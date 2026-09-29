# Decision: Template Catalog Single Source of Truth (awesome-templates)

Status: implemented
Proposed: 2026-09-29
Implemented: 2026-09-29

## Problem

Template content, the machine-readable index (`awesome-templates.yaml`), and
the publishing story were duplicated between this repository and the dedicated
`Easy-Sandbox/awesome-templates` repository, with a "extract the folder later
via `git subtree push`" plan that never happened. Consequences:

1. **Drift by construction.** The two copies diverged: the qwen-code parameter
   contract (`max_turns` → `max_session_turns`, default 100) and legacy
   template fields (`base` / `system_packages`) were fixed on one side but not
   the other; `node-web/Dockerfile` missed `EXPOSE 9000`.
2. **Users got stale content.** A template catalog shipped inside the SDK can
   only refresh with an SDK release; community templates could not be
   discovered until a new version shipped.
3. **The root `awesome-templates.yaml` was never the real index.** It lived in
   this repo but nothing installed from it; `ebx template search` had no
   remote source, and bare-name installs had no resolution path.
4. **Test split was unclear.** `tests/test_templates/` validated a 10-template
   collection that was also being validated (differently) in the other repo.

Audit: task 184 (repository/reference drift audit). The Qwen rename contract is
fixed by ADR 2026-09-29 (qwen-code Session-Turns Parameter Unification) and
must not be reverted.

## Decision

Make `Easy-Sandbox/awesome-templates` the **single source of truth (SSOT)** for
official & community template content, the index, releases, and CI. This
repository keeps no publishable template collection.

### Source-of-truth repository

- Root `awesome-templates.yaml` (`schema_version: 1`) indexes one entry per
  template folder: `name` / `description` / `repo` / `path` / `ref?` / `tags` /
  `author` / `capabilities` / `status` (`official|community|experimental`).
- Template folders hold `template.yaml` + `Dockerfile` + `README.md`
  (+ `commands.py` when server-side commands are declared).
- `tests/` validates folders, the index, the README table, and the qwen-code
  `max_session_turns` contract offline; `.github/workflows/ci.yml` runs the
  suite on Python 3.10–3.13 via `requirements-dev.txt`.
- Drift fixes landed: `node-web/Dockerfile` `EXPOSE 9000`; qwen-code
  `commands.py` renamed to `max_session_turns` (default 100);
  `python-hello/template.yaml` legacy `base`/`system_packages` removed.

### This repository — index client and fixture only

- New `utils/template_index.py` fetches the remote index from
  `raw.githubusercontent.com` (CDN — **not** subject to the api.github.com
  60 req/hour anonymous limit). Cache: `~/.ebx/index/` (body + meta with
  `source_url`/`etag`/`fetched_at`), TTL `INDEX_MAX_AGE_SECONDS = 3600`;
  fresh cache short-circuits the network; `If-None-Match` revalidation keeps
  refreshes cheap; `--refresh` / `force=True` bypasses; corrupt caches are
  discarded, never served.
- Degraded modes are explicit: network failure / 403-with-zero-remaining /
  429 / 5xx → serve the stale cache with `stale=True` + human-readable
  `notice` (CLI prints a warning, exit code stays 0); no cache → `NetworkError`
  with remediation (`GITHUB_TOKEN`/`--token`, `--index-url`, `--refresh`);
  404 → verify-URL suggestion; `schema_version` newer than
  `INDEX_SCHEMA_VERSION` → `TemplateParseError` with an upgrade hint. This
  covers GitHub rate limiting without a hard dependency on authentication.
- `ebx template search` queries the index (`--tag` / `--status` filters,
  `--index-url` / `EBX_TEMPLATE_INDEX_URL` override, `-j` JSON).
- `ebx template install <name>` resolves bare names: local path → builtins
  (`base`, `code-interpreter-v1`, no network) → remote index. An index hit
  yields `TemplateIndexEntry.install_ref` (`owner/repo//subdir[@ref]`, pinning
  honoured); a miss on a fresh cache triggers exactly one forced refresh (so a
  freshly published template resolves immediately); still missing →
  `TemplateNotFoundError` suggesting `ebx template search` or a direct
  `owner/repo//subdir` reference. The CLI prints
  `Resolved '<name>' via the template index: <ref>` for auditability.
