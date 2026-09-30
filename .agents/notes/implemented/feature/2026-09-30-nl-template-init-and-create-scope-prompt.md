# Decision: Natural-language template init, and a create-path switch to it

Status: implemented
Implemented: 2026-09-30

## Problem

`ebx create "DESCRIPTION"` (including the `sandbox create` shortcut) generates a
template and then builds, pushes, deploys, and creates a sandbox. That full
pipeline is easy to start by accident when the user only wanted the template
files. `ebx template init` already scaffolds a local project and stops, but it
only accepts a directory or a built-in case — it cannot take the same
natural-language description.

## Decision

1. **Interactive scope check on natural-language create.** Before install,
   clarification, or generation, an interactive terminal (not `--yes`, not
   `--json`) is shown the four steps — generate, build and push, deploy,
   create a sandbox — and asked:

   `Switch to template init and only create the local template? [y/N]`

   The default is no, so Enter continues the full create. Yes runs the
   template-only generator and returns before `Sandbox.create`. `--yes` and
   `--json` skip the question and keep the full pipeline. A non-interactive
   shell prints one reminder (`Template only: ebx template init "..."`) and
   continues; the existing build confirmation still applies.

2. **`ebx template init "DESCRIPTION"` generates files and stops.** A DIRECTORY
   argument that contains whitespace or CJK text is a description. A path
   token (`my-app`, `./my app`, `.`) stays a directory, so existing scaffold
   invocations are unchanged. The description cannot be combined with
   `--template`/`-t` or `--from`.

   Generation reuses the create-path clarification and codegen
   (`_generate_template_workspace`). The files are copied to `./<name>/`
   (`--name`, otherwise the generated template name). `--force` overwrites.
   `--yes`/`-y` skips clarification and is required for non-interactive
   generation when the description is incomplete. Nothing is built, pushed,
   deployed, or launched.

   `ebx init "DESCRIPTION"` is the same command object.

3. **Output directory.** Files are never written loose into the current
   directory. Both init forms create a subdirectory of the working
   directory unless a scaffold invocation passes an explicit path.

   | Invocation | Where the files go |
   | --- | --- |
   | `ebx template init -t python` | `./python/` |
   | `ebx template init -t python --name myapp` | `./myapp/` |
   | `ebx template init -t python ./my-template` | `./my-template/` (the given directory) |
   | `ebx template init --from owner/repo` | `./<template-name>/` |
   | `ebx template init --from owner/repo ./dest` | `./dest/` |
   | `ebx template init "DESCRIPTION"` | `./<generated-name>/` under the current directory |
   | `ebx template init --name myapp "DESCRIPTION"` | `./myapp/` |

   Natural-language init has one positional, and that positional is the
   description, so a second path is a usage error. `--name` chooses the
   subdirectory. `create --dir` selects the parent of the AI workspace
   used by the full create pipeline (`~/.ebx/generated` when omitted).
   It does not apply after the switch to template init: the warning is
   `--dir is ignored for template-only generation; the files are written
   to ./<name>/`.

   **No stray directories.** `_resolve_output_dir` only validates the
   `--dir` / prompt answer (an existing file, or a parent that cannot be
   written, is a usage error); it never creates the directory. The
   generation step (`prepare_workdir`) creates it, so an answer typed at the
   wrong prompt (for example a clarification answer such as `pandas`, `y` or
   `2 CPU 4 GB`) or a run cancelled before generation leaves nothing behind.
   `tests/test_cli/test_create_nl.py` also runs every test in its own
   working directory so scripted input can never write into the checkout.

## API Design

```text
ebx create "DESCRIPTION"              # interactive: ask, default = full create
ebx create -y "DESCRIPTION"           # full pipeline, no switch question
ebx template init "DESCRIPTION"       # the generated template in ./<name>/
ebx template init -y "DESCRIPTION"    # same, skip clarification
ebx template init --name myapp "DESCRIPTION"   # ./myapp/
ebx template init -t python                 # ./python/  (cwd subdirectory)
ebx template init -t python ./my-app        # explicit directory
ebx template init "DESCRIPTION" ./elsewhere # rejected: one positional only
```

CLI-only. No SDK signature change.

`.agents/design/` is a frozen historical snapshot and is not extended.
This note is the engineering design record. The public write-up is
`docs/en/design/cli-design.md` and `docs/zh/design/cli-design.md`.

## Alternatives considered

- **Replace the existing build confirmation with the switch question** —
  rejected: that confirmation is the last gate before cloud build/push, and
  its yes/no answers are already part of the create contract. The new question
  is an earlier scope choice with the opposite default (continue create).
- **Treat every `template init` positional as a description** — rejected: the
  positional is already a directory (`ebx template init ./my-app`).
- **Ask the switch question only after generation** — rejected: the user
  should see the build/push/sandbox cost before the agent runs. Both answers
  still generate; only the yes answer skips build, push, deploy, and create.

## Dependencies

- `easy_sandbox.cli.commands.sandbox` clarification + codegen workspace
- `easy_sandbox.cli.commands.template.init` and `_print_init_summary`
- Coding-agent backend (Qwen Code) for generation; no new backend method

## Test Strategy

- `tests/test_cli/test_create_nl.py`: TTY yes writes `./<template>/` and does
  not deploy or call `Sandbox.create`; `--yes` still deploys and does not
  copy locally; non-TTY reminder includes `ebx template init`; existing TTY
  scripts answer `n` to the new question first.
- `tests/test_cli/test_create_nl.py`: `template init -y "DESCRIPTION"` writes
  files, honours `--name` and `--force`, and does not deploy; description plus
  `-t` or `--from` is a usage error; `ebx init` accepts a CJK description.
- `tests/test_cli/test_template_commands.py`: `_is_nl_description` treats
  sentences and CJK as descriptions and path tokens as directories.
- `tests/integration/test_nl_template_init_e2e.py` (marked `integration`,
  offline): the full command tree.
  - scaffold init writes the given directory and, with no directory,
    a subdirectory of the working directory;
  - `template init -y "DESCRIPTION"` and `init -y "DESCRIPTION"` write
    `./<name>/` and do not deploy or create a sandbox;
  - a second positional path is rejected;
  - interactive `create` answering yes stops after the local template;
  - `create -y` and `sandbox create -y` deploy and create a sandbox;
  - a non-interactive `create` prints the init reminder and does not
    launch a sandbox.

## Acceptance criteria

- Interactive `ebx create "DESCRIPTION"` asks whether to switch to template
  init; yes leaves a local template and does not build or create a sandbox;
  no (the default) keeps the previous full pipeline.
- `--yes` on create does not ask and still builds, deploys, and creates.
- `ebx template init "DESCRIPTION"` and `ebx init "DESCRIPTION"` generate
  the template files only (Dockerfile, `commands.py`, `template.yaml`, README;
  see `2026-09-30-nl-template-server-entrypoint.md`).
- `ebx template init -t python ./my-app` writes that directory. Omitting
  the directory creates `./<name>/` under the working directory, not a
  loose set of files in the working directory itself.
- Natural-language init cannot take a second path argument. `--name`
  selects the subdirectory under the working directory.
- EN/ZH design, reference, and tutorial docs describe both entry points.

## Files changed

- `src/easy_sandbox/cli/commands/sandbox.py`
- `src/easy_sandbox/cli/commands/template.py`
- `tests/test_cli/test_create_nl.py`
- `tests/test_cli/test_template_commands.py`
- `tests/integration/test_nl_template_init_e2e.py`
- Docs (en/zh): `design/cli-design.md`, `reference/cli-reference.md`,
  `guide/cli-tutorial.md`
- `CHANGELOG.md`
