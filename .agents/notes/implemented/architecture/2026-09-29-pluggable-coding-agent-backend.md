# Decision: Plug in coding-agent backends behind a protocol boundary (Qwen Code stays the default)

Status: implemented
Implemented: 2026-09-29
Related: [2026-09-29-nl-create-qwen-code-integration.md](../feature/2026-09-29-nl-create-qwen-code-integration.md), [2026-09-29-single-question-clarification.md](../feature/2026-09-29-single-question-clarification.md)

## Problem

The natural-language create path (`ebx create "<description>"`) was hard-wired
to Qwen Code at every level of `src/easy_sandbox/cli/commands/sandbox.py`:

- the helpers themselves were named for the agent
  (`_print_qwen_quick_setup`, `_ensure_qwen_code_binary`,
  `_resolve_qwen_credentials`);
- every user-facing sentence contained the literal string `Qwen Code` (install
  prompt, missing-binary error, credential error, stored-key confirmation,
  Quick Setup guide);
- credential resolution hard-coded `EBX_QWEN_CODE_API_KEY` / `qwen_code_api_key`
  / `qwen_code_base_url` / `qwen_code_model`;
- the gate errors were hard-coded to `QwenCodeNotInstalledError` (E2005) and
  `QwenCodeCredentialError` (E2006).

The product direction is that the sandbox's built-in agent may later be Qoder
CLI, Codex, Claude Code, or a user-defined command — and the *host-side*
generation agent may differ from the *in-sandbox* agent. Adding a second
backend must not mean surgery on the create pipeline and a pile of
near-duplicate messages.

## Decision

Introduce one seam, no plugin framework: `src/easy_sandbox/agent/coding_agent.py`.

### Boundary contract

`CodingAgentBackend` (a `typing.Protocol`) — what the create pipeline needs:

| Member | Purpose |
| --- | --- |
| `name`, `display_name` | identifier + every user-facing message |
| `config_key`, `env_var` | credential storage (`ebx config set <config_key>`) and environment variable |
| `base_url_config_key`, `model_config_key` | optional model endpoint overrides |
| `credential_prompt` | interactive prompt label when a key must be entered |
| `credential_error`, `not_installed_error` | the E-code error types the CLI raises for this backend |
| `quick_setup_lines(reason=...)` | the Quick Setup guide (`"not-installed"` / `"no-credentials"`) |
| `find_binary()` / `install(on_progress=...)` | locate or install the host executable |
| `resolve_credentials(stored_api_key=..., llm_api_key=..., stored_base_url=..., stored_model=...)` | resolve model credentials (raises `credential_error`) |
| `prepare_workdir(description)` | `(workdir, template_name)` shared by clarification and generation |
| `assess(prompt, *, workdir, binary, env, session_id=None, resume=None)` | one structured completeness-assessment round; `None` = unavailable → the CLI degrades to direct generation |
| `generate(description, *, workdir, template_name, resume_session=None, binary=None, env=None, on_progress=None)` | produce `Dockerfile` + `template.yaml` |

`CodingAgentCredentials` is a one-method protocol (`as_env() -> dict[str, str]`)
so a backend may inject whatever variables its CLI needs.

`resolve_coding_agent_backend(name=None)` returns a fresh instance from the
module-level `_BACKENDS` mapping; `None` selects `DEFAULT_CODING_AGENT`
(`"qwen-code"`). Unknown names raise `ValueError` with the available names —
the flow never silently falls back to a different agent than requested.

### Adapter

`QwenCodeBackend` is the only shipped backend. It carries the class variables
above (so every CLI message is *derived*, not duplicated) and every method
delegates to the verified modules — **imported lazily inside the method**:

- `easy_sandbox.agent.qwen_code.find_qwen_code_binary` /
  `download_and_install_standalone` / `resolve_qwen_code_credentials` /
  `official_install_command`;
- `easy_sandbox.agent.codegen.prepare_workdir` / `generate_template_files`;
- `easy_sandbox.agent.clarify.evaluate`.

The lazy imports exist specifically so the existing patch points on those
*source modules* keep intercepting every call — the whole CLI test suite
(`tests/test_cli/test_create_nl.py`) monkeypatches there, never on the adapter.

### Orchestration

`sandbox.py` now talks to `CodingAgentBackend` only:

- `_print_quick_setup(out, *, backend, reason)`;
- `_ensure_coding_agent_binary(ctx, *, yes, backend)`;
- `_resolve_coding_agent_credentials(ctx, *, yes, backend)`;
- `_clarify_requirements(..., backend=...)` drives `backend.assess(...)`;
- `_generate_and_deploy_template` resolves the backend, then
  `find_binary → resolve_credentials → prepare_workdir → clarify → generate`.

`_clarify_requirements` still imports `easy_sandbox.agent.clarify` directly for
the loop's *agent-neutral* surface (threshold, prompt builders, `ClarifyOutcome`
shape, round budget); the model-dependent parts go through `backend.assess`.
The displayed degradation warning interpolates `backend.display_name`.

