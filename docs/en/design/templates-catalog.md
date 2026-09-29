# Templates Catalog Design

> The template catalog follows a **single source of truth (SSOT)** architecture:
> official & community template content, the machine-readable index
> (`awesome-templates.yaml`), releases and CI all converge on the dedicated
> repository [`Easy-Sandbox/awesome-templates`](https://github.com/Easy-Sandbox/awesome-templates).
> This repository **no longer maintains a publishable template collection** — it
> keeps only a minimal `python-hello` **offline fixture** under
> `examples/templates/`, explicitly marked as a fixture.
>
> Related documents: [Template System Design](./template-system.md) (template
> tiers and distribution), [CLI Design](./cli-design.md)
> (`ebx template search` / `install` / `deploy`).

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Easy-Sandbox/awesome-templates (single source of truth)        │
│  ├── awesome-templates.yaml   ← machine-readable index          │
│  │                              (data source for search/install)│
│  ├── README.md / CONTRIBUTING.md  ← human index + contribution  │
│  ├── <template>/              ← content (template.yaml +        │
│  │                               Dockerfile + README.md         │
│  │                               [+ commands.py])               │
│  ├── tests/                   ← offline folder/index checks     │
│  │                              (308 test cases)                │
│  └── .github/workflows/ci.yml ← Py3.10–3.13 matrix CI           │
└─────────────────────────────────────────────────────────────────┘
          ▲ raw.githubusercontent.com (CDN, no API rate limit)
          │ fetch_index(): cache in ~/.ebx/index/ + ETag revalidation
┌─────────┴───────────────────────────────────────────────────────┐
│  main repository easy-sandbox                                    │
│  ├── src/easy_sandbox/utils/template_index.py  ← index client    │
│  ├── src/easy_sandbox/cli/commands/template.py ← search/install  │
│  ├── examples/templates/python-hello/          ← minimal fixture │
│  └── tests/ (test_templates / test_utils / test_cli) ← offline   │
└─────────────────────────────────────────────────────────────────┘
```

**Ownership split**:

| Asset | Home | Notes |
|-------|------|-------|
| Official/community template content | Source-of-truth repo | Each folder: `template.yaml` + `Dockerfile` + `README.md` (plus `commands.py` when server-side commands are needed) |
| Machine-readable index | Source-of-truth repo root `awesome-templates.yaml` | The only data source for `search` / `install`; **no** file of that name exists in this repository |
| Releases & versions | Source-of-truth git tags/branches | The entry `ref` field pins a revision; no GitHub Release required |
| Directory consistency checks | Source-of-truth `tests/` + CI | Index ↔ folders ↔ README table reconciled field by field |
| Offline dev fixture | This repo's `examples/templates/python-hello/` | Used by offline unit/integration tests only; **never** add publishable templates here |
| Index client & degraded behaviour | This repo's `utils/template_index.py` | Caching, conditional requests, rate-limit/offline fallback |

### 1.1 Why not "a mirrored copy + periodic sync"

An earlier design kept a full template copy in the main repository and
published it via `git subtree push`. That design had two structural problems:

1. **Double writes always drift**: the Qwen parameter contract
   (`max_turns` → `max_session_turns`) once diverged between the two copies —
   a direct consequence of duplicated content.
2. **Users got a stale copy**: a template list baked into the CLI can only
   refresh with SDK releases, so community templates had to wait for a new
   version before they could be discovered.

After convergence: content has exactly one write path (PRs to the
source-of-truth repo), discovery has exactly one path (the remote index), and
SDK release cadence is fully decoupled from template evolution.

---

## 2. Machine-Readable Index (`awesome-templates.yaml`)

```yaml
schema_version: 1
templates:
  - name: node-web                       # required; unique; kebab-case
    description: "Node.js web service runtime"  # human-readable (search hit source)
    repo: https://github.com/Easy-Sandbox/awesome-templates  # required; github.com only
    path: node-web                       # in-repo subdir; omit if the whole repo is one template
    ref: v1.0.0                          # optional; pins a tag/branch/sha
    tags: [nodejs, web, express, api]    # searchable tags
    author: Easy-Sandbox
    capabilities: [shell, files, code, ports]
    status: official                     # official | community | experimental
```

Conventions:

- **`schema_version`**: index format version, currently `1`. Missing means 1
  (backward compatible); a version newer than the client supports fails
  **loudly** with an upgrade hint instead of being misinterpreted.
- **`repo`**: only `github.com` `owner/repo` slugs or full URLs are accepted
  (normalised at parse time).
- **`path` / `ref` combination**: entries compose into a Terraform-style
  `owner/repo//path@ref` reference (`TemplateIndexEntry.install_ref`) handed
  straight to `RegistryClient.resolve()`; with no `path` it degrades to
  `owner/repo`.
- **`name` uniqueness**: duplicate entries fail at parse time so results never
  depend on ordering.
- Contract enforcement lives in the source-of-truth `tests/test_index.py`:
  exactly one entry per folder, fields matching `template.yaml` item by item,
  and `install_ref` parseable by the registry client.

---

## 3. Remote Index Client Behaviour (`utils/template_index.py`)

### 3.1 Default location & overrides

| Item | Value |
|------|-------|
| Default index URL | `https://raw.githubusercontent.com/Easy-Sandbox/awesome-templates/main/awesome-templates.yaml` |
| Env override | `EBX_TEMPLATE_INDEX_URL` (HTTP(S) URL or local file path) |
| CLI override | `ebx template search/install --index-url <URL-or-path>` |
| Auth | `--token` > `GITHUB_TOKEN` > stored `github_token` (`ebx config set github_token`; private mirrors, higher rate limits) |

Choosing `raw.githubusercontent.com` over `api.github.com` is deliberate: raw
files are served by a CDN and are **not** subject to the 60 req/hour anonymous
API limit; local file paths make enterprise mirrors and fully offline
deployments first-class.

### 3.2 Caching & conditional requests

- Cache lives in `~/.ebx/index/` (kept separate from `~/.ebx/templates/` so it
  can never be mistaken for an installed template): the index body plus
  `awesome-templates.meta.json` (`source_url` / `etag` / `fetched_at`).
- TTL `INDEX_MAX_AGE_SECONDS = 3600`: a fresh cache **makes no network call**
  (the common `search`/`install` path costs zero network).
- Once expired, an `If-None-Match` conditional request is sent; `304` only
  refreshes the metadata timestamp and reuses the cached body.
- `--refresh` / `force=True` bypasses the cache.
- A corrupt (unparseable) cache is discarded and re-fetched — garbage is never
  fed into the degraded path.

### 3.3 Degraded-mode matrix (explicit and predictable)

| Scenario | With cache | Without cache |
|----------|------------|---------------|
| Network unreachable (DNS/timeout/refused) | Stale cache + `stale=True` + warning ("using cached index") | `NetworkError` suggesting network / `GITHUB_TOKEN` / `--index-url` checks |
| GitHub rate limit (403 with `X-RateLimit-Remaining: 0`, or 429) | Same as above + warning pointing at `GITHUB_TOKEN` / `ebx config set github_token` | `GitHubRateLimitError` (E5000) with the verified fine-grained PAT URL, `ebx config set github_token` / `GITHUB_TOKEN` remediation, the `--token` leak warning, and a mirror hint; an interactive terminal is also offered a masked one-shot setup + exactly one retry |
| `404` | Falls into the generic network-error path | `NetworkError` suggesting verifying the index URL (`--index-url`) |
| Server errors (5xx) | Stale cache + warning | `NetworkError` |
| Other non-2xx | Stale cache + warning | `NetworkError` reporting the concrete status |
| `schema_version` too new | No degradation | `TemplateParseError` with `pip install -U easy-sandbox` |
| Missing `templates` list / invalid YAML | No degradation | `TemplateParseError` (includes the source URL) |

Degradation is surfaced uniformly through `TemplateIndex.stale` + `notice`: the
CLI prints the warning before the results and keeps exit code 0 — a stale index
is still usable, just visibly stale.

---

## 4. CLI Behaviour (`ebx template search` / `install`)

### 4.1 `ebx template search <query>`

- Queries the remote index; substring match across `name` / `description` /
  `tags` / `author`; `--tag` / `--status` exact filters; `--refresh` forces a
  re-fetch; `-j` emits JSON.
- Prints a table (Name / Description / Tags / Status) plus the install hint
  `Install one with: ebx template install <name> (index: <source_url>)`.
- On degradation the `notice` warning is printed before the results.

### 4.2 Bare-name resolution order for `ebx template install <name>`

```
<name> is a local path?       → use it directly (no network, no index)
<name> is a builtin?          → BUILTIN_TEMPLATES = {base, code-interpreter-v1}
                                (platform images, no fetch, no index call)
<name> looks like owner/repo[//path][@ref]? → straight to RegistryClient (no index)
otherwise (bare name)         → query the remote index:
                                hit  → install_ref (possibly ref-pinned) → normal install
                                miss and cache is not stale → one forced refresh,
                                  giving freshly published templates a chance
                                still a miss → TemplateNotFoundError with a
                                  suggestion to run 'ebx template search' or
                                  install directly from owner/repo//subdir
```

On an index hit the CLI prints
`Resolved '<name>' via the template index: <owner>/<repo>//<path>[@ref]`, so the
eventual source and version are auditable.

### 4.3 Version pinning & per-ref cache layout

A pinned `ref` (declared by the entry or passed explicitly with `@ref`) ends up
in the cache path `~/.ebx/templates/<owner>/<repo>/<ref|default>/<path>`, so
different refs never bleed into each other. Entries without a `ref` follow the
source-of-truth default branch — "track latest" and "pin a version" are both
explicit choices.

---

## 5. Main-Repository Fixture Contract (`examples/templates/`)

`examples/templates/` is a **test-asset directory**, not a template catalog:

- Only `python-hello` may exist (`EXPECTED_FIXTURE_TEMPLATES`); any additional
  folder fails
  `tests/test_templates/test_template_catalog.py::TestFixtureBoundary` immediately.
- Three explicit markers prevent it from being mistaken for a publishable
  template:
  1. directory-level `README.md` stating "this directory is NOT the publishing
     source" + a link to the source of truth + the remote install commands;
  2. a `FIXTURE` banner comment at the top of `python-hello/template.yaml`;
  3. a fixture notice block in `python-hello/README.md`.
- The fixture itself must still pass every template contract (real loader
  parse, valid capabilities, Dockerfile `FROM`, custom_commands
  placeholder↔args bidirectional coverage) — it is the executable sample of the
  template specification.
- `python-hello` is also referenced by integration tests and golden files (CLI
  help, workflow E2E), so it is **never deleted or renamed**.

---

## 6. Test Strategy (offline-first)

### 6.1 Main repository (fully offline, no network)

| Suite | Coverage |
|-------|----------|
| `tests/test_utils/test_template_index.py` | Index parsing/validation, `install_ref` construction, cache lifecycle (fresh short-circuit / force / 304), degraded matrix (offline / rate limit / 404 / 5xx / corrupt cache), token and env overrides |
| `tests/test_cli/test_template_index_commands.py` | `search` output/filters/JSON/degraded notice/option passthrough; `install` bare-name index resolution, `@ref` pinning, builtin names never touching the index, friendly not-found with forced refresh |
| `tests/test_templates/test_template_catalog.py` | Fixture boundary (uniqueness/markers/README contract) + fixture YAML/Dockerfile/custom_commands contracts |
| `tests/test_templates/test_local_install.py` | The real CLI install pipeline (local tarball stubs, `socket` tripwire guaranteeing zero egress) |

Network interception is done exclusively via `pytest-httpx` (`httpx_mock`) or
`fetch_index` stubs; the full unit suite runs in network-less environments
(CI sandboxes, enterprise intranets).

### 6.2 Source-of-truth repository (self-testing, evolves with content)

`tests/test_catalog.py` (32 cases) + `tests/test_index.py` (11 cases) +
`tests/test_commands_e2e.py` (10 cases): directory contracts, index
reconciliation, README table compared field by field, and the qwen-code
`max_session_turns` contract guard. CI runs on a Python 3.10–3.13 matrix
against `requirements-dev.txt` (`easy-sandbox[cli]` git main + pytest + pyyaml).

> Division of labour: **content correctness** belongs to the source-of-truth
> repo (a template change must update the index and README table in the same
> PR); **client behaviour** belongs to this repository (caching, degradation,
> resolution order). Neither side depends on the other's repository layout —
> they couple only through the public contract of the index file format.

---

## 7. Publishing & Contribution Flow

1. **Contribute**: open a PR against the source-of-truth repo
   (`CONTRIBUTING.md` defines the template anatomy, capability-group rules and
   local dev workflow). The PR must update `awesome-templates.yaml` and the
   README table in lock-step; the offline CI must be green.
2. **Release**: merging to `main` is the release (the index updates atomically
   with the content); tag `v1.0.0` for stable references, which users pin via
   `@v1.0.0`. **No GitHub Release needed** — `RegistryClient` resolves
   tags/branches/shas through the tarball API.
3. **Consume**: users discover via `ebx template search` and install with
   `ebx template install <name>`; a freshly published template is found
   immediately thanks to the single forced refresh on a cache miss, no TTL wait.
4. **Rollback**: point the entry `ref` at a known-good version; to pull a
   template urgently, remove its entry (invisible to new users; installed
   caches are unaffected).

---

## 8. Non-Goals (explicit boundaries)

| Not doing | Why |
|-----------|-----|
| Mirroring template content back into this repository | Double writes are the root problem this design eliminates |
| Keeping a copy of `awesome-templates.yaml` here | The index's single source of truth is the catalog repo; this repo only ships the client |
| Requiring an SDK release for a template update | The index mechanism already decouples the two release cadences |
| Hitting GitHub for real in unit tests | Offline-first is a hard constraint; networked checks are integration/manual |
| Automatic cross-repo sync (subtree/submodule/cron) | The catalog repo is the single entry point — no sync action, hence no sync drift |
| An Agent executing `git push` | Publishing is a human decision point |
| Deleting/renaming the `python-hello` fixture | Integration tests and golden files reference it by path; deletion breaks them |
| Reverting the `max_session_turns` contract | The parameter name established by task 181 is guarded by tests on both sides (catalog `test_commands_e2e.py`) |
