# Decision: Rolling agent-activity lines under the progress header

Status: implemented
Implemented: 2026-09-30

## Problem

While Qwen Code works, the CLI showed `Assessing description... 12s · <text>`
on a single line. The grey text was glued to the header and was the *tail of
the streamed sentence*, so it was rewritten on every token and never
"scrolled": nothing could be read before it changed.

## Decision

- The header (`message... 12s`, with the spinner) is one line. The agent's
  recent activity is shown in grey on the **next lines**, by default the last
  **four**, and the block **scrolls by line**: a new line pushes the oldest one
  out.
- `EBX_ACTIVITY_LINES` (1..10, default 4) changes the count. Invalid values
  fall back to 4.
- Line semantics live with the producer (`agent/qwen_code.py::_ActivityFeed`):
  streamed assistant text is split at newlines (an unbroken run is cut at 160
  characters), every tool use adds a `tool: <name>` line, `system` adds
  `starting`. The feed is handed to `on_activity` as newline-separated text,
  oldest first (the callback stays a single `str`, so existing callers and
  test doubles keep working). Only assistant text and tool *names* are ever
  recorded, never tool input or thinking.
- The renderer (`cli/output.py`) sanitises each line separately (control
  characters and escape sequences removed, never parsed as Rich markup) and
  cuts every row to the terminal width itself, because Rich wraps an
  over-long row inside a spinner table and the block would grow.
- `--verbose` / `--no-color` use a transient block: it stays at the end of its
  last row, redraws by moving up over the rows it drew (`ESC[nA`) and clears
  with `ESC[J`; log writes erase it first and redraw it afterwards, as before.
- Unchanged: stderr only, absent for `--json` / `--quiet` / CI / `TERM=dumb` /
  non-TTY, 0.1 s redraw throttle, 1 s heartbeat while the agent is silent.

## Alternatives considered

- **Scroll in the renderer by diffing successive one-line summaries** —
  rejected: the summary changes on every token, so the renderer cannot tell a
  new line from a longer one.
- **Fixed-height block padded with blanks** — rejected: an empty gap under
  the header while the agent has produced nothing looks like a glitch.

## Test strategy

- `tests/test_agent/test_qwen_code.py`: `_ActivityFeed` scrolls by line, tool
  use is its own line, the feed is bounded and clean, thinking and unknown
  events change nothing; the real-process streaming test asserts the feed
  contents and that tool input never leaks.
- `tests/test_cli/test_output_activity.py`: header first and grey lines below,
  only the last N shown and scrolling, redraw moves up over the previous
  block, `EBX_ACTIVITY_LINES` parsing, log lines never interleave, control
  characters/markup rendered literally, erase on exit and on exception,
  Rich rendering keeps the lines below the header and never wraps.
- Checked by hand under a pty in both renderers (Rich, `--verbose`).

## Files changed

- `src/easy_sandbox/cli/output.py`, `src/easy_sandbox/agent/qwen_code.py`,
  `src/easy_sandbox/cli/commands/sandbox.py` (docstring)
- `docs/{en,zh}/reference/cli-reference.md`, `CHANGELOG.md`