### Preserved behaviour

- Qwen Code remains the default and its output is **byte-identical**:
  the Quick Setup evidence golden (`create-nl-not-installed`), `help-create`,
  and all 28 `ebx create` CLI tests pass unchanged against the refactor.
- `--yes`, TTY detection, install consent, credential prompting, and the
  build/deploy confirmation behave exactly as before (same tests, same order).
- A backend whose `assess` returns `None` never blocks: the CLI warns and
  continues straight to generation (already exercised by
  `test_unavailable_assessment_degrades_and_names_the_backend`).

## Migration points (deliberately NOT implemented)

Recorded so the next step is mechanical, not exploratory:

1. **No plugin registry / entry-point discovery.** The shipped set is the
   static `_BACKENDS` mapping. Add a class here to ship a new built-in
   backend; entry-point loading is only worth it when third-party plugins
   exist.
2. **No `--coding-agent` selector.** `resolve_coding_agent_backend()` is
   always called with the default. Wiring the flag is one option +
   passing its value at the top of `_generate_and_deploy_template`.
3. **The clarify/codegen protocols speak the Qwen headless dialect**
   (`--json-schema`, `--session-id`, `--resume`, `structured_result` payload;
   sessions keyed by working directory). A second backend implements
   `assess`/`generate` natively (e.g. Claude Code `--output-format json`),
   or those two methods get factored into shared helpers once a real second
   implementation shows the common shape.
4. **`ebx config init` / `ebx config set` still name the Qwen keys** in the
   guided wizard. The backend class variables are the single source for the
   *create path* only; generalising the wizard is follow-up work.
5. **In-sandbox agent axis untouched.** The example templates
   (`qwen-code`, `qoder`) and the envd-side deployment in `api/deploy.py`
   are about what runs *inside* the sandbox and are out of scope here — this
   boundary is the *host-side* generation agent only.

## Dependencies

None new — `typing.Protocol` and `ClassVar` are stdlib.

## Test Strategy

- `tests/test_agent/test_coding_agent.py` (new, 20 tests): resolver semantics
  (default / explicit / unknown + listed names / fresh instance), full
  protocol surface, E-code mapping (`E2005`/`E2006` subclasses of
  `SandboxCreationError`), Quick Setup wording pinned byte-for-byte for both
  reasons, per-method delegation with exact kwargs (binary/install/credentials/
  workdir/assess session pair/generate), and a subprocess check that importing
  the adapter keeps `qwen_code` / `codegen` / `clarify` out of `sys.modules`
  (the lazy-import guarantee).
- `tests/test_cli/test_create_backend.py` (new, 5 tests): a `_DummyBackend`
  with zero Qwen code drives the real CLI end-to-end —
  `create -y` reaches deploy + `Sandbox.create` while every Qwen/codegen/
  clarify entry point stays untouched; a complete assessment reaches the
  confirmation gate and generation resumes the assessment session; an
  unavailable assessment degrades with the dummy's `display_name` in the
  warning; missing binary and missing credentials produce the backend's own
  E-codes and wording (`E2905`/`E2906`, `dummy_api_key`).
- Existing suites green: `tests/test_agent/` 276 passed,
  `tests/test_cli/test_create_nl.py` 28 passed,
  evidence golden `create-nl-not-installed` byte-identical; `ruff` and
  `mypy src/easy_sandbox/` clean.

## Acceptance criteria

- [x] `sandbox.py`'s create path touches the agent only through
      `CodingAgentBackend`; no Qwen-specific message, key, or error class
      remains hard-coded in the pipeline
- [x] Qwen Code default path byte-identical (evidence golden + 28 CLI tests)
- [x] existing patch points on `qwen_code` / `codegen` / `clarify` still work
      (lazy imports, pinned by tests)
- [x] a dummy backend runs the whole create flow with zero real-agent calls
- [x] non-blocking degradation (`assess → None`) and `--yes` skip semantics
      preserved
- [x] migration points listed above

## Files changed

- `src/easy_sandbox/agent/coding_agent.py` (new) — protocols, `QwenCodeBackend`,
  `resolve_coding_agent_backend`, `_BACKENDS`
- `src/easy_sandbox/cli/commands/sandbox.py` — backend-driven helpers and
  generate flow (message templating via class variables)
- `tests/test_agent/test_coding_agent.py` (new)
- `tests/test_cli/test_create_backend.py` (new)

## Consequences

- A second backend is a new class + one mapping entry; the create pipeline,
  gates, and messages need no edits.
- The cost is one indirection layer: every adapter call is a method on a
  protocol object, and the CLI no longer imports `qwen_code` directly in the
  create path.
- Until migration points 1–4 land, "pluggable" means *additive* (register a
  class) rather than *user-selectable* (flag / wizard / third-party entry
  points).
