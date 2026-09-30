# Decision: Stream build and push logs under the step header

Status: implemented
Implemented: 2026-09-30

## Problem

`docker build`, `docker push`, and the wait for a template to become READY
could run for minutes behind a single spinner (`[3/3] Building Docker image
locally: …`). The same was true of `Generating template... 119s` whenever the
agent spent that time inside a tool: the header's elapsed time moved only
when a new activity event arrived, and a tool name appeared only after the
tool returned. The terminal looked frozen.

## Decision

- Long deploy steps use the same block as agent generation: a
  `message... 12s` header, and under it the last `EBX_ACTIVITY_LINES`
  (default 4) log lines in grey, scrolling by line.
- `docker build` / `docker push` lines are that log. BuildKit is asked for
  `--progress=plain` (stdout is a pipe; the tty progress UI would be cursor
  noise). A one-second refresh redraws the header while the tool is silent.
- The READY poll is one grey line per sample (`STATE  12s`), not a second
  spinner.
- `--verbose` prints every line in full and does not draw the block.
  `--json`, `--quiet`, CI, and non-TTY stay one progress line; per-line
  output is not written there.
- Generation already used this block. A tool name is now recorded when the
  call starts (`content_block_start`), and the completed assistant message
  does not repeat it. Tool input and thinking are still never shown.

## Alternatives considered

- **Print every docker line as it arrives** — rejected for the default
  terminal: a build log is hundreds of lines, and the four-line window is
  what the user asked to watch. `--verbose` remains the full log.
- **Show tool input during generation** — rejected: shell commands and file
  contents can carry secrets.

## Follow-up: every long CLI step

The same header now covers steps outside deploy. `OutputManager.spinner` is that header (elapsed time redrawn once a second) on a terminal, and stays silent otherwise — quiet, JSON, CI, and non-TTY do not gain a new progress line.

Grey lines are added only where the text is safe:

- upload and `ebx create --upload` list relative paths, never file bytes
- the coding-agent install lists milestones (mirror, checksum, extract)
- `ebx kill --all` lists `i/N <id>`
- the legacy template build wait appends `status  Ns` through `on_output`, without restarting the phase

Download, template fetch, and `ebx template create` have no line log; the header is enough. `--build-arg` values are redacted in the docker command info log. ACR token response bodies are not debug-logged.

## Test strategy

- `tests/test_cli/test_step_activity.py`: lines accumulate under the phase,
  blanks are dropped, verbose prints them instead, a non-TTY session does
  not, and a silent phase still refreshes.
- `tests/test_cli/test_output_activity.py`: a spinner on a terminal is the
  elapsed header and advances; quiet mode writes nothing.
- `tests/integration/test_progress_activity_e2e.py`: a mocked deploy shows
  build lines under the header and not on stdout; upload names files and
  not their bytes; a non-TTY deploy does not dump those lines. The same
  file covers create, download, `kill --all`, template fetch, template
  create, the coding-agent install milestones, and `--json` deploy.
- `tests/test_api/test_docker_builder.py`: `--build-arg` values stay in the
  subprocess command and are redacted in the info log.
- `tests/test_protocol/test_template.py`: `wait_for_build` reports each poll.
- `tests/test_api/test_docker_builder.py`: the build command includes
  `--progress=plain` and the callback receives the line.
- `tests/test_agent/test_qwen_code.py`: the tool name shows at start, is not
  repeated, and the input does not appear.

## Files changed

- `src/easy_sandbox/cli/output.py`, `src/easy_sandbox/cli/commands/template.py`,
  `src/easy_sandbox/cli/commands/sandbox.py`, `src/easy_sandbox/cli/commands/_coding_agent.py`,
  `src/easy_sandbox/api/docker_builder.py`, `src/easy_sandbox/protocol/template.py`,
  `src/easy_sandbox/agent/qwen_code.py`
- `docs/{en,zh}/design/cli-design.md`, `docs/{en,zh}/guide/deploy-and-build.md`,
  `docs/{en,zh}/reference/cli-reference.md`, `CHANGELOG.md`
