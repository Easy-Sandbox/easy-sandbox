# Decision: One CLI name per credential

Status: implemented
Implemented: 2026-09-30
Related: [2026-09-30-credential-resolution-priority.md](2026-09-30-credential-resolution-priority.md), [2026-09-29-config-init-wizard.md](2026-09-29-config-init-wizard.md), [2026-09-29-pluggable-coding-agent-backend.md](../architecture/2026-09-29-pluggable-coding-agent-backend.md)

## Problem

`ebx config list` showed two LLM profiles (`qwen_code_*` and `llm_*`) and a sandbox key named `api_key`. The two API keys are the same kind of OpenAI-compatible credential, and `api_key` does not say which service it authenticates. Users had to guess which key to set.

## Decision

The CLI config surface keeps one name per credential:

- `sandbox_api_key` is the sandbox control-plane key. It is still stored as `E2B_API_KEY` in `~/.ebx/.env`. Process environment order stays `E2B_API_KEY` then `SANDBOX_API_KEY`. `config get` / `config set api_key` is an alias and is not listed.
- `llm_api_key`, `llm_base_url`, and `llm_model` are the only LLM profile, used by NL inference and the coding agent (including Qwen Code).
- `qwen_code_api_key`, `qwen_code_base_url`, and `qwen_code_model` are rejected with a pointer at the `llm_*` replacement.
- When an `llm_*` value is unset, an older `EBX_QWEN_CODE_API_KEY` or stored `qwen_code_base_url` / `qwen_code_model` is still read and displayed under the `llm_*` name. Setting the `llm_*` key drops that older copy.
- Which of those values wins at use time is [2026-09-30-credential-resolution-priority.md](2026-09-30-credential-resolution-priority.md).

The Python SDK parameter stays `api_key=` so E2B-compatible call sites do not change.

## API Design

CLI keys (`ebx config get` / `ebx config set` / `ebx config list`):

- `sandbox_api_key: str` → env `E2B_API_KEY`. Alias: `api_key`.
- `llm_api_key: str` → env `EBX_LLM_API_KEY`.
- `llm_base_url: str`, default DashScope compatible-mode.
- `llm_model: str`, default `qwen3-coder-plus`.

SDK: `Sandbox.create(api_key=...)` is unchanged.

## Alternatives considered

- **Rename `TransportConfig.api_key` and every SDK parameter to `sandbox_api_key`.** Rejected: that breaks the E2B-compatible public API for a CLI labeling problem.
- **Keep listing both `api_key` and `sandbox_api_key`.** Rejected: the list would still show two names for one secret.
- **Drop `llm_base_url` and `llm_model` as well.** Rejected: the endpoint and model are not a second API key; users with a custom OpenAI-compatible endpoint still need one place to set them.
- **Delete older `qwen_code_*` files on `config list`.** Rejected: listing must not rewrite secrets. Read-time fallback preserves a working install.

## Dependencies

`easy_sandbox.cli.commands.config_cmd`, `easy_sandbox.cli.commands._coding_agent`, `easy_sandbox.agent.qwen_code` (default base URL and model).

## Test Strategy

CLI tests cover the alias, the removed-key error, legacy `EBX_QWEN_CODE_API_KEY` / `qwen_code_base_url` / `qwen_code_model` read as `llm_*`, and `llm_api_key` winning when both secrets exist. Golden files for `config list`, `config get`, `config set`, and `config init` are regenerated.

## Acceptance criteria

- `ebx config list` does not print `api_key` or any `qwen_code_*` key.
- `ebx config list` prints `sandbox_api_key`, `llm_api_key`, `llm_base_url`, and `llm_model`.
- `ebx config set api_key` still writes `E2B_API_KEY`.
- `ebx config set qwen_code_api_key` exits 2 and names `llm_api_key`.
- A machine that only has `EBX_QWEN_CODE_API_KEY` still resolves that value as `llm_api_key`.
