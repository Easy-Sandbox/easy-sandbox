"""Remote template index client.

The official and community template catalog lives in a **single source of
truth** repository: ``Easy-Sandbox/awesome-templates``.  Its root index file
(``awesome-templates.yaml``) is what ``ebx template search`` queries and what
``ebx template install <name>`` resolves bare template names against.

Design notes
------------
* The default index URL points at ``raw.githubusercontent.com`` — raw files are
  served by a CDN and are **not** subject to the 60 requests/hour anonymous
  limit of ``api.github.com``.  A ``GITHUB_TOKEN`` is still honoured for
  private mirrors: prefer storing it once with ``ebx config set github_token``;
  ``--token`` remains a one-off override that may leak into shell history and
  process listings.
* The fetched index is cached under ``~/.ebx/index/`` together with metadata
  (``fetched_at`` / ``etag``).  Within ``INDEX_MAX_AGE_SECONDS`` the cache is
  used without touching the network; ``force=True`` (``--refresh``) bypasses it,
  and a conditional request (``If-None-Match``) keeps refreshes cheap.
* Network failures degrade gracefully: when a cached copy exists it is served
  with ``stale=True`` plus a human-readable ``notice``; without a cache the
  error is raised with explicit remediation steps.
* Schema evolution is explicit: the index declares ``schema_version`` (missing
  is treated as :data:`INDEX_SCHEMA_VERSION`, i.e. legacy-compatible).  A newer
  version than this client understands fails loudly instead of being
  misinterpreted.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from easy_sandbox.models.errors import (
    GitHubRateLimitError,
    NetworkError,
    TemplateNotFoundError,
    TemplateParseError,
)
from easy_sandbox.utils.github_token import rate_limit_message, rate_limit_suggestion
from easy_sandbox.utils.logging import get_logger

logger = get_logger("utils.template_index")

#: Canonical index location (single source of truth).
DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/Easy-Sandbox/awesome-templates/main/awesome-templates.yaml"
)

#: Environment variable that overrides the index location.
INDEX_URL_ENV = "EBX_TEMPLATE_INDEX_URL"

#: Local cache location (kept outside ``~/.ebx/templates`` so it is never
#: mistaken for an installed template).
INDEX_CACHE_DIR = Path.home() / ".ebx" / "index"
INDEX_CACHE_FILE = "awesome-templates.yaml"
INDEX_META_FILE = "awesome-templates.meta.json"

#: Index schema version understood by this client.
INDEX_SCHEMA_VERSION = 1

#: Cache freshness window for ``search`` / ``install`` (seconds).
INDEX_MAX_AGE_SECONDS = 3600

_FETCH_TIMEOUT = 20.0

VALID_STATUSES = ("official", "community", "experimental")


@dataclass(frozen=True)
class TemplateIndexEntry:
    """One entry of the remote template index."""

    name: str
    repo: str
    description: str = ""
    path: str | None = None
    ref: str | None = None
    tags: tuple[str, ...] = ()
    author: str = ""
    capabilities: tuple[str, ...] = ()
    status: str = "community"

    @property
    def github_slug(self) -> str:
        """``owner/repo`` part of :attr:`repo` (validated at parse time)."""
        return _parse_repo_slug(self.repo)

    @property
    def install_ref(self) -> str:
        """``owner/repo//path@ref`` ref usable with ``RegistryClient.resolve``."""
        ref = self.github_slug
        if self.path:
            ref = f"{ref}//{self.path.strip('/')}"
        if self.ref:
            ref = f"{ref}@{self.ref}"
        return ref


