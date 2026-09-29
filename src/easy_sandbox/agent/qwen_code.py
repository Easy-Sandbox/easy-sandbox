"""Host-side Qwen Code (https://github.com/QwenLM/qwen-code) adapter.

This is the *local-machine* counterpart of :mod:`easy_sandbox.api.deploy`
(which drives ``qwen`` inside a sandbox).  It locates — or installs — the
official Qwen Code CLI on the host and runs it in headless JSON mode so
that ``ebx create "<description>"`` can generate a Dockerfile and a
``template.yaml`` locally.

Everything below was verified on 2026-09-29 against authoritative sources;
nothing here is guessed:

* Official standalone installers (downloaded and inspected):
  ``https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/``
  ``install-qwen-standalone.sh`` / ``.ps1`` / ``.bat``
* Official docs: ``docs/users/features/headless.md`` and
  ``docs/users/configuration/auth.md`` in the ``QwenLM/qwen-code`` repo.

Verified release facts
----------------------
Standalone assets (name ``qwen-code-<target>.<ext>``):

* ``darwin-x64`` / ``darwin-arm64`` / ``linux-x64`` / ``linux-arm64``
  — ``.tar.gz`` (contain ``qwen-code/bin/qwen`` and
  ``qwen-code/node/bin/node``).
* ``win-x64`` — ``.zip`` (contains ``qwen-code\\bin\\qwen.cmd`` and
  ``qwen-code\\node\\node.exe``).
* There is **no** ``win-arm64`` asset ("RELEASE_TARGETS currently has no
  win-arm64 entry" — official ``.bat`` installer).

Mirrors (both publish ``SHA256SUMS`` next to the asset; lines look like
``<hex>  <name>``, the name optionally prefixed with ``*``):

* Aliyun: ``https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/``
  ``releases/qwen-code/latest/``
* GitHub: ``https://github.com/QwenLM/qwen-code/releases/latest/download``

Headless interface (re-verified against qwen-code 0.15.11 on 2026-09-29):
``qwen "<prompt>" --output-format json --yolo``.  The prompt is a
**positional argument** — the legacy ``-p``/``--prompt`` flag is deprecated
upstream (``--help`` prints "Use the positional prompt instead") and must
not be used.  An optional turn budget travels as the official
``--max-session-turns`` flag (exposed as the ``max_session_turns`` keyword
argument of :func:`run_qwen_code_headless`); qwen-code exits with code 53
when it is exceeded.  Do **not** use the distinct upstream
``--max-tool-calls`` flag for this purpose — it bounds cumulative tool calls
(exit code 55), not session turns.

Native session + structured output (re-verified against qwen-code
0.15.11 on 2026-09-29): ``--session-id <uuid>`` pins/creates a session
for the run and ``--resume <uuid>`` continues one; the CLI validates the
ID (a malformed or unknown ID fails with exit code 1) and rejects
passing both flags at once.  ``--json-schema`` (headless only) registers
a synthetic ``structured_output`` tool: the session ends on the first
valid call and the terminal ``result`` message then carries
``structured_result`` (the validated object, with ``result`` holding its
JSON string) next to ``session_id``.  Sessions are stored per working
directory, so every round of one session must share the same ``cwd``.

stdout is a JSON array of session messages; the final object with
``type == "result"`` carries ``result`` (final text) and ``is_error``.

Auth interface (headless): ``OPENAI_API_KEY`` + ``OPENAI_BASE_URL`` +
``OPENAI_MODEL`` (OpenAI-compatible DashScope endpoint), or
``DASHSCOPE_API_KEY`` / ``BAILIAN_CODING_PLAN_API_KEY``, or a preset
``~/.qwen/settings.json``.  This is the same credential family that
``ebx`` already stores for LLM inference, so a stored ``llm_api_key`` is
an officially compatible fallback (see :func:`resolve_qwen_code_credentials`).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from easy_sandbox.models.errors import (
    AICodegenError,
    QwenCodeCredentialError,
    QwenCodeNotInstalledError,
)
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = get_logger("agent.qwen_code")

# ---------------------------------------------------------------------------
# Verified constants
# ---------------------------------------------------------------------------

_SUPPORTED_TARGETS: tuple[str, ...] = (
    "darwin-x64",
    "darwin-arm64",
    "linux-x64",
    "linux-arm64",
    "win-x64",
)

_ALIYUN_RELEASE_BASE = (
    "https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/releases/qwen-code/latest"
)
_GITHUB_RELEASE_BASE = "https://github.com/QwenLM/qwen-code/releases/latest/download"

#: ``(label, base_url)`` pairs, tried in order (Aliyun first, GitHub fallback).
_STANDALONE_MIRRORS: tuple[tuple[str, str], ...] = (
    ("aliyun", _ALIYUN_RELEASE_BASE),
    ("github", _GITHUB_RELEASE_BASE),
)

_CHECKSUM_NAME = "SHA256SUMS"
_DEFAULT_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DEFAULT_OPENAI_MODEL = "qwen3-coder-plus"
_USER_AGENT = "easy-sandbox-qwen-code/1.0"

#: Environment variables that mean "the user already configured auth".
_EXISTING_AUTH_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "DASHSCOPE_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
)


class _ChecksumMismatchError(Exception):
    """Archive SHA256 does not match the checksum published by the mirror."""


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QwenCodeCredentials:
    """Resolved Qwen Code model credentials.

    ``source`` is one of:

    * ``qwen-stored`` — dedicated ``qwen_code_api_key`` stored by ebx.
    * ``llm-stored`` — compatible fallback to the stored ``llm_api_key``.
    * ``environment`` — a valid variable already exists in the process
      environment, so the child process inherits it (no injection).
    * ``qwen-settings`` — ``~/.qwen/settings.json`` is already configured
      (no injection).
    """

    source: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @property
    def needs_env_injection(self) -> bool:
        """Whether ebx must inject ``OPENAI_*`` variables for the child."""
        return self.source in ("qwen-stored", "llm-stored")

    def as_env(self) -> dict[str, str]:
        """Environment variables to inject (empty when nothing is needed)."""
        if not self.needs_env_injection:
            return {}
        envs = {"OPENAI_API_KEY": self.api_key}
        if self.base_url:
            envs["OPENAI_BASE_URL"] = self.base_url
        if self.model:
            envs["OPENAI_MODEL"] = self.model
        return envs


@dataclass
class QwenCodeRunResult:
    """Raw outcome of one headless ``qwen`` invocation."""

    text: str = ""
    """Final assistant text (the ``result`` message payload)."""

    is_error: bool = False
    """``True`` when the CLI reported ``is_error`` or emitted no result."""

    exit_code: int = -1
    raw_stdout: str = ""
    raw_stderr: str = ""

    structured: Any = None
    """``structured_result`` payload of a ``--json-schema`` run, else ``None``."""

    session_id: str = ""
    """Session ID reported by the CLI (``--session-id`` / ``--resume`` runs)."""


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def detect_standalone_target(
    *,
    system: str | None = None,
    machine: str | None = None,
) -> str | None:
    """Return the official standalone target for this platform.

    Returns ``None`` when the platform has no official standalone build
    (e.g. Windows on ARM64, or any non darwin/linux/win OS).  ``system``
    and ``machine`` default to :func:`platform.system` /
    :func:`platform.machine` and may be overridden for testing.
    """
    sys_name = (system if system is not None else platform.system()).strip().lower()
    arch_name = (machine if machine is not None else platform.machine()).strip().lower()

    if sys_name == "darwin":
        os_id = "darwin"
    elif sys_name == "linux":
        os_id = "linux"
    elif sys_name in ("windows", "win32", "cygwin", "msys"):
        os_id = "win"
    else:
        return None

    if arch_name in ("x86_64", "amd64", "x64"):
        arch_id = "x64"
    elif arch_name in ("arm64", "aarch64"):
        arch_id = "arm64"
    else:
        return None

    if os_id == "win" and arch_id != "x64":
        # Verified: the official release matrix has no win-arm64 asset.
        return None

    target = f"{os_id}-{arch_id}"
    return target if target in _SUPPORTED_TARGETS else None


def standalone_asset_name(target: str) -> str:
    """Return the official asset file name for *target*.

    Raises:
        ValueError: If *target* is not part of the official matrix.
    """
    if target not in _SUPPORTED_TARGETS:
        raise ValueError(f"Unsupported Qwen Code standalone target: {target!r}")
    ext = "zip" if target.startswith("win-") else "tar.gz"
    return f"qwen-code-{target}.{ext}"


def standalone_download_urls(target: str) -> list[tuple[str, str]]:
    """Return ``(mirror_label, archive_url)`` pairs for *target*, in order."""
    asset = standalone_asset_name(target)
    return [(label, f"{base}/{asset}") for label, base in _STANDALONE_MIRRORS]


def official_install_command(*, windows: bool | None = None) -> str:
    """Return the verified official one-line installer command."""
    is_win = (os.name == "nt") if windows is None else windows
    if is_win:
        return (
            'powershell -NoProfile -Command "irm '
            "https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/"
            'install-qwen-standalone.ps1 | iex"'
        )
    return (
        "curl -fsSL "
        "https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/"
        "install-qwen-standalone.sh | bash"
    )


def default_bin_dir() -> Path:
    """Managed install directory: ``~/.ebx/bin``."""
    return Path.home() / ".ebx" / "bin"


def _binary_names(*, windows: bool | None = None) -> tuple[str, ...]:
    is_win = (os.name == "nt") if windows is None else windows
    if is_win:
        return ("qwen.cmd", "qwen.exe", "qwen.bat")
    return ("qwen",)


def find_qwen_code_binary(
    *,
    bin_dir: Path | None = None,
    windows: bool | None = None,
) -> Path | None:
    """Locate the Qwen Code executable.

    Lookup order:

    1. ``EBX_QWEN_CODE_BIN`` override (absolute path to an executable).
    2. The managed directory ``~/.ebx/bin`` (installed by ebx itself).
    3. ``PATH`` (``shutil.which``; honours ``PATHEXT`` on Windows).

    Returns ``None`` when nothing usable is found.
    """
    override = os.environ.get("EBX_QWEN_CODE_BIN")
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None

    is_win = (os.name == "nt") if windows is None else windows
    managed = Path(bin_dir) if bin_dir is not None else default_bin_dir()
    for name in _binary_names(windows=is_win):
        candidate = managed / name
        if candidate.is_file() and (is_win or os.access(candidate, os.X_OK)):
            return candidate

    found = shutil.which("qwen")
    if found:
        return Path(found)
    return None


# ---------------------------------------------------------------------------
# Installation (download + checksum + atomic swap)
# ---------------------------------------------------------------------------


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _download_to_file(url: str, dest: Path, *, timeout: float) -> None:
    """Download *url* into *dest* using urllib (no third-party deps)."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with (
        urllib.request.urlopen(request, timeout=timeout) as response,
        open(dest, "wb") as handle,
    ):
        shutil.copyfileobj(response, handle)


