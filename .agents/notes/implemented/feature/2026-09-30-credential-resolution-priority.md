# Decision: One resolution order for every credential

Status: implemented
Implemented: 2026-09-30
Related: [2026-09-30-unified-config-keys.md](2026-09-30-unified-config-keys.md), [2026-09-29-region-command-level-option.md](2026-09-29-region-command-level-option.md), [2026-09-29-config-init-wizard.md](2026-09-29-config-init-wizard.md), [2026-09-02-dual-auth-mode.md](../architecture/2026-09-02-dual-auth-mode.md)

## Problem

A credential could be set in a function argument, a process environment variable, `./.env`, and `~/.ebx`, and each caller picked a different winner. `Sandbox.create` stopped at the first `.env` file it found, so a project file that did not contain the sandbox key hid `~/.ebx/.env`. `Sandbox.deploy` never read `~/.ebx` at all. `ebx config list` ignored `./.env` and ignored vendor LLM variables when a stored `llm_api_key` existed. `ebx mcp install` parsed `~/.ebx/.env` by hand and could return `SANDBOX_API_KEY` ahead of `E2B_API_KEY`. Public docs also disagreed: getting started listed the code parameter as the lowest priority, and the region notes wrote `ebx config set region` and `SANDBOX_REGION` as one tier.

## Decision

Every credential is resolved in one order. The first non-blank value wins:

1. Explicit argument for this call (`api_key=`, `llm_api_key=`, `openai_base_url=`, `openai_model=`, `--token`, command `--region`).
2. Process environment, in the per-key order below.
3. `./.env`, same names.
4. `~/.ebx`: secrets in `~/.ebx/.env` (`ebx config set`), endpoint / model / region in `~/.ebx/config.toml`.
5. Built-in default, or unset when the key has none.

`.env` files merge per key. `./.env` overrides `~/.ebx/.env` only for a key it sets. A key the project file omits still comes from `~/.ebx/.env`. A blank or whitespace-only value is unset and does not hide the next layer.

`ebx config list` labels the winner `(env)` for the process environment, `(user)` for either file, `(default)` for a built-in default, and `(not set)` when nothing applies. Secrets stay masked.

| Need | Process environment, first hit wins | `~/.ebx` when the layers above are unset | Default |
|---|---|---|---|
| Sandbox API key (`sandbox_api_key`; SDK field stays `api_key`) | `E2B_API_KEY`, then `SANDBOX_API_KEY` | `E2B_API_KEY` in `~/.ebx/.env` | none |
| Alibaba Cloud AK/SK | `ALICLOUD_ACCESS_KEY_*`, then `AccessKey` / `AccessSecret` | the same names in `~/.ebx/.env` | none |
| GitHub token | `GITHUB_TOKEN` | `GITHUB_TOKEN` in `~/.ebx/.env` | none |
| LLM API key | `EBX_LLM_API_KEY`, `BAILIAN_CODING_PLAN_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`, then legacy `EBX_QWEN_CODE_API_KEY` | `EBX_LLM_API_KEY` in `~/.ebx/.env`, then legacy `llm_api_key` in `config.toml`, then `EBX_QWEN_CODE_API_KEY` in `~/.ebx/.env` | none |
| LLM base URL | `EBX_LLM_BASE_URL`, then `OPENAI_BASE_URL` | `llm_base_url` in `config.toml`, then legacy `qwen_code_base_url` | DashScope compatible-mode |
| LLM model | `EBX_LLM_MODEL`, then `OPENAI_MODEL` | `llm_model` in `config.toml`, then legacy `qwen_code_model` | `qwen3-coder-plus` |
| Region | `SANDBOX_REGION` | `region` in `config.toml` | `cn-hangzhou` |

Callers that share this order:

- `Sandbox.create` and the other SDK clients go through `easy_sandbox.transport.config.load_config`. `easy_sandbox.api.sandbox._build_infra` passes that result into `create_auth_provider`. The auth helper does not walk `~/.ebx` itself.
- `Sandbox.deploy` uses `easy_sandbox.api.deploy.resolve_llm_env`. `api/deploy.py` does not import the CLI.
- Natural-language `ebx create` uses `resolve_coding_agent_credentials`, which calls `config_cmd._effective_value` and then passes the winner into `resolve_qwen_code_credentials` as `stored_api_key`. That lower function treats the argument as already chosen.
- `ebx template install` / `ebx template search` use `resolve_github_token` (`--token` is the explicit layer).
- `ebx mcp install` copies the sandbox key from `load_config().api_key`. The `api_url` and `region` it embeds into the editor config are still taken only from the process environment; the later `ebx mcp start` process loads config again.
- `resolve_region` and every regional command use `load_config`, so `SANDBOX_REGION` beats `ebx config set region`.

