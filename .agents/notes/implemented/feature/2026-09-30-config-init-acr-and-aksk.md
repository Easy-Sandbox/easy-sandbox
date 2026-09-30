# Decision: `ebx config init` collects the template-deploy prerequisites

Status: implemented
Implemented: 2026-09-30

## Problem

`ebx install` (and `ebx template deploy`) stop with "Missing ACR namespace"
and "Alibaba Cloud AK/SK credentials not found" unless the user already
knows about `--acr-namespace`, `ACR_NAMESPACE`, and
`ALICLOUD_ACCESS_KEY_ID` / `ALICLOUD_ACCESS_KEY_SECRET`. `ebx config init`
only asked for the sandbox API key, the region, and the LLM API key, so the
first time a user tried to install a template was also the first time they
heard about those prerequisites.

`access_key_id` / `access_key_secret` were already config keys. The ACR
namespace was not: it lived only as a flag, a process variable, or a raw
`.env` line.

## Decision

- `acr_namespace` is a config key, stored in `~/.ebx/.env` as
  `ACR_NAMESPACE`. `config get` / `config set` / `config list` treat it like
  the other env-stored keys. Resolution stays CLI flag, then
  `ACR_NAMESPACE` in the process environment, then `./.env`, then
  `~/.ebx/.env`.
- The guided wizard prompts for six items, each skippable with Enter:
  sandbox API key, region, LLM API key, ACR namespace, AccessKey ID,
  AccessKey Secret. The two API keys and the AccessKey secret stay masked.
- `--yes` and non-TTY sessions print `ebx config set` lines for the
  namespace and the AccessKey pair next to the existing ones.
- The missing-prerequisite errors name `ebx config init` and
  `ebx config set` first.

## Not changed

- A flag or an exported variable still wins over the stored value.
- Pressing Enter still skips a prompt and does not overwrite a stored value
  with an empty string.
- CI guidance still says to pass `--acr-namespace` explicitly when a build
  must not depend on the surrounding environment.

## Test strategy

- `tests/test_cli/test_config_init.py`: the wizard writes
  `ACR_NAMESPACE`, `ALICLOUD_ACCESS_KEY_ID`, and
  `ALICLOUD_ACCESS_KEY_SECRET`; empty answers create no `.env`; the three
  secrets go through the masked prompt; `--yes` prints the new commands.
- `tests/test_cli/test_config_commands.py`: `config set acr_namespace`
  writes `ACR_NAMESPACE` and `config get` reads it back.

## Files changed

- `src/easy_sandbox/cli/commands/config_cmd.py`
- `src/easy_sandbox/cli/commands/template.py` (error text)
- `docs/{en,zh}/reference/cli-reference.md`, `configuration.md`
- `docs/{en,zh}/guide/cli-tutorial.md`, `e2e-template-workflow.md`
- `CHANGELOG.md`
