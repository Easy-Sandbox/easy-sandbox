# Templates Catalog Design

> `examples/templates/` is the **official template collection** for Easy Sandbox, deliberately designed
> as a minimal form of "one README + a bunch of template folders" so that the entire collection can be
> extracted **as-is** into a standalone repository `awesome-easy-sandbox-templates`. This document
> defines the directory's structural contract, publishing workflow, linking between the main repository
> and the standalone repository, and offline validation methods that work in both contexts.
>
> Related documents: [Template System Design](./template-system.md) (template tiers and distribution mechanism),
> [CLI Design](./cli-design.md) (`ebx install` / `ebx run` / `ebx exec`),
> [Capability Model](./template-system.md#关键设计要点) (capabilities gating, see the capability model entry under "Key Design Points"; authoritative definition in ADR `2026-09-03-capability-model.md`).

---

## 1. Why "README + Folders"

There are two approaches for the template collection's indexing scheme:

| Approach | Form | Problem |
|----------|------|---------|
| Structured manifest | `registry.json` / `index.json` / multi-layer manifest | Manifest and template files require **dual maintenance**, inevitably drifting; paths must be rewritten when extracting to a standalone repo; contributors must first learn the manifest format |
| **Minimal directory** (this approach) | `README.md` + one folder per template | The index is **for humans**, consistency is ensured by tests rather than manual synchronization |

Reasons for choosing the minimal form:

1. **Template folders are self-describing**. `template.yaml` is the single source of truth,
   `Dockerfile` is an independently buildable equivalent artifact, `README.md` is the human documentation.
   Any additional index file is a projection of these three, and projections risk distortion.
2. **Extraction to a standalone repo is zero-cost**. `git filter-repo` or simply `cp -r` works,
   with no path references to rewrite — because **no file references absolute locations**.
3. **Lowest contribution barrier**. Adding a new template = copy a folder, modify three files, add a row to the overview table.
4. **Consistency can be machine-enforced**. See [§5 Offline Validation](#5-offline-validation-running-the-same-checks-in-a-standalone-repo).

### 1.1 Directory Contract

```
examples/templates/                 ← Becomes standalone repo root when extracted
├── README.md                       ← Sole index (template overview table + install/usage/contribution guide + schema)
├── browser-automation/
│   ├── template.yaml       ← Required: authoritative definition
│   ├── Dockerfile                  ← Required: build artifact equivalent to YAML
│   └── README.md                   ← Required: template documentation
├── claude-code/
├── codex/
├── deepseek-harness/
├── hermes-agent/
├── node-web/
├── openclaw/
├── python-hello/
├── qoder/
└── qwen-code/
```

Hard constraints:

- **Folder name == `template.yaml`'s `name` == default `alias` after installation**.
  All three must be consistent; otherwise `api/capability.py::resolve_capabilities()` cannot
  look up the template by name in `~/.ebx/templates/`, and capabilities will silently fall back to
  `DEFAULT_CAPABILITIES` (only logging a warning, not raising an error) — the hardest class of bugs to diagnose.
- Naming in kebab-case: no spaces, no underscores, no uppercase.
- All three required files must be present and non-empty.
- The index table lives in `README.md`; **no additional json/yaml manifest files are introduced**.

### 1.2 Index Table Fields

The "Template Overview" table in `README.md` has 7 columns, all sourced from YAML:

| Column | Data Source |
|--------|-------------|
| Template | Folder name (links to `./<name>/`) |
| Description | `description` |
| Keywords | `tags` (order-sensitive) |
| Base Image | `base` |
| Resources | `resources.cpu` / `resources.memory` / `ports` |
| Capabilities | `capabilities` (order-sensitive; `*` annotation see below) |
| Custom Commands | `custom_commands` keys + their respective `args`, formatted as `` `run(task*)` ``, `*` = `required: true` |

"Order-sensitive" is deliberate: tests perform **list equality** rather than set equality,
so the table truly reflects the declaration order in YAML rather than masking differences with sorting.

---

## 2. Publishing Workflow (Definition of Done)

The template collection's publishing is a **four-stage pipeline**; any stage not passing means it's not done:

```
①  Offline validation + local install E2E all green
        │   python -m pytest tests/test_templates/ -q
        ▼
②  User pushes to GitHub (push git tag / branch, no Release needed)
        │   (manual step, Agent does not execute git push)
        ▼
③  Real ebx install <owner>/<repo>//<template> --registry-type github end-to-end passes
        │   (real network, real GitHub API, real ~/.ebx/templates cache)
        ▼
④  Done
```

### 2.1 Stage ①: Local Install Test (Agent's Hard Gate)

`tests/test_templates/test_local_install.py` drives the real CLI via `CliRunner`:

```bash
python -m pytest tests/test_templates/ -q
```

It exercises the **real code path**: `RegistryClient.resolve()` → `RegistryClient.fetch()` →
`load_template_from_yaml()` → `SandboxTemplate.to_dockerfile()` → construct
`POST /templates` request body. Only two boundaries are stubbed:

| Stubbed Boundary | Reason |
|------------------|--------|
| `transport.config.load_config` / `transport.auth.create_auth_provider` / `transport.http.HttpClient` | Requires real backend and credentials |
| `httpx.AsyncClient.get` | Requires real network (GitHub tarball bytes) |

Note that `_download_and_extract()` is **not** stubbed — tarball top-level directory stripping and `//subdir`
subdirectory extraction, plus path traversal protection, are all executed for real using an in-memory
GitHub-style .tar.gz replica built by `build_repo_tarball()`. Thus the entire chain "ref resolution → download → extract
→ cache → load → generate Dockerfile → submit build" goes through real code except for the HTTP bytes themselves.

The entire module also installs a `socket.getaddrinfo` / `socket.create_connection` tripwire
(autouse fixture); any unexpected DNS resolution causes tests to fail immediately — "fully offline" is an **executable**
commitment, not just a comment.

> The tripwire deliberately does **not** patch `socket.socket`: asyncio's self-pipe (`socketpair()`)
> depends on it, and patching it would crash `asyncio.run()` inside `run_sync()`.
> `getaddrinfo` and `create_connection` are the choke points for all outbound HTTP.

### 2.2 Stage ②: Manual Push (tag / branch is sufficient)

Executed by the user; Agent does not touch it:

```bash
# Standalone repo form
git remote add templates git@github.com:<owner>/awesome-easy-sandbox-templates.git
git subtree push --prefix=examples/templates templates main
git tag v1.0.0 && git push origin v1.0.0     # Push a git tag
```

**No GitHub Release needed**: `RegistryClient` uses the GitHub tarball API
(`/repos/{owner}/{repo}/tarball[/{ref}]`) to fetch by tag/branch/sha; GitHub
automatically resolves ref to tag/branch/sha. Without `@ref`, it fetches the default branch. Whether
using only the default branch, just pushing git tags, or even using bare commit SHAs — all work with `ebx install`.

### 2.3 Stage ③: Real GitHub End-to-End

After publishing, a **real network** verification must be performed to cover what Stage ① cannot
(real API response structure, real tarball top-level prefix, real authentication, real cache directory):

```bash
# Clear cache to ensure we're not hitting leftovers from Stage ①
ebx template cache --clear

# Single template (standard usage for this collection)
ebx install <owner>/awesome-easy-sandbox-templates//node-web \
  --registry-type github --registry-url https://github.com

# Pin version
ebx install <owner>/awesome-easy-sandbox-templates//node-web@v1.0.0 \
  --registry-type github

# Verify cache landed
ebx template cache
ls ~/.ebx/templates/<owner>/awesome-easy-sandbox-templates/v1.0.0/node-web

# Verify capabilities / custom_commands are actually parsed (not falling back to defaults)
ebx create --template node-web
ebx run <sandbox_id> start
ebx exec <sandbox_id> "node -v"
ebx kill <sandbox_id> -y
```

`ebx run <sandbox_id> start` succeeding proves that `custom_commands` were correctly parsed from the
cached YAML — the most informative single assertion across the entire chain.

### 2.4 Why Whole-Repo Ref (Without `//`) Does Not Work

```bash
ebx install <owner>/awesome-easy-sandbox-templates --registry-type github
```

This resolves the **repository root** to the cache directory, but the root only contains `README.md` and
template folders without its own `template.yaml`, causing install to fail with
`No template.yaml found in ...`.

This is **by design**, not a defect: this collection is a multi-template repository, and `//<template>` is the correct usage.
`test_github_install_whole_repo_without_subdir_fails` pins this behavior,
and the installation section in `README.md` explicitly documents the subdirectory syntax. Whole-repo ref is only valid when
"one repository = one template."

---

## 3. Linking Between Main Repo and Standalone Repo

Both forms coexist, distinguished by **reference format** rather than file content:

### 3.1 Staying in the Main Repository (Current State)

```bash
ebx install ./examples/templates/node-web --registry-type local
```

Main repository association points:

| Location | Association Method | Breaks on Extraction? |
|----------|-------------------|----------------------|
| `README.md` (root) → `examples/templates/` | Relative link | Must change to point to standalone repo URL |
| `examples/README.md` directory tree | Relative path description | Must remove that section |
| `src/easy_sandbox/agent/infer.py::TEMPLATE_CATALOG` | References **by template name**, no paths | ❌ Does not break |
| `examples/templates/README.md` schema links | `../../src/...` relative links | Must change to main repo blob URL |
| `tests/test_templates/` | `parents[2] / "examples" / "templates"` | Adjust per §5.3 |

Key design: **`TEMPLATE_CATALOG` references templates by name only, not by path**.
So after the template directory is extracted, natural language inference (`ebx create "…"`) still works —
it recommends a template name, and users then `ebx install <owner>/<repo>//<name>` themselves.

### 3.2 After Extraction to Standalone Repo

The main repository retains only a **pointer**, no longer holding content:

````markdown
<!-- Main repo README.md -->
## Templates

Ready-to-use sandbox templates are in the standalone repository
[awesome-easy-sandbox-templates](https://github.com/<owner>/awesome-easy-sandbox-templates):

```bash
ebx install <owner>/awesome-easy-sandbox-templates//node-web --registry-type github
```
````

Synchronization strategy (choose one):

| Method | Description | Best For |
|--------|-------------|----------|
| `git subtree push --prefix=examples/templates` | Main repo remains the sole editing entry point; standalone repo is a published artifact | Frequent template changes, maintained by core team |
| `git submodule` / delete main repo copy entirely | Standalone repo is the sole entry point; main repo only keeps links | Accepting community PRs, template ecosystem expanding |

**Current recommendation: subtree push**: `tests/test_templates/` depends on the main repo's
`easy_sandbox` package (real loader, real CLI); submodule-izing would split offline validation into two separate suites.

### 3.3 Version Alignment

The standalone repo's git tag/ref and each template's `template.yaml` `version` field
are **two independent dimensions**:

- git tag/ref (`v1.0.0`) = snapshot version of the entire collection, used for `@ref` pinning and cache subdirectories.
- Template `version` = semantic version of an individual template, used for display and compatibility decisions.

The cache path is organized by ref (`~/.ebx/templates/<owner>/<repo>/<ref|default>/`),
so inconsistencies across these two dimensions do not cause cache cross-contamination.

---

## 4. Boundary Between `ebx run` and `ebx exec`

The existence of the template collection makes this boundary meaningful, which is why it's documented in the design doc rather than just the README:

| | `ebx run <id> <command_name>` | `ebx exec <id> "<shell>"` |
|---|---|---|
| Command source | Declared in template `custom_commands` | Ad-hoc by the caller |
| Parameter model | `--arg k=v` fills `{placeholder}`, auto-escaped via `shlex.quote` | None, entirely manual |
| `cwd` / `env` / `timeout` | Declared in template; caller doesn't repeat | `--cwd` / `--timeout` explicitly passed; `env` cannot be passed |
| Discoverability | `sandbox.list_commands()` can enumerate | Not enumerable |
| Failure modes | Command name not found / required arg missing / placeholder unfilled → explicit `ValueError` | Shell syntax errors, non-zero exit codes |
| Dependencies | Requires successful capabilities resolution (see §1.1 naming constraints) | Only needs `shell` capability |

Design intent: `custom_commands` is the template author's **declarative encapsulation** of "how this environment should be used,"
consolidating error-prone details like `cwd`/`env`/`timeout`/escaping from every call site into a single template declaration.
`ebx exec` is reserved for one-off exploration and debugging. The two are not substitutes for each other.

---

## 5. Offline Validation: Running the Same Checks in a Standalone Repo

### 5.1 Validation Checklist

`tests/test_templates/test_template_catalog.py` performs parameterized assertions per template:

| # | Contract | Description |
|---|----------|-------------|
| a | YAML can be parsed by the **real loader** | `utils.registry.load_template_from_yaml()` → `SandboxTemplate`, not re-implementing parsing logic |
| b1 | Required fields are complete | `name` / `version` / `description` / `base` / `author` / `tags` explicitly declared (the model has defaults, but published templates must state them) |
| b2 | Capabilities are valid | All fall within `STANDARD_CAPABILITIES`; explicitly declared; no duplicates; `ports` capability and top-level `ports:` list are mutually sufficient and necessary |
| b3 | custom_commands structure is valid | Command name in kebab/identifier format; `cmd` non-empty; `timeout > 0`; `cwd` absolute path; `env` is `str→str`; `{placeholder}` and `args` have **bidirectional** coverage; `required: true` must not have `default`, non-required **must** have `default` |
| c | Three required files exist and are non-empty | `template.yaml` / `Dockerfile` / `README.md`; also catches spelling variants like `sandbox_template.yaml`, `dockerfile` |
| d | Reconciliation with `TEMPLATE_CATALOG` | No orphans, no missing (see §5.2) |
| e | `README.md` index table matches YAML field by field | description/keywords/base/cpu/memory/ports/capabilities/custom commands; plus capabilities distribution matrix; plus install and schema sections existence |
| f | `Dockerfile`'s `FROM` == YAML `base` | Prevents handwritten Dockerfile and YAML telling different stories |

### 5.2 Reconciliation Rules (Contract d)

`TEMPLATE_CATALOG` (`src/easy_sandbox/agent/infer.py`) and disk folders
are not 1:1, so two explicit whitelists pin "intentional asymmetries,"
leaving any remaining discrepancy as a bug:

```python
# Provided by platform built-in images / online catalog; this collection intentionally has no folder
PLATFORM_ONLY_TEMPLATES = {"base", "code-interpreter", "python-data-science", "full-stack"}

# Example/test fixtures only, not participating in natural language inference
EXAMPLE_ONLY_TEMPLATES = {"python-hello"}
```

Four assertions:

1. Every entry in `TEMPLATE_CATALOG` must either have a corresponding folder or be in `PLATFORM_ONLY_TEMPLATES` (**no missing**).
2. Every folder must either be in `TEMPLATE_CATALOG` or in `EXAMPLE_ONLY_TEMPLATES` (**no orphans**).
3. Names in `PLATFORM_ONLY_TEMPLATES` **must not** appear as folders (to avoid shadowing platform built-in templates;
   `utils.registry.BUILTIN_TEMPLATES` treats bare name `base` as built-in and skips fetching).
4. Entries with corresponding folders must have `cpu` / `memory` / `ports` consistent with the YAML's
   `resources` / `ports` (the inference engine's resource defaults must not conflict with the template's actual declarations).

> Deliberately **not** asserting "catalog keywords must contain YAML tags."
> Keywords are **human phrasing** for natural language matching (`node.js`, `web service`, `build websites`),
> while tags are **canonical identifiers** for retrieval (`nodejs`, `web`, `api`); the two are inherently different.
> Forcing alignment would push `infer.py` to include keywords nobody would ever say, degrading inference quality.

### 5.3 Running the Same Checks in a Standalone Repo

`tests/test_templates/` only depends on `pydantic` + `pyyaml` + `click` + `pytest` +
`easy_sandbox` package itself, with no dependency on any other main repo assets. When extracting:

**Step 1 — Copy Tests**

```bash
mkdir -p tests/test_templates
cp <main-repo>/tests/__init__.py tests/__init__.py
cp <main-repo>/tests/test_templates/*.py tests/test_templates/
```

(`tests/__init__.py` and `tests/test_templates/__init__.py` must both exist;
the test modules use package-relative imports `from .conftest import ...`.)

**Step 2 — Change Path Constant**

Only one location in `tests/test_templates/conftest.py` needs modification:

```python
# Main repo: tests/test_templates/conftest.py → parents[2] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "examples" / "templates"

# Standalone repo: template folders are at the repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT                      # ← Only change this line
```

**Step 3 — Install SDK**

Standalone repo CI needs `easy-sandbox[cli]` (tests use the real loader and real CLI):

```yaml
# .github/workflows/validate.yml
name: validate-templates
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install "easy-sandbox[cli]>=0.1" pytest
      - run: python -m pytest tests/test_templates/ -q
```

**Step 4 — Disable Two Assertions Requiring Main Repo Context**

Contract d (`TEMPLATE_CATALOG` reconciliation) depends on `easy_sandbox.agent.infer`;
with the SDK installed, it runs without modification.
Contract e's references to `../../src/...` relative links only appear in README text;
tests do not validate link reachability, so no modification is needed either.

> Conclusion: **The standalone repo runs the same test files, changing only the `TEMPLATES_DIR` line.**

### 5.4 Quick Local Validation

```bash
# Full suite (~400 parameterized cases, 2-3 seconds)
python -m pytest tests/test_templates/ -q

# Directory contract only
python -m pytest tests/test_templates/test_template_catalog.py -q

# Install end-to-end only
python -m pytest tests/test_templates/test_local_install.py -q

# Validate a specific template only
python -m pytest tests/test_templates/ -q -k node-web

# Manual offline load (bypassing CLI)
python -c "
from pathlib import Path
from easy_sandbox.utils.registry import load_template_from_yaml
t = load_template_from_yaml(Path('examples/templates/node-web/template.yaml'))
print(t.name, t.base, t.capabilities, list(t.custom_commands))
print(t.to_dockerfile())
"
```

---

## 6. What We Don't Do (Explicit Boundaries)

| Not Doing | Reason |
|-----------|--------|
| No `registry.json` / `index.json` / multi-layer manifest | Dual maintenance inevitably drifts; indexing is ensured by README + tests |
| No real docker image builds in tests | Requires docker daemon, breaks offline and CI reproducibility; `Dockerfile` only checks `FROM` matches YAML |
| No real platform `POST /templates` calls in tests | Requires credentials and quotas; build boundaries are all stubbed |
| Agent does not execute `git push` / create Releases | Publishing is a human decision point, see §2.2 |
| No renaming / moving existing template folders | `TEMPLATE_CATALOG` and multiple documents reference by name; renaming is a breaking change |
| No forcing `TEMPLATE_CATALOG` keywords to align with YAML tags | See the explanation at the end of §5.2 |
