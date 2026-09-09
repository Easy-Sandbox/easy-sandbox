# Full Suite Verification — 2026-09-04

## Environment
- Python: 3.9 (system, /Library/Developer/CommandLineTools)
- OS: macOS darwin 15.7.7
- Command: `python3 -m pytest tests/ -v --tb=short`

---

## 1. pytest — Full Suite

```
================= 1452 passed, 6 skipped, 56 warnings in 6.83s =================
```

| Metric   | Value |
|----------|-------|
| Passed   | 1452  |
| Skipped  | 6     |
| Failed   | 0     |
| Errors   | 0     |
| Warnings | 56    |
| Duration | 6.83s |

**Baseline comparison**: 1452 passed, 6 skipped — **EXACT MATCH** ✅

### Golden CLI Evidence Subset
```
======================= 77 passed, 15 warnings in 0.37s ========================
```
All 77 golden snapshots pass — **no drift** ✅

---

## 2. ruff check src/ tests/

```
Found 360 errors.
[*] 198 fixable with the `--fix` option (82 hidden fixes can be enabled with the `--unsafe-fixes` option).
```

**Status: FAIL** ❌

### Error breakdown by rule (top 15):

| Rule  | Count | Description |
|-------|-------|-------------|
| F401  | 103   | Unused imports |
| I001  | 71    | Import block un-sorted/un-formatted |
| E501  | 40    | Line too long |
| TC001 | 36    | Move application import into type-checking block |
| F841  | 18    | Local variable assigned but never used |
| TC003 | 13    | Move stdlib import into type-checking block |
| N806  | 10    | Variable in function should be lowercase |
| UP045 | 5     | Use `X | None` instead of `Optional[X]` |
| TC002 | 5     | Move third-party import into type-checking block |
| SIM105| 6     | Use `contextlib.suppress(...)` |
| B007  | 3     | Loop control variable not used |
| UP012 | 2     | Unnecessary `str()` call |
| UP035 | ~8    | Import from `collections.abc` instead |

### Key affected files (sample):
- `src/serverless_sandbox/agent/__init__.py` — I001
- `src/serverless_sandbox/agent/builtin.py` — I001, F401
- `src/serverless_sandbox/agent/infer.py` — F401
- `src/serverless_sandbox/api/capability.py` — F401, TC001
- `src/serverless_sandbox/cli/commands/sandbox.py` — E501, F841
- `tests/test_utils/test_async_bridge.py` — I001, F401
- `tests/test_utils/test_registry.py` — I001, TC003, F401
- `tests/test_utils/test_retry.py` — F401, F841
- `tests/test_utils/test_logging.py` — F841

**NOTE**: These are pre-existing lint violations, NOT introduced by #85/#86/#87 (which did not land).

---

## 3. mypy src/serverless_sandbox/

```
Found 159 errors in 38 files (checked 81 source files)
```

**Status: FAIL** ❌

### Error categories:
| Category | Count (approx) |
|----------|----------------|
| untyped-decorator | ~35 |
| no-any-return | ~15 |
| import-not-found (cloudpickle, msgpack, tomllib, aiosqlite) | ~8 |
| import-untyped (yaml) | ~3 |
| unused-ignore | ~12 |
| attr-defined (StreamReader union) | ~15 |
| no-untyped-def | ~12 |
| call-arg (wrong kwarg names) | ~8 |
| type-arg (missing generic params) | ~10 |
| valid-type (function used as type) | 3 |
| arg-type | ~4 |
| union-attr | ~10 |
| return-value | 1 |
| no-untyped-call | 2 |

### Key affected files:
- `src/serverless_sandbox/session/oss.py` — attr-defined, unused-ignore (5 errors)
- `src/serverless_sandbox/session/database.py` — no-untyped-def, import-not-found
- `src/serverless_sandbox/cli/commands/sandbox.py` — untyped-decorator, union-attr
- `src/serverless_sandbox/cli/commands/deploy.py` — untyped-decorator, union-attr
- `src/serverless_sandbox/api/sandbox.py` — call-arg, valid-type
- `src/serverless_sandbox/api/session_manager.py` — call-arg (5 errors)
- `src/serverless_sandbox/integrations/*.py` — type-arg, arg-type
- `src/serverless_sandbox/transport/config.py` — import-not-found, no-any-return
- `src/serverless_sandbox/agent/builtin.py` — union-attr, return-value

**NOTE**: These are pre-existing type errors, NOT introduced by #85/#86/#87 (which did not land).

---

## 4. Tree Coherence — Agent Deliverables

### #85 (James): Rename template.yaml → template.yaml

**VERDICT: ❌ NOT LANDED**

Evidence:
- `examples/templates/*/template.yaml` — **10 files still exist** (old name)
- `examples/templates/*/template.yaml` — **0 files exist** (new name)
- Grep `template.yaml` across tree: **105 occurrences in 26 files**
- Affected areas:
  - `src/` — 14 hits (6 files: capability.py, sandbox.py, errors.py, template.py, registry.py, template.py CLI)
  - `tests/` — 25+ hits (6 files)
  - `docs/design/` — 23 hits (5 files)
  - `.agents/notes/` — 13 hits (4 files)
  - `docs/evidence/research/` — 3 hits (2 files)
  - `examples/` — 2+ hits (2 README files)
  - `docs/DESIGN.md` — hits present

Q2 project-level command declaration: **NOT IMPLEMENTED** (no `template.yaml` convention in project root, no resolution priority code changes detected).

### #86 (Kevin): Examples reorganization

**VERDICT: ❌ NOT LANDED**

Evidence:
- `examples/quickstart/` — **DOES NOT EXIST**
- `examples/agents/` — **DOES NOT EXIST**
- `examples/compat-demos/` — **DOES NOT EXIST**
- All example files remain flat in `examples/`:
  - `01_basic_sandbox.py` … `07_browser_automation.py` (flat)
  - `demo_e2b_*.py`, `demo_modal_*.py`, `demo_comparison.py` (flat)
- `examples/templates/` — still in place (correct)
- README path references — NOT updated (no quickstart/agents/compat-demos paths)

### #87 (Aaron): docs/design/ + .agents/notes/ sync

**VERDICT: ❌ NOT LANDED**

Evidence:
- `docs/design/template-system.md` — 12 hits for `template.yaml`
- `docs/design/templates-catalog.md` — 9 hits
- `docs/design/sdk-api-design.md` — 2 hits
- `docs/design/built-in-agents.md` — 1 hit
- `docs/design/cli-design.md` — 1 hit
- `.agents/notes/implemented/` — 13 hits across 4 files
- No resolution-priority documentation updates detected

---

## 5. Golden Snapshot Drift

**Status: NO DRIFT** ✅

All 77 golden snapshots in `tests/test_cli_evidence/golden/` pass against current CLI output.
`docs/evidence/cli/` files are consistent (not invalidated since no rename landed).

---

## Summary

| Check | Status | Details |
|-------|--------|---------|
| pytest | ✅ PASS | 1452 passed, 6 skipped, 0 failed |
| Golden evidence | ✅ PASS | 77/77 snapshots match |
| ruff | ❌ FAIL | 360 errors (pre-existing) |
| mypy | ❌ FAIL | 159 errors in 38 files (pre-existing) |
| #85 rename | ❌ NOT LANDED | 105 residual refs, 0 template.yaml files |
| #86 reorg | ❌ NOT LANDED | No subdirectories created |
| #87 docs sync | ❌ NOT LANDED | 38+ residual refs in docs |