The user-facing copy of this table is [Credential resolution](../../../../docs/en/reference/configuration.md#credential-resolution) and [凭证解析](../../../../docs/zh/reference/configuration.md#凭证解析).

## API Design

```text
load_config(**overrides) -> TransportConfig
    overrides > process env > merged .env files > ~/.ebx/config.toml > defaults

project_dotenv_value(names: tuple[str, ...]) -> str | None
    first non-blank name in ./.env only

resolve_llm_env(*, llm_api_key, openai_base_url, openai_model) -> dict[str, str]
    explicit > process env > ./.env > ~/.ebx > DashScope default
    raises DeployLLMKeyMissingError (E7001) when no key exists

resolve_github_token(explicit: str | None) -> str | None
    --token > process GITHUB_TOKEN > ./.env > ~/.ebx/.env > None

_effective_value(key) -> (value, "env" | "user" | "default" | "unset")
```

`TransportConfig.api_key` and `Sandbox.create(api_key=)` stay. The CLI name is `sandbox_api_key`.

## Alternatives considered

- **Process environment only, with `~/.ebx` as a write-only store.** Rejected: a developer who ran `ebx config set` and then opened a new shell with no exports would appear to have no key.
- **`~/.ebx` beats the process environment.** Rejected: CI and a one-off `export` must be able to override the machine store without editing it.
- **First existing `.env` file wins as a whole.** Rejected: a project `.env` used for unrelated tools hid the sandbox key stored in `~/.ebx/.env`.
- **A new `(project)` source label in `ebx config list`.** Rejected: both files are user configuration. `(env)` stays reserved for the process environment so the label still answers "will this shell override the files?"
- **Teach `resolve_qwen_code_credentials` to re-read the environment after it receives `stored_api_key`.** Rejected: the CLI already resolved the winner. A second pass would let a vendor variable override an explicit stored argument that a direct caller passed on purpose.

## Dependencies

`easy_sandbox.transport.config`, `easy_sandbox.cli.commands.config_cmd`, `easy_sandbox.api.deploy`, `easy_sandbox.cli.commands._coding_agent`, `easy_sandbox.cli.commands.mcp`, `easy_sandbox.cli.region`. `python-dotenv` reads the `.env` files. Deploy must not import the CLI.

## Test Strategy

`tests/integration/test_credential_priority_e2e.py` points the CLI, `load_config`, `resolve_llm_env`, the coding agent, `resolve_github_token`, `resolve_region`, MCP's editor-config writer, and ACR namespace resolution at one temporary home and one project `.env`. It checks the process environment beating both files, a project file that omits a key still yielding `~/.ebx`, and a key set in `./.env` beating `~/.ebx` and losing to the process environment. It also checks same-layer order (`E2B_API_KEY` over `SANDBOX_API_KEY`, `EBX_LLM_API_KEY` over `DASHSCOPE_API_KEY`, `ALICLOUD_ACCESS_KEY_ID` over `AccessKey`), a command `--region` beating `SANDBOX_REGION`, a blank value falling through, a legacy `EBX_QWEN_CODE_API_KEY`, and `--acr-namespace` over `ACR_NAMESPACE` over `./.env` over `~/.ebx`. An explicit `llm_api_key=` and `--token` still win. MCP copies `SANDBOX_REGION` into the editor config only when the process environment sets it.

`tests/test_transport/test_config.py` covers the per-key `.env` merge. `tests/test_cli/test_config_commands.py` covers a whitespace `GITHUB_TOKEN` falling through to the stored token. `tests/test_cli/test_region_options.py` already asserts `SANDBOX_REGION` beats `config.toml`.

The suite isolates `transport.config._PROJECT_ENV_FILE` so a developer's `./.env` cannot leak into `ebx config list`.

## Acceptance criteria

- With `E2B_API_KEY` exported and a different key in `~/.ebx/.env`, `ebx config list`, `load_config().api_key`, and `ebx mcp install` all use the exported key.
- With neither the process environment nor `./.env` setting `EBX_LLM_API_KEY`, `Sandbox.deploy` and natural-language `ebx create` use the key stored by `ebx config set llm_api_key`.
- A `./.env` that sets only `SANDBOX_HTTP_TIMEOUT` does not hide `E2B_API_KEY` in `~/.ebx/.env`.
- `DASHSCOPE_API_KEY` in the process environment beats a stored `llm_api_key`. `EBX_LLM_API_KEY` beats `DASHSCOPE_API_KEY`.
- `SANDBOX_REGION` beats `region` in `~/.ebx/config.toml`. A command `--region` beats both.
- A whitespace-only `GITHUB_TOKEN` does not hide the stored token.