def _http_get_text(url: str, *, timeout: float) -> str:
    """Fetch a small text resource (``SHA256SUMS``)."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: bytes = response.read()
    return payload.decode("utf-8", errors="replace")


def _parse_sha256sums(text: str) -> dict[str, str]:
    """Parse ``SHA256SUMS`` content into ``{file_name: hex_digest}``."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        digest = parts[0].strip().lower()
        name = parts[-1].lstrip("*")
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            result[name] = digest
    return result


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_tar_members(dest: Path, members: list[tarfile.TarInfo]) -> None:
    root = dest.resolve()
    for member in members:
        target = (dest / member.name).resolve()
        if not _is_within(target, root):
            raise QwenCodeNotInstalledError(
                f"Refusing to extract archive entry outside destination: {member.name!r}"
            )
        if member.issym() or member.islnk():
            link = PurePosixPath(member.linkname)
            if link.is_absolute() or not _is_within((dest / link).resolve(), root):
                raise QwenCodeNotInstalledError(
                    f"Refusing to extract unsafe link in archive: {member.name!r}"
                )


def _extract_tar(archive: Path, dest: Path) -> None:
    """Safely extract a ``.tar.gz`` archive into *dest*."""
    with tarfile.open(archive, "r:*") as handle:
        members = handle.getmembers()
        _validate_tar_members(dest, members)
        try:
            handle.extractall(dest, filter="data")
        except TypeError:
            # Python < 3.11.4 has no ``filter`` parameter; members were
            # validated above.
            handle.extractall(dest)


