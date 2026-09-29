# Decision: Add access_key_id / access_key_secret to ebx config set

Status: implemented
Implemented: 2026-09-29

## Problem
Users need to persist AK/SK credentials for the token exchange flow, but
`ebx config set` only supported `api_key` and non-secret fields. There was no
unified mechanism for storing sensitive credentials in the `.env` file versus
non-sensitive settings in `config.toml`.

## Decision
Extend `ebx config set` to accept `access_key_id` and `access_key_secret`:

- Both values are written to `~/.ebx/.env` (same location as `api_key`),
  keeping all secrets in one file with restricted permissions.
- Introduce a `_ENV_STORED_KEYS` set to centrally define which config keys are
  stored in `.env` vs `config.toml`:
  ```python
  _ENV_STORED_KEYS = {"api_key", "access_key_id", "access_key_secret"}
  ```
- `ebx config get` masks `access_key_secret` and `api_key` with `***…<last4>`
  in display output.

## API Design
N/A — this decision does not involve API changes. CLI-only.

## Alternatives considered
- **Store AK/SK in config.toml** — secrets would be in a world-readable config
  file without restricted permissions. Rejected.
- **Use a separate credentials file** — adds complexity with three config file
  locations. Rejected.

## Dependencies
- Existing `cli/commands/config_cmd.py` module
- `python-dotenv` for `.env` read/write

## Test Strategy
- Unit tests verify `config set access_key_id` writes to `.env`.
- Unit tests verify `config get access_key_secret` returns masked output.

## Files changed
- `src/easy_sandbox/cli/commands/config_cmd.py` — `_ENV_STORED_KEYS`, set/get logic

## Acceptance criteria
- ✅ `ebx config set access_key_id LTAI...` persists to `~/.ebx/.env`
- ✅ `ebx config set access_key_secret ...` persists to `~/.ebx/.env`
- ✅ `ebx config get access_key_secret` shows `***…<last4>` masked value
- ✅ Existing `api_key` behavior unchanged