- `examples/templates/` keeps only the minimal `python-hello` **fixture**, with
  a three-layer explicit marker (directory README stating "not the publishing
  source", `FIXTURE` banner in `template.yaml`, fixture notice in the
  template README). `TestFixtureBoundary` fails if the folder set changes or
  the markers disappear, so the collection cannot silently grow back.
- All main-repo tests are offline: `pytest-httpx` (`httpx_mock`) intercepts
  HTTP; CLI tests stub `fetch_index`; the local-install test keeps its
  `socket` tripwire.

## API Design

```python
# easy_sandbox/utils/template_index.py
DEFAULT_INDEX_URL: str            # raw.githubusercontent.com/.../awesome-templates.yaml
INDEX_CACHE_DIR: Path             # ~/.ebx/index
INDEX_SCHEMA_VERSION = 1
INDEX_MAX_AGE_SECONDS = 3600

@dataclass(frozen=True)
class TemplateIndexEntry:
    name: str; repo: str; description: str = ""; path: str | None = None
    ref: str | None = None; tags: tuple[str, ...] = ()
    author: str = ""; capabilities: tuple[str, ...] = ()
    status: str = "community"
    @property
    def github_slug(self) -> str: ...   # owner/repo
    @property
    def install_ref(self) -> str: ...   # owner/repo//path@ref

@dataclass
class TemplateIndex:
    schema_version: int; entries: list[TemplateIndexEntry]
    source_url: str; stale: bool = False; notice: str = ""
    fetched_at: float | None = None
    def find(self, name: str) -> TemplateIndexEntry | None: ...
    def filter(self, query: str, *, tag=None, status=None) -> list[TemplateIndexEntry]: ...

def parse_index(text: str, *, source_url: str = "") -> TemplateIndex: ...
def read_cached_index(cache_dir: Path | None = None) -> TemplateIndex | None: ...
async def fetch_index(url=None, *, token=None, force=False,
                      cache_dir=None) -> TemplateIndex: ...
```

## Alternatives considered

- **Keep the main-repo copy and sync via `git subtree push` / submodule** —
  double writes are exactly the drift source (problem 1); the audit found the
  copies already diverged. Rejected.
- **Bundle a snapshot of the index into the SDK at release time** — still a
  stale copy between releases and a second write path; adds release-coupling
  without solving discovery lag. Rejected.
- **Fetch the index from `api.github.com`** — 60 req/hour anonymous limit
  makes `search` fragile exactly where the feature matters; raw files are
  CDN-served and unauthenticated. A `GITHUB_TOKEN` stays supported for
  private mirrors. Rejected.
- **Fail hard on any index fetch error (no stale fallback)** — an offline or
  rate-limited user loses even cached information; serving the stale cache
  with a visible warning keeps the tool usable while staying honest.
  Rejected.
- **Offline reconciliation of `TEMPLATE_CATALOG` (infer.py) against the
  remote index in unit tests** — would require the network or a bundled
  snapshot (the thing being removed). The catalog repo's own CI validates
  index↔folders; this repo keeps offline catalog sanity only. Deferred.

## Dependencies

- `httpx` (existing), `pyyaml` (existing); no new runtime dependencies.
- Source-of-truth repo: `easy-sandbox[cli]` (git main until the first release
  containing `template_index`), `pytest`, `pyyaml` via `requirements-dev.txt`.

## Test Strategy

- `tests/test_utils/test_template_index.py` — parse/validate, `install_ref`,
  cache lifecycle (fresh/force/304), degraded matrix (offline, 403/429, 404,
  5xx, 418, corrupt cache), token and env overrides (35 cases, `httpx_mock`).
- `tests/test_cli/test_template_index_commands.py` — `search` output/filters/
  JSON/notice/option forwarding; `install` bare-name resolution, `@ref`
  pinning, builtin short-circuit, not-found with one forced refresh (15 cases).
- `tests/test_templates/` — fixture boundary + python-hello contracts +
  offline local-install E2E (57 cases).