def _extract_zip(archive: Path, dest: Path) -> None:
    """Safely extract a ``.zip`` archive into *dest*."""
    root = dest.resolve()
    with zipfile.ZipFile(archive) as handle:
        for name in handle.namelist():
            if not _is_within((dest / name).resolve(), root):
                raise QwenCodeNotInstalledError(
                    f"Refusing to extract archive entry outside destination: {name!r}"
                )
        handle.extractall(dest)


def _extract_archive(archive: Path, dest: Path, target: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if target.startswith("win-"):
        _extract_zip(archive, dest)
    else:
        _extract_tar(archive, dest)


def _entry_relative_path(target: str) -> Path:
    """Archive-relative entry point (verified layout)."""
    name = "qwen.cmd" if target.startswith("win-") else "qwen"
    return Path("qwen-code") / "bin" / name


def _node_relative_path(target: str) -> Path:
    if target.startswith("win-"):
        return Path("qwen-code") / "node" / "node.exe"
    return Path("qwen-code") / "node" / "bin" / "node"


def _validate_archive_layout(extract_dir: Path, target: str) -> None:
    """Ensure the extracted archive matches the official layout."""
    entry = extract_dir / _entry_relative_path(target)
    node = extract_dir / _node_relative_path(target)
    missing: list[str] = []
    if not entry.is_file():
        missing.append(str(_entry_relative_path(target)))
    if not node.is_file():
        missing.append(str(_node_relative_path(target)))
    if missing:
        raise QwenCodeNotInstalledError(
            f"Downloaded Qwen Code archive has an unexpected layout; missing: {', '.join(missing)}."
        )
    if not target.startswith("win-"):
        for path in (entry, node):
            os.chmod(path, 0o755)


def _write_wrapper(wrapper: Path, entry: Path, *, windows: bool) -> None:
    """Atomically write the ``qwen`` wrapper script pointing at *entry*."""
    if windows:
        content = f'@echo off\r\ncall "{entry}" %*\r\n'
    else:
        # Single-quote shell escaping so paths with spaces still work.
        quoted = "'" + str(entry).replace("'", "'\"'\"'") + "'"
        content = f'#!/usr/bin/env sh\nexec {quoted} "$@"\n'
    tmp = wrapper.with_name(wrapper.name + ".new")
    tmp.write_text(content, encoding="utf-8", newline="")
    if not windows:
        os.chmod(tmp, 0o755)
    os.replace(tmp, wrapper)


def download_and_install_standalone(
    *,
    target: str | None = None,
    bin_dir: Path | None = None,
    timeout: float = 180.0,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Download, verify, and install the official Qwen Code standalone build.

    The archive is downloaded from the Aliyun mirror first with a GitHub
    fallback, its SHA256 is verified against the mirror's ``SHA256SUMS``
    (a mismatch aborts immediately — no silent retry with an unverified
    binary), and the install directory is swapped atomically.

    Returns the path of the installed ``qwen`` wrapper
    (``~/.ebx/bin/qwen`` or ``qwen.cmd``).

    Raises:
        QwenCodeNotInstalledError: On unsupported platforms or when every
            mirror fails, or when integrity verification fails.
    """

    def progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    resolved_target = target if target is not None else detect_standalone_target()
    if resolved_target is None:
        raise QwenCodeNotInstalledError(
            f"No official Qwen Code standalone build for {platform.system()} {platform.machine()}.",
            suggestion=(
                "Install Qwen Code manually with the official installer: "
                f"{official_install_command()}"
            ),
        )

    is_win = resolved_target.startswith("win-")
    asset = standalone_asset_name(resolved_target)
    dest_bin = Path(bin_dir) if bin_dir is not None else default_bin_dir()
    dest_bin.mkdir(parents=True, exist_ok=True)

    staging = dest_bin / ".qwen-code-staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    archive_path = staging / asset
    extract_dir = staging / "extract"

    failures: list[str] = []
    installed = False
    for label, url in standalone_download_urls(resolved_target):
        try:
            progress(f"Downloading {asset} from {label} mirror...")
            _download_to_file(url, archive_path, timeout=timeout)

            progress("Verifying SHA256 checksum...")
            base = url.rsplit("/", 1)[0]
            sums = _parse_sha256sums(_http_get_text(f"{base}/{_CHECKSUM_NAME}", timeout=timeout))
            expected = sums.get(asset)
            if not expected:
                raise QwenCodeNotInstalledError(
                    f"{_CHECKSUM_NAME} from {label} has no entry for {asset}; "
                    "refusing to install an unverified binary."
                )
            actual = _sha256_of(archive_path)
            if actual != expected:
                raise _ChecksumMismatchError(
                    f"SHA256 mismatch for {asset}: expected {expected}, got {actual}."
                )

            progress("Extracting archive...")
            _extract_archive(archive_path, extract_dir, resolved_target)
            _validate_archive_layout(extract_dir, resolved_target)
            installed = True
            break
        except _ChecksumMismatchError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise QwenCodeNotInstalledError(
                f"Qwen Code archive failed integrity verification: {exc}",
                suggestion=(
                    "Do not retry blindly; the download may be corrupted or "
                    "tampered with. Retry once, and if it persists install "
                    f"manually: {official_install_command()}"
                ),
            ) from exc
        except Exception as exc:  # mirror-specific failure: try the next one
            logger.debug("Mirror %s failed: %s", label, exc)
            failures.append(f"{label}: {exc}")
            archive_path.unlink(missing_ok=True)
            shutil.rmtree(extract_dir, ignore_errors=True)

    if not installed:
        shutil.rmtree(staging, ignore_errors=True)
        raise QwenCodeNotInstalledError(
            "Failed to download a verified Qwen Code standalone archive "
            "from all official mirrors. " + " | ".join(failures),
            suggestion=(
                "Check network access to qwen-code-assets.oss-cn-hangzhou.aliyuncs.com "
                "and github.com, or install manually: "
                f"{official_install_command()}"
            ),
        )

    # Atomic swap: staged extraction -> lib dir, then write the wrapper.
    install_lib = dest_bin / "qwen-code"
    new_lib = dest_bin / ".qwen-code.new"
    old_lib = dest_bin / ".qwen-code.old"
    shutil.rmtree(new_lib, ignore_errors=True)
    shutil.rmtree(old_lib, ignore_errors=True)
    shutil.move(str(extract_dir / "qwen-code"), str(new_lib))

    if install_lib.exists():
        shutil.move(str(install_lib), str(old_lib))
    try:
        os.replace(new_lib, install_lib)
    except OSError:
        if not install_lib.exists() and old_lib.exists():
            shutil.move(str(old_lib), str(install_lib))
        raise
    shutil.rmtree(old_lib, ignore_errors=True)

    wrapper = dest_bin / _binary_names(windows=is_win)[0]
    progress(f"Installing Qwen Code into {dest_bin}...")
    entry_name = "qwen.cmd" if is_win else "qwen"
    _write_wrapper(wrapper, install_lib / "bin" / entry_name, windows=is_win)

    shutil.rmtree(staging, ignore_errors=True)
    return wrapper


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _qwen_settings_configured(settings_path: Path | None = None) -> bool:
    """Whether ``~/.qwen/settings.json`` already carries model auth config."""
    path = settings_path
    if path is None:
        path = Path.home() / ".qwen" / "settings.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("modelProviders") or data.get("env"))


def resolve_qwen_code_credentials(
    *,
    stored_api_key: str | None = None,
    llm_api_key: str | None = None,
    stored_base_url: str | None = None,
    stored_model: str | None = None,
    environ: Mapping[str, str] | None = None,
    settings_path: Path | None = None,
) -> QwenCodeCredentials:
    """Resolve credentials for the Qwen Code headless run.

    Resolution order (first hit wins):

    1. ``qwen_code_api_key`` stored by ebx (``source="qwen-stored"``).
    2. The ebx ``llm_api_key`` — officially compatible: Qwen Code accepts
       OpenAI-compatible / DashScope keys through the ``OPENAI_*``
       variables, which is exactly what ``llm_api_key`` is
       (``source="llm-stored"``).
    3. A valid variable already present in the process environment
       (``OPENAI_API_KEY`` / ``DASHSCOPE_API_KEY`` /
       ``BAILIAN_CODING_PLAN_API_KEY``) — inherited by the child process,
       nothing is injected (``source="environment"``).
    4. A configured ``~/.qwen/settings.json`` (``source="qwen-settings"``).

    Raises:
        QwenCodeCredentialError: When none of the sources is available.
    """
    env = os.environ if environ is None else environ
    base_url = stored_base_url or _DEFAULT_OPENAI_BASE_URL
    model = stored_model or _DEFAULT_OPENAI_MODEL

    if stored_api_key:
        return QwenCodeCredentials(
            source="qwen-stored", api_key=stored_api_key, base_url=base_url, model=model
        )
    if llm_api_key:
        return QwenCodeCredentials(
            source="llm-stored", api_key=llm_api_key, base_url=base_url, model=model
        )
    for var in _EXISTING_AUTH_ENV_VARS:
        value = env.get(var)
        if value:
            return QwenCodeCredentials(source="environment", api_key=value)
    if _qwen_settings_configured(settings_path):
        return QwenCodeCredentials(source="qwen-settings")

    raise QwenCodeCredentialError(
        "Qwen Code is installed but no model credentials were found.",
        suggestion=(
            "Store a DashScope/ModelStudio API key with "
            "'ebx config set qwen_code_api_key <KEY>' (or run "
            "'ebx config init'), export OPENAI_API_KEY / DASHSCOPE_API_KEY, "
            "or configure Qwen Code interactively once via 'qwen'."
        ),
    )


# ---------------------------------------------------------------------------
# Headless execution
# ---------------------------------------------------------------------------


def _build_headless_command(
    binary: Path,
    prompt: str,
    *,
    max_session_turns: int | None = None,
    session_id: str | None = None,
    resume: str | None = None,
    json_schema: Mapping[str, Any] | str | None = None,
    windows: bool | None = None,
) -> list[str]:
    """Build the argv for ``qwen`` headless JSON mode.

    The prompt travels as a single positional argv element (never through
    a shell, never via the deprecated ``-p`` flag).

    * ``max_session_turns`` — forwarded as the official
      ``--max-session-turns`` flag (qwen-code exits with code 53 once the
      user/model/tool turn budget is exceeded); ``None`` adds no flag.
    * ``session_id`` — forwarded as the official ``--session-id`` flag
      (must be a valid UUID; creates/pins the native session).
    * ``resume`` — forwarded as the official ``--resume`` flag (continue
      an existing session).  The CLI rejects passing both session flags,
      so ``resume`` wins when both are set.
    * ``json_schema`` — forwarded as the official ``--json-schema`` flag.
      A mapping is dumped to a JSON literal; a string is passed through
      (the CLI also accepts ``@path/to/schema.json``).

    On Windows the managed wrapper is a ``.cmd`` shim which
    ``CreateProcess`` cannot launch directly, so it is wrapped in
    ``cmd.exe /c`` — the same approach the official installer uses.
    """
    argv = [str(binary), prompt, "--output-format", "json", "--yolo"]
    if json_schema is not None:
        schema_text = (
            json_schema
            if isinstance(json_schema, str)
            else json.dumps(json_schema, ensure_ascii=False)
        )
        argv += ["--json-schema", schema_text]
    if resume is not None:
        argv += ["--resume", str(resume)]
    elif session_id is not None:
        argv += ["--session-id", str(session_id)]
    if max_session_turns is not None:
        argv += ["--max-session-turns", str(max_session_turns)]
    is_win = (os.name == "nt") if windows is None else windows
    if is_win and binary.suffix.lower() in (".cmd", ".bat"):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", *argv]
    return argv


def _maybe_json_object(text: str) -> Any:
    """Parse *text* when it is a JSON object/array document, else ``None``."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _parse_headless_output(stdout: str) -> tuple[str, bool, Any, str]:
    """Extract ``(result_text, is_error, structured, session_id)``.

    The CLI emits a JSON array of session messages; the last message with
    ``type == "result"`` carries the answer.  For ``--json-schema`` runs
    the message also carries ``structured_result`` (the validated object)
    and ``session_id``; when ``structured_result`` is absent the ``result``
    string is parsed instead if it is a JSON object.  Individual lines are
    also tried so that stray log lines do not break parsing.  Returns
    ``("", True, None, "")`` when no result message can be found.
    """
    candidates = [stdout.strip()]
    candidates.extend(line.strip() for line in stdout.splitlines())
    for candidate in candidates:
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            data: Any = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        messages = data if isinstance(data, list) else [data]
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("type") != "result":
                continue
            result = message.get("result", "")
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            structured = message.get("structured_result")
            if structured is None:
                structured = _maybe_json_object(result)
            session_id = message.get("session_id")
            return (
                result,
                bool(message.get("is_error", False)),
                structured,
                session_id if isinstance(session_id, str) else "",
            )
    return "", True, None, ""


def run_qwen_code_headless(
    prompt: str,
    *,
    binary: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
    timeout: float = 600.0,
    max_session_turns: int | None = None,
    session_id: str | None = None,
    resume: str | None = None,
    json_schema: Mapping[str, Any] | str | None = None,
) -> QwenCodeRunResult:
    """Run ``qwen`` in headless JSON mode and return its raw result.

    The subprocess is spawned with an argv list (``shell=False``), a
    bounded cwd, an explicit timeout, and — when credentials were stored
    by ebx — the ``OPENAI_*`` variables merged into a copy of the current
    environment.  Nothing else about the environment is modified.

    ``max_session_turns`` (optional) is forwarded to qwen-code as the
    official ``--max-session-turns`` flag; ``None`` adds no turn flag.
    ``session_id`` / ``resume`` use the native session flags
    (``resume`` wins when both are given), and ``json_schema`` requests
    the structured ``structured_output`` result — see
    :func:`_build_headless_command`.

    Raises:
        QwenCodeNotInstalledError: When no executable can be located.
        AICodegenError: On timeout, spawn failure, or a missing cwd.
    """
    binary_path = Path(binary) if binary is not None else find_qwen_code_binary()
    if binary_path is None:
        raise QwenCodeNotInstalledError(
            "Qwen Code executable was not found on PATH or in ~/.ebx/bin.",
            suggestion=(
                "Re-run the command in a terminal to install it, or install "
                f"manually: {official_install_command()}"
            ),
        )
    if cwd is not None and not Path(cwd).is_dir():
        raise AICodegenError(f"Working directory does not exist: {cwd}")

    argv = _build_headless_command(
        binary_path,
        prompt,
        max_session_turns=max_session_turns,
        session_id=session_id,
        resume=resume,
        json_schema=json_schema,
    )
    run_env = {**os.environ, **env} if env else None
    logger.debug("Running Qwen Code headless via %s", argv[0])

    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise AICodegenError(
            f"Qwen Code did not finish within {timeout:.0f}s and was terminated.",
            suggestion=(
                "Retry with a shorter description or raise the limit with "
                "EBX_QWEN_CODEGEN_TIMEOUT (seconds)."
            ),
        ) from None
    except OSError as exc:
        raise AICodegenError(f"Failed to start Qwen Code: {exc}") from exc

    text, is_error, structured, reported_session_id = _parse_headless_output(completed.stdout or "")
    return QwenCodeRunResult(
        text=text,
        is_error=is_error,
        exit_code=completed.returncode,
        raw_stdout=completed.stdout or "",
        raw_stderr=completed.stderr or "",
        structured=structured,
        session_id=reported_session_id,
    )
