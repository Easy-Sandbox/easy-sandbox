# Decision: `ebx deploy` is the fixed publish step; descriptions belong to template authoring

Status: implemented
Implemented: 2026-09-30
Supersedes (partial): [2026-09-09-template-deploy-command.md](2026-09-09-template-deploy-command.md) — its "coexisting `ebx deploy`" section (project deployment into a sandbox via an in-sandbox agent) is replaced.
Related: [2026-09-30-nl-template-server-entrypoint.md](2026-09-30-nl-template-server-entrypoint.md), [2026-09-30-nl-template-init-and-create-scope-prompt.md](2026-09-30-nl-template-init-and-create-scope-prompt.md).

> The file name keeps `agent-flag` for history: a `deploy --agent` flag was first implemented and then **withdrawn the same day** (see "Reversed decision").

## Problem

Reported while using the CLI:

1. `ebx deploy` failed with `[E7001] No LLM API key found for qwen-code agent` — asking for `BAILIAN_CODING_PLAN_API_KEY` / `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`, unrelated to the LLM key `ebx config` / `ebx create` manage.
2. `ebx deploy --verbose` failed with `No such option: --verbose`.
3. The intent was unclear: `deploy` is naturally "build + push + create template", a fixed procedure, yet it started a `qwen-code` **cloud sandbox** with its own agent and its own LLM route.

Root cause: `deploy_shortcut` was a separate "NL project deployment" product (`Sandbox.deploy`) that shared only the name with the template pipeline: its own credential chain (`api/deploy.py`), a private option set (no `-v`, no `--region`, no ACR options), unusable without an LLM.

## Decision

The template lifecycle has three steps with one job each:

| Step | Command | Input | AI |
|------|---------|-------|----|
| 1. Author | `ebx template init` / `ebx template init "DESCRIPTION"` | scaffold case or description → `Dockerfile`, `commands.py`, `template.yaml` | optional |
| 2. Publish | `ebx deploy [PATH]` | the template directory | never |
| 3. Launch | `ebx create --template ID` | template ID | never |

`ebx create "DESCRIPTION"` = 1 + 2 + 3 with a confirmation before anything is pushed.

1. **`ebx deploy [PATH]` = `ebx template deploy`** with `PATH` defaulting to `.`: `docker build` → push to ACR → `CreateTemplate` → poll. No LLM, no key, no cloud sandbox, **no description argument**. The option set is derived from `template build.params` at import time, so `-v/--verbose`, `--acr-namespace`, `--region`, `--yes`, ... are inherited and cannot drift.
2. **What a template is lives in `template.yaml`** (plus `Dockerfile` / `commands.py`), written at authoring time. `deploy` only reads `name`, `resources.cpu`, `resources.memory`, `generation`; CLI options override them.
3. A missing `Dockerfile` stops `deploy` with a message that points at `ebx template init`.
4. `--traditional` becomes a hidden, deprecated no-op with a warning. The old `INSTRUCTION` argument is removed (click reports an unexpected extra argument).
5. `Sandbox.deploy()` (in-sandbox agent deploy) is kept as an **SDK API only**; `DeployLLMKeyMissingError` (E7001) remains for it, with an updated suggestion.

## Reversed decision: `deploy --agent`

First implemented: `ebx deploy [PATH] [INSTRUCTION] --agent` ran the local Qwen Code on the project to write `Dockerfile` + `template.yaml` before the pipeline (flag name chosen over `--auto` / `--ai` because it names the actor). It was **withdrawn** after review, for these reasons:

- **Two sources of truth.** A description given at deploy time ("FastAPI, listens on 8080") is exactly the information that belongs in `template.yaml` (`ports`, `capabilities`, `resources`, `env`, `custom_commands`). Typed into a deploy command it is consumed once and never recorded, so the next deploy cannot reproduce it.
- **Wrong verb.** `deploy` is a fixed publish step; generating or editing source files inside it makes a cloud-cost command also a code-rewriting command.
- **Drift from the real template contract.** Since the generator now writes `commands.py` (the `SandboxServer` without which a deployed sandbox cannot be used), a second, separate prompt for "existing project" files would have to be kept in sync with `agent/template_guide.py`, and it was not.
- Same LLM route and credentials as `ebx create` was right, but that is achieved by authoring through `template init`, which already reuses it.

The code written for it (`deploy --agent`, `CodingAgentBackend.generate_for_project`, `codegen.prepare_project_template`, `.ebx-bak` backups, tree fingerprinting) was removed rather than left as dead code.

## Open follow-up (not implemented): adopting an existing project

An existing project without a `Dockerfile` / `template.yaml` has no AI path today. If needed, it belongs under **authoring**, not `deploy`: e.g. `ebx template init` reading an existing directory and writing the template files next to the code, through the same `_generate_template_workspace` and `TEMPLATE_GUIDE`, with the backup / "files touched" guard rails that were prototyped here. It needs its own design because `template init DIRECTORY` currently means "scaffold into this directory" and natural-language init takes a single positional.

## Alternatives rejected

- **Keep the NL default and only add `--verbose`.** Fixes the symptom but keeps a hidden LLM dependency and second credential route for a command whose name promises a fixed procedure.
- **`deploy` auto-detects a missing Dockerfile and runs the AI silently.** Surprising: edits the user's tree and needs an LLM without being asked.
- **Drop `Sandbox.deploy`.** Public SDK surface with tests; only the CLI route was wrong.

## Consequences

- **Breaking for CLI users** who relied on `ebx deploy ./p "instruction"`: author with `ebx template init "DESCRIPTION"`, then `ebx deploy ./<name>`. Documented in CHANGELOG (Breaking Changes #2).
- Fewer credential concepts: CLI AI steps use `ebx config` / `EBX_LLM_*`; only the SDK `Sandbox.deploy` keeps its own env-var chain.
- `ebx deploy --help` lists ~30 options because it mirrors `template deploy`; acceptable, and prevents drift.

## Verification

- `tests/test_cli/test_deploy_commands.py`: delegation, `PATH` default, never touches agent / LLM keys / `Sandbox.deploy`, `-v` works, option parity with `template build`, help has no AI options, description argument and `--agent` / `-i` are rejected, missing Dockerfile points at `template init`, ACR fail-fast, deprecated `--traditional`.
- Golden `help-deploy`.

## Related changes shipped with this report

- `ebx create --dir DIRECTORY` and the interactive "Save the generated template under which directory?" prompt (default `~/.ebx/generated`).
- Live activity block (`OutputManager.activity`: header plus scrolling grey lines, see `2026-09-30-rolling-agent-activity-lines.md`) fed by `--output-format stream-json`, with process-tree termination on timeout / Ctrl-C.
- Bounded research round (20 turns, 240 s, `EBX_QWEN_RESEARCH_TIMEOUT`), separate "Researching public facts" phase, and a **fresh session** for the assessment after a failed research round (qwen rejects re-pinning an existing `--session-id`, the cause of the bogus "assessment unavailable" warning).