@dataclass
class TemplateIndex:
    """Parsed remote index plus provenance information."""

    entries: list[TemplateIndexEntry] = field(default_factory=list)
    source_url: str = DEFAULT_INDEX_URL
    schema_version: int = INDEX_SCHEMA_VERSION
    #: ``True`` when the data was served from a stale local cache.
    stale: bool = False
    #: Human-readable explanation attached to degraded states (stale cache,
    #: rate limiting, …).  Empty when the index is fresh.
    notice: str = ""
    fetched_at: float | None = None

    def find(self, name: str) -> TemplateIndexEntry | None:
        """Exact (case-insensitive) lookup by template name."""
        wanted = name.strip().lower()
        for entry in self.entries:
            if entry.name.lower() == wanted:
                return entry
        return None

    def filter(
        self,
        query: str,
        *,
        tag: str | None = None,
        status: str | None = None,
    ) -> list[TemplateIndexEntry]:
        """Substring search over name/description/tags/author + optional filters."""
        query_lower = query.strip().lower()
        tag_lower = tag.strip().lower() if tag else None
        results: list[TemplateIndexEntry] = []
        for entry in self.entries:
            if status and entry.status != status:
                continue
            if tag_lower and tag_lower not in [t.lower() for t in entry.tags]:
                continue
            if query_lower and not (
                query_lower in entry.name.lower()
                or query_lower in entry.description.lower()
                or query_lower in entry.author.lower()
                or any(query_lower in t.lower() for t in entry.tags)
            ):
                continue
            results.append(entry)
        return results


def _parse_repo_slug(repo: str) -> str:
    """Normalise ``repo`` to ``owner/repo``.

    Accepts ``owner/repo``, ``https://github.com/owner/repo`` and
    ``git@github.com:owner/repo.git``.  Any other host is rejected explicitly —
    this client only knows how to fetch from GitHub.
    """
    value = repo.strip()
    if not value:
        raise TemplateParseError("Index entry has an empty 'repo' field.")

    if value.startswith("git@"):
        host, _, path = value.partition(":")
        if "github.com" not in host:
            raise TemplateParseError(
                f"Unsupported template host in index entry: {repo!r}. "
                "Only github.com repositories are supported."
            )
        slug = path
    elif "://" in value:
        parsed = urlparse(value)
        if parsed.hostname not in ("github.com", "www.github.com"):
            raise TemplateParseError(
                f"Unsupported template host in index entry: {repo!r}. "
                "Only github.com repositories are supported."
            )
        slug = parsed.path
    else:
        slug = value

    slug = slug.strip().strip("/")
    if slug.endswith(".git"):
        slug = slug[: -len(".git")]
    parts = [p for p in slug.split("/") if p]
    if len(parts) < 2:
        raise TemplateParseError(
            f"Index entry 'repo' must be 'owner/repo' or a GitHub URL, got {repo!r}."
        )
    return f"{parts[0]}/{parts[1]}"


def _parse_entry(raw: Any, index_url: str) -> TemplateIndexEntry:
    if not isinstance(raw, dict):
        raise TemplateParseError(
            f"Index entry must be a mapping, got {type(raw).__name__} ({index_url})."
        )
    name = str(raw.get("name") or "").strip()
    if not name:
        raise TemplateParseError(f"Index entry is missing the required 'name' field ({index_url}).")
    repo = str(raw.get("repo") or "").strip()
    if not repo:
        raise TemplateParseError(
            f"Index entry '{name}' is missing the required 'repo' field ({index_url})."
        )
    path = raw.get("path")
    ref = raw.get("ref")
    tags = raw.get("tags") or []
    capabilities = raw.get("capabilities") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise TemplateParseError(f"Index entry '{name}': 'tags' must be a list of strings.")
    if not isinstance(capabilities, list) or not all(isinstance(c, str) for c in capabilities):
        raise TemplateParseError(f"Index entry '{name}': 'capabilities' must be a list of strings.")

    entry = TemplateIndexEntry(
        name=name,
        repo=repo,
        description=str(raw.get("description") or ""),
        path=str(path).strip("/") or None if path else None,
        ref=str(ref).strip() or None if ref else None,
        tags=tuple(tags),
        author=str(raw.get("author") or ""),
        capabilities=tuple(capabilities),
        status=str(raw.get("status") or "community"),
    )
    # Fail fast on unusable repo references (also validates the host).
    entry.github_slug  # noqa: B018 - property access raises on bad input
    return entry


