# Decision: AI-generated templates ship a SandboxServer entry point

Status: implemented
Implemented: 2026-09-30

## Problem

`ebx create "DESCRIPTION"` and `ebx template init "DESCRIPTION"` asked the
coding agent for two files, `Dockerfile` and `template.yaml`, and told it to
create nothing else. A deployed sandbox is reached over HTTP(S)
(`https://<port>-<sandbox_id>.<domain>`), so an image with no long-running
server has nothing to answer: the generated template could be built and
deployed but not used. Every reference template in
`Easy-Sandbox/awesome-templates` (all eleven) instead ships a `commands.py`
that starts the container-side `easy_sandbox.server.SandboxServer` on port
9000, plus a README. The agent also had no description of that SDK, so it
could not have written one.

## Decision

1. **The generation prompt asks for a usable template.** Required files:
   `Dockerfile`, `commands.py`, `template.yaml`, and a short `README.md`.
   Business code / dependency manifests are allowed when the request needs
   them; unrelated files are not. Unchanged: no docker, no installs, no
   secret files.
2. **The server SDK reference is part of the prompt.**
   `src/easy_sandbox/agent/template_guide.py` holds `TEMPLATE_GUIDE`, a
   condensed form of `docs/en/design/server-api.md` and the awesome-templates
   conventions: why a server is needed, the Dockerfile rules (python3 + the
   `COPY *.whl` / PyPI install pattern, `COPY commands.py`, `EXPOSE 9000`,
   `CMD ["python3", "commands.py"]`), the `easy_sandbox.server` API
   (`CapabilityGroup` and its default-disabled groups, `CommandRegistry`,
   `RouteTable.route`, `ServerResponse`, `SSEResponse`, auth via
   `EBX_SERVER_TOKEN` / `X-Access-Token`), how to run a business web service
   next to the server, the `template.yaml` fields (`capabilities` mapped to
   the enabled groups, `ports` including 9000, `custom_commands`, `env`
   names only) and a complete minimal `commands.py`.
3. **Fail closed on Dockerfile-only output.** `generate_template_files`
   raises `AICodegenError` when `commands.py` is missing, is not valid
   Python, never imports `easy_sandbox.server` / calls `serve()` (or
   `start()`), or when the Dockerfile never references `commands.py`.
4. **Every deliverable travels.** `CodegenResult.commands_py` and
   `CodegenResult.files` (workspace-relative, dot-files other than
   `.dockerignore`, `__pycache__`, `*.pyc`, `*.whl` excluded) drive the
   local copy made by `template init "DESCRIPTION"` and by the create
   switch, so `./<name>/` contains the whole template. The deploy path
   already builds the whole workspace directory.
5. **Clarification knows about the server.** The research and assessment
   prompts state that the 9000 server is a fixed practice and must not be
   asked about; only business interfaces, entry command or ports that cannot
   be inferred remain valid questions.

## Not changed

- `ebx deploy` has no AI step (an earlier `--agent` design was dropped, see
  `2026-09-30-deploy-fixed-pipeline-agent-flag.md`): publishing only reads
  the template directory, so this generator is the one place a description
  turns into template files.
- The Dockerfile SDK-install pattern is the established one from the
  scaffolds and awesome-templates. It relies on `ebx template deploy`
  injecting the SDK wheel, falling back to PyPI as documented there.

## Alternatives considered

- **Put the guide in the workspace as a file for the agent to read** —
  rejected: adds a stray file to the build context and depends on the agent
  choosing to read it. Prompt text is deterministic.
- **Warn instead of fail when `commands.py` is missing** — rejected: a
  Dockerfile-only template is the bug being fixed, and AGENTS.md requires
  capability/resolution problems to fail closed.
- **Make the agent copy `python-hello`** — rejected: examples are not
  packaged in the wheel and the fixture is explicitly not a publishing source.

## SDK wheel in the image

The Dockerfile snippet (`COPY *.whl` + PyPI fallback) assumes the builder puts
a matching SDK wheel into the context. `inject_sdk_wheel` used to only build
from a source checkout, so an installed `ebx` (PyPI or the PyInstaller binary,
which cannot run `pip`) injected nothing. It now downloads the released wheel of
the running version from PyPI (SHA-256 verified, no `pip` needed) and only then
falls back to the Dockerfile's PyPI install. Verified that BuildKit accepts a
`COPY *.whl` that matches nothing, so the fallback path still builds. Covered by
`TestInjectSdkWheel` in `tests/test_api/test_docker_builder.py`.

## Test Strategy

- `tests/test_agent/test_template_guide.py`: keeps the guide honest — every
  imported name is in `easy_sandbox.server.__all__`, every named
  `CapabilityGroup` exists, capability tokens equal `STANDARD_CAPABILITIES`,
  the port equals `SandboxServer.serve`'s default, and the reference
  `commands.py` executes (with `serve` patched), registers its command and
  route, and freezes before serving.
- `tests/test_agent/test_codegen.py`: the prompt demands a server and
  carries the SDK reference; Dockerfile-only, syntax-error, no-server and
  Dockerfile-not-starting-commands.py results are rejected; `files` lists
  deliverables and skips junk.
- `tests/integration/test_nl_template_init_e2e.py`: `template init` /
  `init` / the create switch copy `commands.py` and `README.md` along with
  the Dockerfile and `template.yaml`. These tests also run the *real*
  `generate_template_files` (only the Qwen Code subprocess is faked) to check
  that the prompt reaches the agent with the SDK reference, that a
  Dockerfile-only or no-server result writes nothing locally, that
  `create --yes` hands the whole workspace to `do_deploy` (and never deploys
  a rejected result), and that answers typed at the directory prompt leave
  no stray directories. Mutation-checked: disabling the entrypoint
  validation fails the no-server test.

## Acceptance criteria

- A generated template directory contains `Dockerfile`, `commands.py`,
  `template.yaml` (and README) and can be deployed as-is.
- A generation that yields only a Dockerfile fails with an error naming
  `commands.py`.
- The prompt names `SandboxServer`, `CommandRegistry`, `CapabilityGroup`,
  port 9000, and the Dockerfile `CMD`.

## Files changed

- `src/easy_sandbox/agent/template_guide.py` (new)
- `src/easy_sandbox/agent/codegen.py`, `src/easy_sandbox/agent/clarify.py`
- `src/easy_sandbox/cli/commands/sandbox.py`,
  `src/easy_sandbox/cli/commands/template.py` (help text, local copy)
- Tests above; help goldens (`help-create`, `help-template-init`,
  `help-init-alias`) and `.agents/evidence/cli/help.md`
- Docs (en/zh): `design/cli-design.md`, `reference/cli-reference.md`
- `CHANGELOG.md`
