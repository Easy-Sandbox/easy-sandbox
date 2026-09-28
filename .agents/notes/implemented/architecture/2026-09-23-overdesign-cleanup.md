# Decision: P0+P1 Overdesign Cleanup

Status: implemented

## Problem

The codebase contained several over-engineered abstractions and unused features
that added complexity without serving the current use case (project not yet live,
no external consumers):

1. **integrations/** — Empty plugin system with only an abstract base class
2. **session/base.py** — Abstract `SessionStore` base class with only one concrete
   implementation (`LocalSessionStore`)
3. **TEMPLATE_CATALOG phantom entries** — Three templates (code-interpreter,
   python-data-science, full-stack) referenced in inference but never backed by
   real template YAML/Dockerfile
4. **check_capability runtime gating** — 14 call-sites checking capabilities at
   runtime that added overhead without protecting against real misconfiguration
5. **Multi-format serializer** — PICKLE and MSGPACK serialization modes in
   `@sandbox` decorator that were never exercised in practice
6. **macOS Keychain integration** — Platform-specific keychain via `subprocess`
   calls in `SecretStore`, adding `platform`/`subprocess` imports for a feature
   not validated on CI
7. **qwen-cli / qwen-browser documentation** — Docs referenced non-existent
   CLI tools and browser agents

## Decision

Delete all P0+P1 overdesign items in a single coordinated cleanup. The project
has no live consumers, so no backward-compatibility shims are needed.

### What was deleted

| Item | Files removed | Files modified |
|------|--------------|----------------|
| integrations/ | `src/easy_sandbox/integrations/` (2 files), `tests/test_integrations/` | 4 docs files |
| SessionStore ABC | `src/easy_sandbox/session/base.py` | `session/local.py`, `session/__init__.py`, `api/session_manager.py`, 4 docs |
| TEMPLATE_CATALOG phantoms | — | `agent/infer.py`, 3 test files, 4 docs |
| check_capability gating | — | `api/capability.py`, `api/commands.py`, `api/files.py`, `api/code.py`, `api/network.py`, `api/sandbox.py`, 3 test files |
| PICKLE/MSGPACK serializer | — | `declarative/serializer.py`, `declarative/decorator.py`, 2 test files |
| macOS Keychain | — | `utils/keychain.py`, 1 test file |
| qwen-cli docs | — | 4 docs files |

### What was preserved

- `ResolvedCapabilities` class and `resolve_capabilities()` function (used by Sandbox.create/connect)
- `CapabilityNotSupportedError` class and E3004 error code in `models/errors.py`
- `base` entry in TEMPLATE_CATALOG (fallback for `infer_template`)
- All `_capabilities` fields on modules (still used for resolve_capabilities data flow)
- File-based storage in `SecretStore` (the only storage path now)

## API Design
```python
# Public-surface changes from the cleanup:
# Removed:   integrations plugin base, SessionStore ABC (session/base.py),
#            runtime check_capability() gating call-sites, PICKLE/MSGPACK serializer modes,
#            macOS Keychain path in SecretStore
# Preserved: ResolvedCapabilities, resolve_capabilities(), CapabilityNotSupportedError (E3004),
#            LocalSessionStore, file-based SecretStore
```

## Alternatives considered

- **Keep abstractions with TODO markers** — Rejected: adds maintenance burden
  for hypothetical future use; YAGNI principle.
- **Deprecation warnings instead of removal** — Rejected: no external consumers
  exist; deprecation cycle adds no value.

## Dependencies

No new dependencies. Removed implicit dependencies on `cloudpickle`, `msgpack`,
`platform`, and `subprocess` from affected modules.

## Test Strategy

- Each step verified with targeted `pytest` runs on affected test files
- Full test suite run at end: 1459 passed (excluding pre-existing failures in
  `test_local_install.py`, `test_evidence_snapshots.py`, `test_template_catalog.py`)
- No new test failures introduced

## Acceptance criteria

- [x] All 7 cleanup items completed
- [x] No new test regressions
- [x] `__init__.py` exports updated (no stale symbols)
- [x] Lint check shows no new errors from changes
- [x] Type check unchanged (pre-existing errors only)

## Post-cleanup follow-ups (2026-09-23)

Additional doc/config/test alignment performed after adversarial review:

### Documentation alignment
- Removed pickle/msgpack references from `docs/*/guide/declarative-usage.md`, `docs/*/design/architecture.md`, `docs/*/DESIGN.md`, `examples/quickstart/05_decorator_usage.py`, `tests/test_declarative/test_config.py`
- Updated `docs/*/guide/authentication.md` from "Keychain Storage" to "Secret Storage (File-Based)" with plaintext/chmod 600 warnings
- Updated `docs/*/guide/authoring-templates.md`: removed `check_capability()` gate description, replaced with `resolve_capabilities()` fail-closed semantics
- Updated `docs/*/reference/error-codes.md`: E3004 annotated as "now only raised during template resolution, not at API call time"
- Updated `AGENTS.md`: integrations → planned, keychain → secret store, capability gate → capability declaration, guardrail #4 → resolve_capabilities
- Updated `README.md`, `llms.txt`: integrations marked as planned / directory empty

### Test/example alignment
- `e2e_capability_validation.py` E2B-05: changed from negative gate test (expect CapabilityNotSupportedError) to positive port-access test (verify get_host returns valid string)
- `benchmarks/bench_import.py`: removed `easy_sandbox.integrations` import
- `test_config.py`: pickle/msgpack test values → json

### Code robustness
- `decorator.py`: added clear migration error when `serializer != "json"` (instead of raw enum ValueError)
- `keychain.py`: chmod failure now logs explicit warning; files created with restricted permissions via `os.open()` to avoid permission window; docstring notes single-process limitation

### Dependency sync
- `pyproject.toml`: removed `cloudpickle` and `msgpack` from `declarative` extra

### Breaking changes record
- `CHANGELOG.md`: added Breaking Changes section with 5 items and migration guidance
