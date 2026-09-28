# Decision: Single-repo single-distribution + [cli] extra (no split, no binary for now)

Status: implemented
Task: #95, #105

## Problem
The SDK and CLI live in the same repository, so the packaging structure must be
decided: (1) whether to split into separate distributions (SDK + a CLI
meta-package); (2) how to isolate the CLI dependencies; (3) whether to provide a
pre-built binary (shiv/pex/PyInstaller).

## Decision
Keep the **single-repo single-distribution + `[cli]` extra** structure.

### Naming scheme

1. **Distribution name (pip install X)**: `easy-sandbox`. `ebx` is already taken by
   a third party on PyPI (`evryoneowo`'s "secret manager", v1.1.0, MIT, first
   uploaded 2026-01-08) and is unavailable.
2. **Import name (import Y)**: `easy_sandbox`. The hyphen/underscore correspondence
   with the distribution name follows standard Python packaging convention.
3. **CLI command name**: `ebx`. `[project.scripts] ebx = "easy_sandbox.cli.main:cli"`.
   The CLI command name is independent of the distribution name and can be chosen freely.

### Installation modes

4. **SDK only**: `pip install easy-sandbox` — core dependencies httpx/websockets/pydantic/python-dotenv.
5. **SDK + CLI**: `pip install "easy-sandbox[cli]"` — additionally installs click/rich/pyyaml.
6. **`ebx` errors when click is missing after a bare install**: this is a known
   usability pitfall and must be documented up front.

### No library split

7. **Clean, one-way dependency**: CLI → SDK. The reverse is zero (a full Grep for
   `easy_sandbox.cli` / `from .cli` in the SDK layer = 0 matches). No circular dependency.
8. **A split is technically feasible but of limited benefit**:
   - The `ebx` distribution name is unavailable (a hard constraint), so a
     standalone CLI package could only be called `easy-sandbox-cli`, which weakens
     the original intent.
   - It would require version coordination (version pinning, duplicate CI,
     synchronized release cadence).
   - The current extra mechanism already satisfies the two needs "SDK only" and
     "SDK + CLI".

### No binary for now

9. **Freezing is not a structural fix; it is a distribution-UX option**. Current
   blockers:
   - `cli/main.py`'s `LazyGroup` uses `importlib.import_module` for dynamic
     imports (PyInstaller needs `--hidden-import`).
   - `@click.version_option(package_name="easy-sandbox")` relies on
     `importlib.metadata` (a frozen bundle usually has no `*.dist-info`).
   - `pydantic-core` (Rust), `orjson` (Rust), and `msgpack` (C) make the artifact
     platform-specific.

## API Design
```toml
# pyproject.toml (current)
[project]
name = "easy-sandbox"
# ...

[project.optional-dependencies]
cli = ["click>=8.0", "rich>=13.0", "pyyaml>=6.0"]

[project.scripts]
ebx = "easy_sandbox.cli.main:cli"

[tool.hatch.build.targets.wheel]
packages = ["src/easy_sandbox"]
```

```bash
# installation modes
pip install easy-sandbox            # SDK only
pip install "easy-sandbox[cli]"     # SDK + CLI
pip install "easy-sandbox[all]"     # all extras
```

## Alternatives considered
- **Split into two distributions (SDK + a CLI meta-package)** — technically
  feasible (one-way acyclic dependency), but the `ebx` distribution name is taken,
  version-coordination cost is high, and the benefit is limited. Rejected (not
  recommended for now).
- **Split into two repositories** — adds cross-repo collaboration/issue/CI
  complexity on top of the dual-distribution cost; not worth it at the current
  team size. Rejected.
- **Freeze into a single-file binary** — a pure UX plus, but requires solving
  LazyGroup dynamic imports, version_option metadata, and cross-platform builds of
  native extensions. Optional enhancement (not required).
- **Fold the CLI dependencies into the core dependencies** — a bare
  `pip install easy-sandbox` would then install click/rich/pyyaml, which is
  unnecessary bloat for SDK-only users. Rejected.

## Dependencies
- `pyproject.toml` (distribution configuration)
- `src/easy_sandbox/_version.py` (version source)
- `cli/main.py` (entry point + LazyGroup)

## Test Strategy
- After `pip install easy-sandbox`, `import easy_sandbox` succeeds and the `ebx`
  command raises a clear error due to missing click.
- After `pip install "easy-sandbox[cli]"`, `ebx --help` works normally.
- Grep for `easy_sandbox.cli` / `from .cli` under SDK layers such as
  `api/`/`models/`/`transport/`/`protocol/` = 0 matches (continuous verification of
  no circular dependency).

## Acceptance criteria
- A single distribution name `easy-sandbox`, a single import name `easy_sandbox`, and the CLI command `ebx`.
- The `[cli]` extra isolates the CLI dependencies; the SDK core has no click/rich/pyyaml.
- The SDK → CLI dependency direction is zero.

## Evidence
- `.agents/evidence/research/2026-09-04-pypi-publish-readiness.md` §3, §10
