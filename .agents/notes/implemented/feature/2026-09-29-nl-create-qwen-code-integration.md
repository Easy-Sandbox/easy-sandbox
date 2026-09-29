# Decision: Integrate Qwen Code as the AI coding backend for the `ebx create` NL path

Status: implemented
Proposed: 2026-09-29
Implemented: 2026-09-29

## Problem

`ebx create "natural language description"` previously used keyword matching plus an
optional single-shot LLM classification call to pick one of the existing templates.
This approach:

- Cannot generate custom environments; it only picks from existing templates.
- Requires maintaining a keyword→template mapping that grows stale.
- Does not deliver the "describe what you want, get a working sandbox" experience.

## Decision

Route the natural-language create path through
[Qwen Code](https://github.com/QwenLM/qwen-code) running in headless mode on the host,
generating real `Dockerfile` + `template.yaml` files that are then built, deployed, and
launched through the existing pipelines.

Routing for `ebx create`:

| Invocation | Path |
| --- | --- |
| no DESCRIPTION, no `--template` | `base` template, direct create |
| `--template <name>` | direct template path (`--template` wins over a description) |
| DESCRIPTION only | AI path (this decision) |

AI path pipeline (`src/easy_sandbox/cli/commands/sandbox.py::_generate_and_deploy_template`):

1. **Executable discovery** — `find_qwen_code_binary()` checks `PATH` first, then
   `~/.ebx/bin` (Windows: `qwen.cmd`, `qwen.exe`, `qwen.bat`).
2. **Install guidance** — when missing, an interactive TTY is offered an automatic
   install of the official standalone build: downloaded from the verified Aliyun
   mirror (GitHub release assets as fallback), `SHA256SUMS` mandatory (a mismatch
   aborts immediately, never retrying with an unverified binary), extracted into a
   staging directory and atomically swapped into `~/.ebx/bin` with the executable bit
   set on Unix. Non-TTY without `--yes`, or a declined prompt, raises
   `QwenCodeNotInstalledError` (E2005) plus an actionable Quick Setup — never a hang
   and never a silent fallback.
3. **Credentials** — `resolve_qwen_code_credentials()` resolves in priority order:
   stored `qwen_code_api_key` → stored `llm_api_key` (officially compatible
   same-family fallback) → `OPENAI_API_KEY`/`DASHSCOPE_API_KEY`/
   `BAILIAN_CODING_PLAN_API_KEY` already exported in the environment (inherited by
   the child process, not injected) → `~/.qwen/settings.json` (no injection needed).
   When a stored ebx key drives the run, the child process is given `OPENAI_API_KEY`
   + `OPENAI_BASE_URL` + `OPENAI_MODEL` (DashScope compatible-mode,
   default `qwen3-coder-plus`); `DASHSCOPE_API_KEY` is never injected. Interactive
   terminals may be prompted once for a key, stored via
   `write_env_var("EBX_QWEN_CODE_API_KEY", ...)`; otherwise `QwenCodeCredentialError`
   (E2006) is raised.
4. **Generation and validation** — `generate_template_files()` runs
   `qwen -p "<prompt>" --output-format json --yolo` (list-form argv, `shell=False`,
   bounded cwd and timeout) inside a fresh
   `~/.ebx/generated/<slug>-<timestamp>/` workspace, parses the JSON message array
   (final `type == "result"` message), then validates the outputs: the Dockerfile
   must contain a `FROM` instruction and `template.yaml` must pass the public
   `parse_template_data()` schema validation (reused from `api/capability.py`). The
   generated `name` is pinned to `ebx-nl-<slug>-<token>` before validation.
   Failures/timeouts keep the workspace and raise `AICodegenError` (E2007).
5. **Confirmation, build, create** — unless `--yes`, an interactive confirmation is
   required (`click.UsageError` in non-TTY). The generated workspace is then handed
   to the existing `template deploy` pipeline (`do_deploy` +
   `resolve_acr_namespace`, `--acr-namespace` / `ACR_NAMESPACE`), and the resulting
   template ref is passed to the existing `Sandbox.create`.

The previous keyword/LLM-classification selection is no longer used by `ebx create`;
`llm_api_key` remains supported only as a compatible credential fallback.

## API Design

New module `src/easy_sandbox/agent/qwen_code.py` (host-side adapter):

```python
@dataclass(frozen=True)
class QwenCodeCredentials:
    source: str        # "qwen-stored" | "llm-stored" | "environment" | "qwen-settings"
    api_key: str | None
    base_url: str | None
    model: str | None
    def as_env(self) -> dict[str, str]: ...

@dataclass
class QwenCodeRunResult:
    text: str
    is_error: bool
    exit_code: int
    raw_stdout: str
    raw_stderr: str

def detect_standalone_target(*, system=None, machine=None) -> str | None
def standalone_asset_name(target: str) -> str
def standalone_download_urls(target: str) -> list[tuple[str, str]]  # (mirror, url)
def official_install_command(*, windows=None) -> str
def default_bin_dir() -> Path                       # ~/.ebx/bin

def find_qwen_code_binary(*, bin_dir=None, windows=None) -> Path | None
def download_and_install_standalone(
    *, target=None, bin_dir=None, timeout=180.0, on_progress=None
) -> Path
def resolve_qwen_code_credentials(
    *, stored_api_key=None, llm_api_key=None, stored_base_url=None,
    stored_model=None, environ=None, settings_path=None
) -> QwenCodeCredentials
def run_qwen_code_headless(
    prompt, *, binary=None, env=None, cwd=None, timeout=600.0
) -> QwenCodeRunResult
```

New module `src/easy_sandbox/agent/codegen.py` (generation orchestration):

```python
@dataclass
class CodegenResult:
    workdir: Path
    template_name: str          # ebx-nl-<slug>-<token>
    dockerfile: Path
    template_yaml: Path
    description: str = ""
    raw_output: str = ""

def make_template_name(description: str, *, token=None) -> str
def build_codegen_prompt(description: str, template_name: str) -> str
def generate_template_files(
    description, *, binary=None, env=None, timeout=None,
    base_dir=None, on_progress=None
) -> CodegenResult
```

New error classes in `src/easy_sandbox/models/errors.py` (all
`SandboxCreationError` subclasses): `QwenCodeNotInstalledError` (E2005),
`QwenCodeCredentialError` (E2006), `AICodegenError` (E2007).

`parse_template_data()` was made public in `api/capability.py` so the codegen
validator reuses the exact same YAML schema check as template deploy.

## Alternatives considered

- **Keep keyword matching + single LLM classification** — cannot generate custom
  code; limited to selecting existing templates. Rejected.
- **Bundle qwen-code as a Python dependency** — qwen-code is a standalone
  Node.js-based binary; bundling would bloat the SDK. Rejected.
- **Call a generic OpenAI-compatible chat endpoint and ask for YAML** — no file
  workspace, no agentic tooling; generated Dockerfiles would be unverified text.
  Rejected in favour of a real coding agent with a bounded workspace.
- **Add a custom coding harness** — out of scope; Qwen Code already provides the
  agent loop, file editing, and JSON headless output. Rejected.

## Dependencies

- Qwen Code CLI (external; detected on `PATH`/`~/.ebx/bin`, or installed on demand
  from the verified official standalone assets).
- DashScope/ModelStudio-compatible API key for the Qwen Code backend
  (`qwen_code_api_key`, or a compatible `llm_api_key`, or an exported env var).
- Python standard library only for the adapter (`urllib`, `hashlib`, `subprocess`,
  `tarfile`/`zipfile`) — no new third-party dependencies.

## Test Strategy

All tests are offline; the network and the `qwen` binary are fully mocked.

- `tests/test_agent/test_qwen_code.py` (42 tests) — platform/target detection and
  asset matrix, mirror URL construction, SHA256SUMS parsing and mismatch handling,
  atomic install (staging → swap, executable bit), PATH/`~/.ebx/bin` discovery
  (including Windows suffixes), credential resolution order, headless JSON parsing,
  timeout/exit-code handling, install-command strings.
- `tests/test_agent/test_codegen.py` (18 tests) — prompt construction, template
  naming/slugging, missing files, Dockerfile without `FROM`, invalid YAML /
  schema-invalid `capability`, non-mapping YAML, success path, timeout propagation.
- `tests/test_cli/test_create_nl.py` (16 tests) — create routing (`--template`
  bypass, description → AI path, no-args → base), not-installed prompt and refusal
  (E2005), non-TTY failure (no hang), credential prompt and storage, `--yes`
  behaviour, generation failure (E2007), build failure propagation, explicit
  template bypassing codegen.
- Evidence snapshots regenerated via
  `scripts/capture_cli_evidence.py` and `EBX_UPDATE_EVIDENCE=1 pytest
  tests/test_cli_evidence/` (79 cases).
- No integration test downloads the real binary or calls the network.

## Acceptance criteria

- [x] `ebx create "build a web scraper"` triggers Qwen Code headless mode
- [x] First-time setup guides the user through binary install and credential
      configuration (interactive; `--yes` for non-interactive)
- [x] Standalone install works for the officially published targets
      (`darwin-x64/arm64`, `linux-x64/arm64`, `win-x64`; no `win-arm64` exists)
- [x] Failure paths raise E2005/E2006/E2007 with an actionable Quick Setup and
      never silently fall back to `base`
- [x] Explicit `--template` always bypasses AI generation
- [x] Non-TTY environments without `--yes` fail fast instead of hanging

## Implementation

- `ebx create` with a DESCRIPTION and no `--template` calls
  `_generate_and_deploy_template`, then continues through the pre-existing
  create/upload flow unchanged (same env/metadata/timeout/upload handling).
- `generate_template_files` writes into `~/.ebx/generated/<slug>-<timestamp>/`
  and keeps the workspace on failure for inspection (path included in E2007).
- Codegen timeout defaults to 600s, overridable via `EBX_QWEN_CODEGEN_TIMEOUT`.
- The child process environment starts from a copy of the current environment;
  only when a stored ebx key is the credential source are `OPENAI_*` variables
  merged in.
- Docs updated: `cli-reference` (zh/en), `cli-design` section 3 (zh/en),
  `cli-tutorial` (zh/en), `error-codes` (E2005–E2007, zh/en), `configuration`
  (zh/en), plus regenerated CLI evidence.

## Evidence

- `scripts/evidence_cases.py` — `create-nl-python`, `create-nl-nodejs`,
  `create-nl-confirm-required`, `create-nl-not-installed` cases.
- `.agents/evidence/` markdown captures and
  `tests/test_cli_evidence/golden/*.txt` snapshots (79 cases, verified twice).
- `pytest tests/test_cli/ tests/test_agent/` — 517 passed (includes the 76 new
  codegen/qwen-code/create tests).

## Files changed

- `src/easy_sandbox/agent/qwen_code.py` (new)
- `src/easy_sandbox/agent/codegen.py` (new)
- `src/easy_sandbox/models/errors.py` (E2005/E2006/E2007)
- `src/easy_sandbox/api/capability.py` (`parse_template_data` made public)
- `src/easy_sandbox/cli/commands/sandbox.py` (AI create path, `--yes`,
  `--acr-namespace`)
- `src/easy_sandbox/cli/commands/config_cmd.py` (qwen_code_* keys, `config init`)
- `tests/test_agent/test_qwen_code.py`, `tests/test_agent/test_codegen.py`,
  `tests/test_cli/test_create_nl.py`, `tests/test_cli/test_config_init.py`
- `scripts/evidence_cases.py`, `.agents/evidence/`,
  `tests/test_cli_evidence/golden/`
- `docs/{zh,en}/reference/cli-reference.md`, `docs/{zh,en}/design/cli-design.md`,
  `docs/{zh,en}/guide/cli-tutorial.md`, `docs/{zh,en}/reference/error-codes.md`,
  `docs/{zh,en}/reference/configuration.md`

## Errata

- **2026-09-29 — `ebx deploy` turn-budget flag.** The project-deployment
  path (`api/deploy.py::_build_qwen_command`) originally emitted
  `--max-turns`, which is not a Qwen Code flag: the CLI parses with yargs
  `strict()` and rejects it as `Unknown arguments: max-turns, maxTurns`
  (verified live against the official `@qwen-code/qwen-code@0.23.0` package,
  the version pinned by the `qwen-code` template Dockerfile; `--max-turns`
  does not appear in `qwen --help`). The correct headless flag is
  `--max-session-turns` — an integer capping user/model/tool turns;
  exceeding it exits with code 53, matching
  `_QWEN_EXIT_MAP[53] = "turn_limit_exceeded"`. Fixed in
  `_build_qwen_command` and the `qwen-code` template's `deploy` command
  (`commands.py`, `template.yaml`), asserted in
  `tests/test_api/test_deploy.py` (`test_build_qwen_command*`, including a
  skip-if-absent live `qwen --help` flag check). Public parameter names
  (`max_tool_calls` / `--max-tool-calls`) are unchanged.