def parse_index(
    text: str,
    *,
    source_url: str = DEFAULT_INDEX_URL,
    stale: bool = False,
    notice: str = "",
    fetched_at: float | None = None,
) -> TemplateIndex:
    """Parse the raw YAML of the template index.

    Raises:
        TemplateParseError: malformed YAML, missing ``templates`` list,
            duplicate names, unusable entries, or a ``schema_version`` newer
            than this client supports.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TemplateParseError(f"Template index is not valid YAML ({source_url}): {exc}") from exc

    if not isinstance(data, dict):
        raise TemplateParseError(
            f"Template index must be a YAML mapping with a 'templates' list ({source_url})."
        )

    schema_version = data.get("schema_version", INDEX_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise TemplateParseError(
            f"Template index declares a non-integer schema_version "
            f"({schema_version!r}) at {source_url}."
        )
    if schema_version > INDEX_SCHEMA_VERSION:
        raise TemplateParseError(
            f"Template index schema_version {schema_version} is newer than supported "
            f"schema_version {INDEX_SCHEMA_VERSION}.",
            suggestion="Upgrade easy-sandbox (`pip install -U easy-sandbox`) to read this index.",
        )

    raw_entries = data.get("templates")
    if not isinstance(raw_entries, list):
        raise TemplateParseError(f"Template index has no 'templates' list ({source_url}).")

    entries: list[TemplateIndexEntry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        entry = _parse_entry(raw, source_url)
        key = entry.name.lower()
        if key in seen:
            raise TemplateParseError(
                f"Template index contains duplicate entry '{entry.name}' ({source_url}); "
                "names must be unique for install-by-name resolution."
            )
        seen.add(key)
        entries.append(entry)

    return TemplateIndex(
        entries=entries,
        source_url=source_url,
        schema_version=schema_version,
        stale=stale,
        notice=notice,
        fetched_at=fetched_at,
    )


def _cache_paths(cache_dir: Path | None = None) -> tuple[Path, Path]:
    base = cache_dir or INDEX_CACHE_DIR
    return base / INDEX_CACHE_FILE, base / INDEX_META_FILE


def read_cached_index(cache_dir: Path | None = None) -> TemplateIndex | None:
    """Load the cached index (if any) without touching the network."""
    cache_file, meta_file = _cache_paths(cache_dir)
    if not cache_file.is_file():
        return None
    meta: dict[str, Any] = {}
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive
            meta = {}
    try:
        return parse_index(
            cache_file.read_text(encoding="utf-8"),
            source_url=str(meta.get("source_url") or DEFAULT_INDEX_URL),
            fetched_at=float(meta["fetched_at"]) if "fetched_at" in meta else None,
        )
    except TemplateParseError:
        logger.warning("Ignoring unreadable template index cache at %s", cache_file)
        return None


def _write_cache(
    text: str,
    *,
    source_url: str,
    etag: str | None,
    fetched_at: float,
    cache_dir: Path | None = None,
) -> None:
    cache_file, meta_file = _cache_paths(cache_dir)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
        meta_file.write_text(
            json.dumps(
                {"source_url": source_url, "etag": etag, "fetched_at": fetched_at},
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - defensive (read-only HOME)
        logger.warning("Could not write template index cache: %s", exc)


def _touch_cache_meta(
    *,
    source_url: str,
    etag: str | None,
    fetched_at: float,
    cache_dir: Path | None = None,
) -> None:
    """Refresh the fetch timestamp/etag without rewriting the cached YAML."""
    _, meta_file = _cache_paths(cache_dir)
    try:
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(
            json.dumps(
                {"source_url": source_url, "etag": etag, "fetched_at": fetched_at},
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - defensive (read-only HOME)
        logger.warning("Could not update template index cache metadata: %s", exc)


def _read_cache_meta(cache_dir: Path | None = None) -> dict[str, Any]:
    _, meta_file = _cache_paths(cache_dir)
    if not meta_file.is_file():
        return {}
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive
        return {}
    # A meta file that is not a mapping is treated like a corrupt cache: discard.
    return data if isinstance(data, dict) else {}


def _index_url_from_env_or_default(index_url: str | None) -> str:
    if index_url:
        return index_url
    return os.environ.get(INDEX_URL_ENV) or DEFAULT_INDEX_URL


def _stale_fallback(
    cached: TemplateIndex | None,
    *,
    reason: str,
    index_url: str,
    suggestion: str,
    error_cls: type[NetworkError] = NetworkError,
) -> TemplateIndex:
    if cached is not None:
        cached.stale = True
        cached.notice = f"{reason} Serving the cached index ({cached.source_url})."
        logger.warning(cached.notice)
        return cached
    raise error_cls(
        f"{reason} No cached copy of the template index is available ({index_url}).",
        suggestion=suggestion,
    )


async def fetch_index(
    index_url: str | None = None,
    *,
    token: str | None = None,
    cache_dir: Path | None = None,
    max_age: float = INDEX_MAX_AGE_SECONDS,
    force: bool = False,
) -> TemplateIndex:
    """Return the template index, using the cache when fresh.

    Args:
        index_url: HTTP(S) URL of the index, or a local file path.  Defaults to
            ``EBX_TEMPLATE_INDEX_URL`` and then :data:`DEFAULT_INDEX_URL`.
        token: optional GitHub token (``GITHUB_TOKEN``) for private mirrors.
        cache_dir: override for the cache directory (tests).
        max_age: cache freshness window in seconds.
        force: bypass the freshness window and re-fetch over the network.
    """
    url = _index_url_from_env_or_default(index_url)

    # Local file path → read directly, no caching involved.
    if not url.startswith(("http://", "https://")):
        path = Path(url).expanduser()
        if not path.is_file():
            raise TemplateNotFoundError(
                f"Template index file not found: {path}",
                suggestion=(
                    "Check --index-url / EBX_TEMPLATE_INDEX_URL, or drop the "
                    "override to use the canonical remote index."
                ),
            )
        return parse_index(path.read_text(encoding="utf-8"), source_url=str(path))

    cached = read_cached_index(cache_dir)
    meta = _read_cache_meta(cache_dir)
    now = time.time()

    if (
        cached is not None
        and not force
        and cached.fetched_at is not None
        and (now - cached.fetched_at) < max_age
    ):
        return cached

    headers: dict[str, str] = {"Accept": "application/x-yaml, text/yaml, text/plain, */*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cached is not None and meta.get("etag") and not force:
        headers["If-None-Match"] = str(meta["etag"])

    suggestion = (
        "Check your network connection, or point at a mirror with "
        f"--index-url / {INDEX_URL_ENV}. For GitHub rate limits, authenticate "
        "with 'ebx config set github_token'. As a last resort install directly "
        "with 'ebx template install owner/repo//subdir[@ref]'."
    )

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_FETCH_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return _stale_fallback(
            cached,
            reason=f"Could not reach the template index at {url} ({exc.__class__.__name__}).",
            index_url=url,
            suggestion=suggestion,
        )

    if resp.status_code == 304 and cached is not None:
        cached.fetched_at = now
        _touch_cache_meta(
            source_url=cached.source_url,
            etag=meta.get("etag"),
            fetched_at=now,
            cache_dir=cache_dir,
        )
        return cached

    if resp.status_code in (403, 429):
        remaining = resp.headers.get("X-RateLimit-Remaining")
        try:
            body_text = (resp.text or "").lower()
        except Exception:  # pragma: no cover - defensive
            body_text = ""
        if remaining == "0" or "rate limit" in body_text or resp.status_code == 429:
            return _stale_fallback(
                cached,
                reason=rate_limit_message(operation="fetching the template index"),
                index_url=url,
                suggestion=rate_limit_suggestion(
                    extra=(
                        "Alternatively wait for the window to reset, or point at "
                        f"a mirror via --index-url / {INDEX_URL_ENV}."
                    )
                ),
                error_cls=GitHubRateLimitError,
            )
        return _stale_fallback(
            cached,
            reason=f"Template index request was rejected with HTTP 403 ({url}).",
            index_url=url,
            suggestion=suggestion,
        )

    if resp.status_code == 404:
        return _stale_fallback(
            cached,
            reason=f"Template index not found at {url} (HTTP 404).",
            index_url=url,
            suggestion=(
                "Verify the index URL (--index-url / EBX_TEMPLATE_INDEX_URL); the "
                "repository, branch, or file may have moved."
            ),
        )

    if resp.status_code >= 500:
        return _stale_fallback(
            cached,
            reason=f"Template index server error at {url} (HTTP {resp.status_code}).",
            index_url=url,
            suggestion=suggestion,
        )

    if resp.status_code != 200:
        return _stale_fallback(
            cached,
            reason=f"Unexpected HTTP {resp.status_code} while fetching {url}.",
            index_url=url,
            suggestion=suggestion,
        )

    index = parse_index(resp.text, source_url=url, fetched_at=now)
    _write_cache(
        resp.text,
        source_url=url,
        etag=resp.headers.get("ETag"),
        fetched_at=now,
        cache_dir=cache_dir,
    )
    return index
