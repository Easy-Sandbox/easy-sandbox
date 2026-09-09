# AGENTS.md — AI Contributor Entry Point

> **For AI coding assistants** (Cursor, Copilot, Codex, Qoder, etc.).
> Human contributors: see [CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Project Overview

**Serverless Sandbox** (`serverless-sandbox` on PyPI, CLI command `sbox`) is a Python SDK + CLI for the Alibaba Cloud FC Agent Sandbox service. It is **E2B-protocol compatible** with extensions for the Alibaba Cloud ecosystem (OSS, VPC, custom domains).

- **Language:** Python 3.10+
- **Build system:** Hatchling
- **Package:** `src/serverless_sandbox/`
- **Entry point:** `sbox` → `serverless_sandbox.cli.main:cli`

---

## Directory Structure

```
serverless-sandbox/
├── src/serverless_sandbox/    # SDK source
│   ├── models/                # Data models: config, errors, sandbox, template, session, filesystem, process
│   ├── transport/             # HTTP/WS transport, auth, codec, retry, streaming
│   ├── protocol/              # Protocol abstractions: sandbox, filesystem, process, terminal, port, code_interpreter
│   ├── api/                   # High-level API: Sandbox, files, code, commands, network, image, capability, session_manager, template
│   ├── cli/                   # Click-based CLI (`sbox`), formatters, command modules
│   │   └── commands/          # Subcommands: auth, config_cmd, deploy, mcp, sandbox, secret, session, skill, template
│   ├── agent/                 # AI agent tooling: builtin agents, MCP server, tool definitions, inference
│   ├── compat/                # E2B compatibility layer (drop-in replacement)
│   ├── declarative/           # @sandbox decorator, config, serializer
│   ├── extensions/            # Alibaba Cloud extensions: OSS, VPC, custom domains
│   ├── integrations/          # Framework adapters: LangChain, CrewAI, AutoGen
│   ├── session/               # Session persistence: local, OSS-backed, database
│   └── utils/                 # Async bridge, keychain, logging, registry, retry
├── tests/                     # Mirrors src/ structure (test_api/, test_cli/, test_models/, …)
├── docs/
│   ├── design/                # Architecture & feature design documents
│   └── evidence/              # Golden-file CLI evidence (auto-generated, see below)
├── examples/
│   └── templates/             # Sandbox template examples (python-hello, codex, qoder, …)
├── .agents/notes/             # Architecture Decision Records (ADR) — see below
├── scripts/                   # Utility scripts (evidence capture, etc.)
├── benchmarks/                # Performance benchmarks
├── Makefile                   # Dev commands
└── pyproject.toml             # Build config, dependencies, tool settings
```

---

## Architecture Layers

The SDK follows a strict layered architecture — **lower layers never import upper layers**:

```
L0  Models        models/           Pydantic data models, error hierarchy, config  (no cross-module deps)
L0  Utils         utils/            Async bridge, keychain, logging, registry, retry (no cross-module deps)
L1  Transport     transport/        HTTP, WebSocket, auth, codec, streaming         (depends on L0)
L2  Protocol      protocol/         Sandbox lifecycle, filesystem, process, terminal, port (depends on L0+L1)
L3  API           api/              High-level Sandbox class, file ops, code exec, capability (depends on L0–L2)
─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ─── ───
    CLI           cli/              Click commands, formatters
    Agent/MCP     agent/            MCP server, builtin agents, tool defs
    Integrations  integrations/     LangChain, CrewAI, AutoGen adapters
    Declarative   declarative/      @sandbox decorator
    Compat        compat/           E2B compatibility shim
    Extensions    extensions/       OSS, VPC, domain extensions
    Session       session/          Persistence (local/OSS/DB)
```

---

## Development Commands

### Setup

```bash
# Install with all dev dependencies (test + lint + all extras)
pip install -e ".[dev]"

# Or just CLI extras
pip install -e ".[cli]"
```

### Day-to-Day

| Command              | What it does                           |
|----------------------|----------------------------------------|
| `make test`          | `pytest tests/ -v --tb=short`          |
| `make test-cov`      | Tests with coverage report             |
| `make lint`          | `ruff check src/ tests/`               |
| `make format`        | `ruff format src/ tests/`              |
| `make typecheck`     | `mypy src/serverless_sandbox/`         |
| `make clean`         | Remove build artifacts and caches      |

### Running a Specific Test

```bash
pytest tests/test_api/test_sandbox.py -v
pytest -k "test_capability" -v
```

---

## Key Conventions

### Error Code System

All SDK errors live in [`models/errors.py`](src/serverless_sandbox/models/errors.py). Error codes follow `E{category}{sequence}`:

| Range   | Category       | Base Class               |
|---------|----------------|--------------------------|
| E1xxx   | Authentication | `AuthenticationError`    |
| E2xxx   | Creation       | `SandboxCreationError`   |
| E3xxx   | Execution      | `ExecutionError`         |
| E4xxx   | Filesystem     | `FileOperationError`     |
| E5xxx   | Network        | `NetworkError`           |
| E6xxx   | Session        | `SessionError`           |

Every exception carries: `code`, `message`, `suggestion`, `docs_url`.

### Capability Model

Defined in [`models/template.py`](src/serverless_sandbox/models/template.py), resolved by [`api/capability.py`](src/serverless_sandbox/api/capability.py).

- **`STANDARD_CAPABILITIES`** = `{shell, files, code, terminal, ports}` — all recognised tokens
- **`DEFAULT_CAPABILITIES`** = `{shell, files, code}` — applied when a template declares nothing
- `terminal` and `ports` **must** be declared explicitly in the template's `template.yaml`
- **Capability gate:** `check_capability()` raises `CapabilityNotSupportedError` (E3004) if a required capability is missing — **never bypass this gate**
- **Fail-closed:** if a matched template's YAML is malformed, the resolver raises `TemplateParseError` (E2004) rather than silently falling back to defaults

### Capability Resolution Priority

1. Explicit `local_yaml_path` (programmatic override)
2. Local template cache scan (`~/.sbox/templates/`)
3. *(Phase 2, TODO)* Online fallback — `GET /templates/{id}`
4. Fall back to `DEFAULT_CAPABILITIES` + warning

### CLI Command Resolution Priority

When `sbox create` resolves a template:
- Programmatic specification → local project `template.yaml` → installed template cache → *(Phase 2)* online registry → `DEFAULT`

### Template Definition

Templates use `template.yaml` (not `manifest.yaml` for capability purposes). Key fields: `name`, `capabilities`, `custom_commands`, `alias`/`aliases`.

---

## Testing Conventions

### Standard Tests

- Framework: **pytest** + **pytest-asyncio** (mode: `auto`)
- Structure mirrors `src/`: `tests/test_api/`, `tests/test_cli/`, `tests/test_models/`, etc.
- Integration tests marked with `@pytest.mark.integration` — skip with `-m "not integration"`
- Type annotations enforced: `mypy --strict`

### Golden-File CLI Evidence

The `docs/evidence/cli/` directory contains auto-generated golden-file snapshots of every CLI command's input→output behaviour.

**Regenerate:**
```bash
# Offline (mocked backend) — default
python scripts/capture_cli_evidence.py

# With real backend
E2B_API_KEY=your-key python scripts/capture_cli_evidence.py --live

# Single command group
python scripts/capture_cli_evidence.py --command create
```

To update golden files when tests use snapshot comparison:
```bash
SBOX_UPDATE_EVIDENCE=1 pytest tests/
```

---

## Contributing References

| Resource                | Path                                                                 |
|-------------------------|----------------------------------------------------------------------|
| Contributing guide      | [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md)                 |
| PR template             | [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) |
| Security policy         | [`.github/SECURITY.md`](.github/SECURITY.md)                        |
| Architecture decisions  | [`.agents/notes/`](.agents/notes/README.md) (ADR system)            |
| Design documents        | [`docs/design/`](docs/design/)                                      |
| CLI evidence            | [`docs/evidence/`](docs/evidence/README.md)                         |
| Changelog               | [`CHANGELOG.md`](CHANGELOG.md)                                      |

### ADR System (`.agents/notes/`)

Architecture Decision Records follow a `proposed → implemented | rejected` lifecycle:

```
.agents/notes/
├── proposed/          # Under review
│   ├── architecture/
│   ├── feature/
│   └── process/
├── implemented/       # Accepted and active
│   ├── architecture/
│   ├── feature/
│   └── process/
└── rejected/          # Considered but not adopted (flat directory, no subdirectories)
    ├── .gitkeep
    └── *.md
```

See [`.agents/notes/README.md`](.agents/notes/README.md) for the full template and process.

---

## AI Assistant Guardrails

**MUST follow:**

1. **Never auto-commit.** Make changes; let the human review and commit.
2. **Never delete golden files** in `docs/evidence/cli/`. If CLI output changes, regenerate them via `python scripts/capture_cli_evidence.py`.
3. **After modifying any CLI command**, regenerate the affected evidence files and verify they look correct.
4. **Never bypass capability gates.** If `check_capability()` blocks an operation, the fix is to declare the capability in the template — not to remove the gate.
5. **Never fabricate FC/envd API endpoints.** If you're unsure about a real backend API, flag it as a TODO rather than inventing a placeholder.
6. **Run the full test suite** (`make test && make lint && make typecheck`) before claiming a task is done.
7. **Secret scanning** is enforced via `.githooks/check-secrets.sh`. Never commit API keys, tokens, or passwords. Use `REPLACE_ME` or `placeholder` for examples.
8. **Conventional Commits** for all commit messages: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`, `perf:`.
9. **Minimize changes.** Touch only the files necessary for the task. Don't refactor unrelated code.
10. **Type annotations** on all public APIs. Google-style docstrings.
11. **Layer dependency constraint.** Lower layers must never import upper layers (L0 must not import L1+, L1 must not import L2+, etc.). If you need a type from a higher layer, refactor it downward or use dependency injection.
12. **Maintain `__all__` exports.** When adding or removing any public symbol in a module's `__init__.py`, update the `__all__` list to match.
13. **Pydantic alias convention.** Model fields that map to camelCase API responses use `Field(alias="camelCaseName")`. Always use `model_config = ConfigDict(populate_by_name=True)` so both the alias and the Python snake_case name work.