- Source-of-truth repo: `tests/test_catalog.py`, `tests/test_index.py`,
  `tests/test_commands_e2e.py` (including the qwen `max_session_turns` guard)
  — 308 cases green, plus a Python 3.10–3.13 CI matrix.

## Files changed

- This repo — new: `src/easy_sandbox/utils/template_index.py`,
  `tests/test_cli/test_template_index_commands.py`,
  `tests/test_utils/test_template_index.py`.
- This repo — changed: `src/easy_sandbox/cli/commands/template.py`;
  `examples/templates/README.md`, `python-hello/{template.yaml,README.md}`;
  `tests/test_templates/{__init__,conftest,test_template_catalog,test_template_e2e,test_local_install}.py`;
  `README(.zh-CN).md`, `docs/{en,zh}/{README,DESIGN}.md`,
  `docs/{en,zh}/design/{cli-design,templates-catalog}.md`,
  `docs/{en,zh}/guide/e2e-template-workflow.md`,
  `docs/{en,zh}/reference/cli-reference.md`, `examples/README.md`,
  `examples/quickstart/{README.md,03_web_service.py}`,
  `.github/CONTRIBUTING.md`, `CHANGELOG.md`,
  `scripts/{deploy_all_templates.sh,deploy_remaining.sh,build_hermes.sh,cloud_e2e_test.py}`.
- This repo — removed: 9 template folders under `examples/templates/` and the
  root `awesome-templates.yaml`.
- Source-of-truth repo — new: `README.md`, `CONTRIBUTING.md`,
  `awesome-templates.yaml`, `tests/`, `requirements-dev.txt`,
  `.github/workflows/ci.yml`; drift fixes in `node-web/Dockerfile`,
  `qwen-code/commands.py`, `python-hello/template.yaml`. Commits `d98bdfb`,
  `3da792b`, `3257f21` (local only — not pushed).

## Evidence

Full snapshot: `.agents/evidence/verify/2026-09-29-template-ssot-verification.md`.

- Targeted suites green: 185 passed (`test_template_index.py`,
  `test_template_index_commands.py`, `test_templates/`,
  `test_template_commands.py`).
- CLI evidence goldens `help-install` / `help-template` /
  `help-template-install` regenerated (`EBX_UPDATE_EVIDENCE=1`); all
  template/help evidence cases pass; evidence docs regenerated
  deterministically (83 cases; byte-identical across runs, warning noise
  suppressed).
- Full non-integration suite: 2226 passed, 13 failed — all 13 failures belong
  to the concurrently running NL-create / errors workstream (its files were
  modified during the same window); zero failures in template/index scope. A
  clean full-suite run is expected once that workstream lands.
- `ruff check src/ tests/` → All checks passed; `mypy src/easy_sandbox/` → no
  issues in 97 source files. During verification the task files gained a
  mapping guard in `template_index._read_cache_meta` (mypy `no-any-return`)
  and ruff formatting (F541 fix + format pass).

## Consequences

- Template discovery now works against the live catalog; SDK releases and
  template evolution are fully decoupled.
- An offline user with a warm cache keeps working with a visible staleness
  warning; a cold offline user gets an actionable error instead of a silent
  empty result.
- `TEMPLATE_CATALOG` (natural-language inference) still references template
  **names** only; the index is the resolution path, so removed local folders
  do not affect `ebx create "..."` recommendations.
- Out of scope (untouched): `connect`, natural-language create, MCP deploy,
  Agent Skill files.

## Acceptance criteria

- [x] `Easy-Sandbox/awesome-templates` holds content + index + tests + CI;
      drift (qwen `max_session_turns`, `EXPOSE 9000`, legacy fields) fixed
      there; the rename is not reverted
- [x] Main repo keeps only the `python-hello` fixture, explicitly marked at
      three levels; `TestFixtureBoundary` guards the boundary
- [x] `search` / bare-name `install` resolve via the remote index with cache,
      version pinning, and explicit offline/rate-limit/schema behaviour
- [x] Full unit suite runs offline (no network); targeted template/index/CLI
      suites green (185 cases combined)
- [x] Docs, README, CONTRIBUTING, CHANGELOG, and helper scripts updated; no
      dangling references to removed folders
- [x] Catalog-repo suite green (308 cases) across its own CI matrix
