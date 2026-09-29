# Decision: Add guided configuration wizard (`ebx config init`) to the ebx CLI

Status: implemented
Proposed: 2026-09-29
Implemented: 2026-09-29

## Problem

New users had to manually discover and set multiple configuration values
(`api_key`, `region`, LLM/Qwen Code credentials) through individual
`ebx config set` calls. There was no guided onboarding flow, which led to:

- Incomplete configurations where users forget required settings.
- Repeated documentation lookups for valid config keys and values.
- Poor first-run experience compared to tools like `aws configure` or
  `gh auth login`, especially now that `ebx create "<description>"` needs a
  DashScope/ModelStudio key for the AI code-generation path.

## Decision

Add `ebx config init` as an interactive configuration wizard covering the three
values a new user needs most: platform API key, default region, and Qwen Code
(AI) credentials.

Interactive behaviour (TTY only):

1. **Platform API key** — hidden input, stored as `E2B_API_KEY` in
   `~/.ebx/.env` via the existing `write_env_var` helper. Empty input skips.
2. **Default region** — prefilled with the currently stored region (or
   `cn-hangzhou`), persisted through `_save_config_dict` into
   `~/.ebx/config.toml`. Empty input keeps the current value.
3. **Qwen Code API key** — hidden input, stored as `EBX_QWEN_CODE_API_KEY` in
   `~/.ebx/.env`; this is the credential read first by the AI create path.

Non-interactive safety (never blocks):

- In non-TTY environments (CI, piped input) or with `--yes`/`-y`, the wizard
  prints the equivalent non-interactive commands and exits 0 without prompting:
  `ebx config set api_key <E2B_API_KEY>`,
  `ebx config set region cn-hangzhou`,
  `ebx config set qwen_code_api_key <DASHSCOPE_OR_MODELSTUDIO_KEY>`.

New configuration keys introduced alongside the wizard:

| Key | Storage | Purpose |
| --- | --- | --- |
| `qwen_code_api_key` | `~/.ebx/.env` (`EBX_QWEN_CODE_API_KEY`) | AI template generation credentials |
| `qwen_code_base_url` | `~/.ebx/config.toml` | OpenAI-compatible base URL (default DashScope compatible-mode) |
| `qwen_code_model` | `~/.ebx/config.toml` | Model name (default `qwen3-coder-plus`) |

## API Design

```python
# CLI command (src/easy_sandbox/cli/commands/config_cmd.py)
@click.option("--yes", "-y", is_flag=True,
              help="Non-interactive: print the equivalent commands instead of prompting")
@click.pass_context
@handle_errors
def init(ctx: click.Context, yes: bool) -> None:
    """Guided setup: platform credentials, region, and Qwen Code (AI)."""

def _print_noninteractive_setup() -> None:
    """Print the non-interactive commands equivalent to the guided wizard."""
```

The wizard reuses the existing config infrastructure only:
`load_config_dict` / `_save_config_dict` for `config.toml`, and
`write_env_var` / `read_env_var` for `~/.ebx/.env` (with the same masking
applied by `ebx config list` / `ebx config get`).

## Alternatives considered

- **Auto-detect on first `ebx create`** — mixes setup with sandbox creation;
  confusing when creation fails due to missing config, and impossible to run
  ahead of time. Rejected.
- **Web-based setup flow** — requires a browser and a server component;
  overkill for a CLI tool. Rejected.
- **`ebx config set` calls only (no wizard)** — kept as the power-user path
  (and as the non-interactive equivalent the wizard prints), but it does not
  solve discoverability on first run. Rejected as the only onboarding path.

## Dependencies

- Click `prompt()` (with `hide_input=True`) for interactive input — already a
  CLI dependency; no new packages.
- Existing `config set` infrastructure for persisting values
  (`write_env_var`, `read_env_var`, `load_config_dict`, `_save_config_dict`).

## Test Strategy

`tests/test_cli/test_config_init.py` (7 tests, fully offline — all storage
paths patched to `tmp_path`):

- Non-TTY run prints the three non-interactive `ebx config set` commands and
  writes nothing to disk.
- `--yes` behaves identically to non-TTY.
- TTY wizard stores `E2B_API_KEY` and `EBX_QWEN_CODE_API_KEY` in `.env` and
  `region` in `config.toml`.
- Sensitive values are never echoed back to the terminal.
- Empty input creates no `.env` file and keeps the default region.
- A previously stored region becomes the prompt default.
- `ebx config list` masks `qwen_code_api_key` (e.g. `abc***456`).

## Acceptance criteria

- [x] `ebx config init` walks through API key, region, and Qwen Code settings
- [x] Non-TTY/CI environments skip the wizard with the equivalent
      non-interactive commands and exit 0
- [x] `--yes` skips prompts with the same non-blocking output
- [x] All values persisted via the existing config infrastructure
      (`~/.ebx/.env` for secrets, `~/.ebx/config.toml` for the region)
- [x] The wizard never blocks in automation and never requires new dependencies

## Implementation

- Command implemented in `src/easy_sandbox/cli/commands/config_cmd.py`
  (`init` + `_print_noninteractive_setup`), registered under the existing
  `ebx config` group.
- `qwen_code_api_key` was added to `_ALLOWED_KEYS` / `_ENV_STORED_KEYS` /
  `_SENSITIVE_KEYS` so `config get|set|list` treat it like the other
  credentials, including masking.
- Help text and docs updated: `cli-reference` (zh/en), `configuration` (zh/en),
  `cli-tutorial` (zh/en).
- CLI evidence regenerated for `ebx config init` (non-TTY capture).

## Evidence

- `.agents/evidence/` captures: `config-init` and the `config init --help`
  case.
- `tests/test_cli_evidence/golden/*.txt` snapshots (79 cases, verified twice).
- `pytest tests/test_cli/ tests/test_agent/` — 517 passed.

## Files changed

- `src/easy_sandbox/cli/commands/config_cmd.py` (wizard, new keys, masking)
- `tests/test_cli/test_config_init.py` (new)
- `scripts/evidence_cases.py`, `.agents/evidence/`,
  `tests/test_cli_evidence/golden/`
- `docs/{zh,en}/reference/cli-reference.md`,
  `docs/{zh,en}/reference/configuration.md`,
  `docs/{zh,en}/guide/cli-tutorial.md`
