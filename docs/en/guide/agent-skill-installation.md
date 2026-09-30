# Agent Skill Installation & Distribution

This guide explains how to bring the Easy Sandbox **Agent Skill** (`SKILL.md`, repository root) into your AI coding tool — Qoder, Claude Code, Cursor, Qwen Code, Codex, and any other skills-aware tool — **before** the `ebx` CLI or the Python SDK is installed.

The skill is plain text (YAML frontmatter + Markdown instructions). Installing it adds no runtime to this repository, no registry to the CLI, and nothing that executes on its own. It simply teaches an agent how to operate Easy Sandbox once you are ready.

> **How these commands were verified:** every command, option, and directory in this guide was checked on 2026-09-29 against real `--help` output or vendor documentation (sources at the end). The Agent Skills ecosystem has **no single cross-tool installation command** — where tools differ, this guide lists each verified option instead of inventing one.

---

## 1. Skill first, SDK second

The skill and the `ebx` / SDK installation are deliberately decoupled:

1. **Install the skill** into your tool (this guide). No Python required.
2. **Install the package** when the agent (or you) is ready to actually run sandboxes: `pip install "easy-sandbox[cli]"` — see [section 7](#7-after-the-skill-install-easy-sandbox-configure-credentials-choose-an-interface).
3. **Configure credentials** (`ebx config set sandbox_api_key …`, or AK/SK).
4. **Pick an interface** — MCP for chat agents, CLI for scripts, SDK for Python code (see `SKILL.md` → "Choosing an interface").

The agent reads the skill's instructions and drives steps 2–4 itself; nothing in step 1 depends on them.

---

## 2. Where each tool looks for skills (verified)

A skill is a directory containing a `SKILL.md` file (`easy-sandbox/SKILL.md`). Every tool below loads the same frontmatter format:

| Tool | User-level (all projects) | Project-level (this repository) | Verified source |
|------|---------------------------|---------------------------------|-----------------|
| **Qoder** | `~/.qoder/skills/easy-sandbox/SKILL.md` | `<project>/.qoder/skills/easy-sandbox/SKILL.md` | Qoder docs — [IDE skills](https://docs.qoder.com/zh/extensions/skills), [CLI skills](https://docs.qoder.com/zh/cli/Skills) |
| **Claude Code** | `~/.claude/skills/easy-sandbox/SKILL.md` | `<project>/.claude/skills/easy-sandbox/SKILL.md` | [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) |
| **Cursor** | `~/.cursor/skills/easy-sandbox/SKILL.md` or `~/.agents/skills/easy-sandbox/SKILL.md` | `<project>/.cursor/skills/easy-sandbox/SKILL.md` or `<project>/.agents/skills/easy-sandbox/SKILL.md` | [Cursor skills](https://cursor.com/docs/skills) |
| **Qwen Code** | `~/.qwen/skills/easy-sandbox/SKILL.md` | `<project>/.qwen/skills/easy-sandbox/SKILL.md` | [Qwen Code skills](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/skills.md) |
| **Codex** | `$HOME/.agents/skills/easy-sandbox/SKILL.md` | `<repo-root>/.agents/skills/easy-sandbox/SKILL.md` (scanned from the current directory up to the repo root) | [Codex skills](https://developers.openai.com/codex/skills) |

Notes verified in the same sources:

- **Cursor** additionally loads Claude and Codex skill directories for compatibility: `.claude/skills/`, `.codex/skills/`, `~/.claude/skills/`, `~/.codex/skills/`.
- **Codex** also supports an admin location (`/etc/codex/skills`) and symlinked skill folders. To disable a skill without deleting it, use `[[skills.config]]` in `~/.codex/config.toml`.
- **Qoder CN** uses `~/.qoder-cn/skills/` as its user-level directory (project-level stays `.qoder/skills/`).
- Project-level directories can be committed and shared with your team; user-level directories apply to all of your projects.

If a tool is missing from this table (Gemini CLI, GitHub Copilot, Windsurf, …), consult the tool's own documentation — the formats are compatible, but directory names differ.

---

## 3. Option A — the `skills` CLI (`npx skills add`)

The [`skills` CLI](https://github.com/vercel-labs/skills) (npm package `skills`, v1.7.0 at verification time) installs Agent Skills into the directories from section 2, for many tools at once.

### Preview first (changes nothing on disk)

```bash
npx skills add Easy-Sandbox/easy-sandbox --list
```

### Install

```bash
# One agent, project scope (default), non-interactive:
npx skills add Easy-Sandbox/easy-sandbox --skill easy-sandbox -a qoder -y

# The same skill to several agents at once:
npx skills add Easy-Sandbox/easy-sandbox --skill easy-sandbox \
  -a qoder -a claude-code -a cursor -a qwen-code -y

# User-level instead of project-level:
npx skills add Easy-Sandbox/easy-sandbox --skill easy-sandbox -a qoder -g -y
```

`--agent` names (from `npx skills --help` and the CLI README): `qoder`, `qoder-cn`, `claude-code`, `cursor`, `qwen-code`, `codex`; use `'*'` for every detected agent.

### Options (real `--help` output)

| Option | Meaning |
|--------|---------|
| `-g, --global` | Install to the user-level directory instead of the project |
| `-a, --agent <agents>` | Target specific agents (`'*'` = all) |
| `-s, --skill <skills>` | Install only the named skills (`'*'` = all skills in the repo) |
| `-l, --list` | List available skills without installing |
| `-y, --yes` | Skip all confirmation prompts (CI-friendly) |
| `--copy` | Copy files instead of the default symlink/copy handling |
| `--all` | Shorthand for `--skill '*' --agent '*' -y` |

### Where files land (observed)

Project-scope installs write `<project>/<agent-dir>/skills/easy-sandbox/` (for example `.qoder/skills/easy-sandbox/`) and record the install in a `skills-lock.json` at the project root:

```json
{
  "version": 1,
  "skills": {
    "easy-sandbox": {
      "source": "…",
      "sourceType": "…",
      "computedHash": "…"
    }
  }
}
```

Commit `skills-lock.json` alongside the skill so teammates and CI can restore the exact install with `npx skills experimental_install`.

### Two caveats specific to this repository

- `SKILL.md` lives at the **repository root**, so the skills CLI treats the repository root as the skill folder and snapshots the repository content (a fresh clone without `.git`, roughly 6 MB at the time of writing) into the skill directory. Everything installed is still just files — nothing runs until the agent reads the instructions.
- Installing from a **local path** (`npx skills add ./easy-sandbox`) copies your working tree **as-is, including files ignored by `.gitignore`** — for example a local `.env`. Always install from the published repository form (as shown above), or from a fresh clone that contains no credentials.
- The CLI collects anonymous usage telemetry; disable it with `DISABLE_TELEMETRY=1` or `DO_NOT_TRACK=1` if your environment requires it.

### Update / list / remove

```bash
npx skills list                                   # show installed skills
npx skills update easy-sandbox -y                 # update (auto-detects scope)
npx skills update -g                              # only user-level skills
npx skills remove easy-sandbox                    # remove from project scope
npx skills remove easy-sandbox -g                 # remove from user scope
```

Requires Node.js (`npx`). If you do not want to run Node tooling, use one of the next two options.

---

## 4. Option B — copy or download the single file

`SKILL.md` is one self-contained file; a manual copy is a fully supported install.

1. Open <https://github.com/Easy-Sandbox/easy-sandbox/blob/main/SKILL.md> and use **Raw** / **Download**, then place the file as `easy-sandbox/SKILL.md` under the directory for your tool (section 2). For example:

   ```bash
   mkdir -p ~/.qoder/skills/easy-sandbox
   # save the downloaded file as:
   # ~/.qoder/skills/easy-sandbox/SKILL.md
   ```

2. Or download directly with `curl` — a single file, **never piped into a shell**:

   ```bash
   mkdir -p ~/.claude/skills/easy-sandbox
   curl -fsSL "https://raw.githubusercontent.com/Easy-Sandbox/easy-sandbox/<TAG-OR-COMMIT>/SKILL.md" \
     -o ~/.claude/skills/easy-sandbox/SKILL.md
   ```

   Replace `<TAG-OR-COMMIT>` with a release tag or a full commit SHA. Avoid a moving branch (`main`) when you need a reproducible version.

3. Verify what you downloaded before the agent uses it:

   ```bash
   head -n 3 ~/.claude/skills/easy-sandbox/SKILL.md   # must start with "---"
   grep -m1 '^name: easy-sandbox$' ~/.claude/skills/easy-sandbox/SKILL.md
   shasum -a 256 ~/.claude/skills/easy-sandbox/SKILL.md   # record/compare the hash
   ```

**This project does not recommend `curl … | sh`-style pipelines** — download to a file, inspect it, then install.

### Reloading after a manual install

| Tool | How it picks up the new skill |
|------|-------------------------------|
| Qoder | `/skills reload` in a running CLI session, or restart the IDE |
| Claude Code | Loaded automatically in new sessions (personal/project skill dirs) |
| Cursor | Restart, or **Developer: Reload Window** |
| Qwen Code | Personal/project skill directories are watched; restart in bare mode |
| Codex | Skill changes are detected automatically; restart if an update does not appear |

---

## 5. Option C — `git clone` / sparse checkout

Use Git when you want the file to come from a tracked, verifiable revision.

Full clone (then copy just the skill folder you need):

```bash
git clone https://github.com/Easy-Sandbox/easy-sandbox.git
mkdir -p ~/.qwen/skills/easy-sandbox
cp easy-sandbox/SKILL.md ~/.qwen/skills/easy-sandbox/SKILL.md
```

Sparse checkout (only `SKILL.md`, no other repository content):

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/Easy-Sandbox/easy-sandbox.git
cd easy-sandbox
git sparse-checkout set --no-cone /SKILL.md
```

Pin a version at any point with `git checkout <TAG-OR-COMMIT>`; the sparse working tree follows the checkout, so re-copying `SKILL.md` from a tag gives you that exact revision. Delete the clone directory when you are done.

---

## 6. Marketplace and plugin paths (verified, and what they are not)

Plugin marketplaces distribute **bundles**; Easy Sandbox currently publishes no plugin bundle (the repository contains no `.claude-plugin/` or `.cursor-plugin/` manifest). For a single skill, options A–C above are the working paths. The marketplace mechanics below are documented for completeness and for future plugin packaging:

- **Claude Code** — plugins come from marketplaces (a repository or directory with `.claude-plugin/marketplace.json`). Add one with `/plugin marketplace add <marketplace-repo>` and install with `/plugin install <plugin>@<marketplace>`; skills inside a plugin run as `/plugin-name:skill-name`. Standalone skills do not need a plugin at all — `~/.claude/skills/` and `.claude/skills/` are sufficient.
- **Cursor** — official plugins are installed from **Customize** (marketplace), or distributed through team marketplaces (Teams/Enterprise plans); local plugin development lives in `~/.cursor/plugins/local`. Every marketplace plugin is manually reviewed and must be open source; community plugins and MCP servers are listed on [cursor.directory](https://cursor.directory).
- **Qoder** — the [marketplace](https://qoder.com/en/marketplace) is where you browse and obtain Skills; per Qoder's official documentation, installing a Skill is done with the skills CLI or by placing `SKILL.md` into the skills directories (section 2). There is no verified one-click "install to disk" command to document.
- **Codex** — the built-in `$skill-installer` installs curated skills (for example from `openai/skills`); reusable distribution of your own skills goes through plugins.
- **Qwen Code** — extensions can bundle skills (`skills` field in the extension's `qwen-extension.json`); a plain directory install needs none of that.

If a marketplace listing for Easy Sandbox appears later, prefer it only after checking this repository's release notes.

---

## 7. After the skill: install `easy-sandbox`, configure credentials, choose an interface

The skills guide the agent loads (`SKILL.md`) contains the operational details; the summary:

```bash
# 1. Install the package (CLI + MCP STDIO server)
pip install "easy-sandbox[cli]"

# If pip reports "No matching distribution" (no public PyPI release was
# available at the time of writing — check with the command below), install
# from source instead:
pip index versions easy-sandbox
pip install "easy-sandbox[cli] @ git+https://github.com/Easy-Sandbox/easy-sandbox.git"

# 2. Verify
ebx --version

# 3. Configure credentials (stored in ~/.ebx/.env, masked on display)
ebx config set sandbox_api_key <YOUR_API_KEY>
ebx config set region cn-hangzhou

# 4. Choose an interface
ebx mcp install --target cursor   # MCP for chat agents (or --target claude / vscode)
ebx exec <sandbox-id> "echo hi"   # CLI for scripts
```

- **Credential rules** — never paste real keys into a skill, a repository, a chat message, or a sandbox file; the full rules live in `SKILL.md` → "Credentials and security".
- **Interface selection** — MCP for chat agents, CLI for scripts, SDK for Python orchestration; see `SKILL.md` → "Choosing an interface" and the [MCP Integration guide](mcp-integration.md).
- Authenticating with Alibaba Cloud AK/SK instead of an API key is covered in the [Authentication guide](authentication.md).

---

## 8. Version pinning, updates, uninstall

| Method | Pin a version | Update | Uninstall |
|--------|---------------|--------|-----------|
| `skills` CLI | `skills-lock.json` (records source + content hash; restore with `npx skills experimental_install`) | `npx skills update easy-sandbox -g` / `-p` | `npx skills remove easy-sandbox [-g]` |
| Manual copy | Download from a tag/commit raw URL | Repeat the download, overwrite the file | Delete the `easy-sandbox/` skill folder |
| Git clone / sparse | `git checkout <TAG-OR-COMMIT>` | `git fetch` + checkout, then re-copy | Delete the clone and the installed skill folder |

Uninstall means removing exactly one folder — for example `~/.qoder/skills/easy-sandbox/` — then reloading the tool. Do not delete the shared `skills/` parent directory: other skills live there.

---

## 9. Security notes and third-party boundaries

1. **A skill is instructions for an agent running with your privileges.** Read `SKILL.md` before installing; prefer the official repository URL. The `skills` CLI itself prints "Review skills before use; they run with full agent permissions."
2. **Local-path installs copy ignored files** (`.env`, caches). Never install from a local working tree that contains credentials (section 3).
3. **Credential hygiene:** the skill never asks you to print keys. It instructs agents to use masked commands (`ebx config get sandbox_api_key`) and to store credentials in `~/.ebx/.env`. Do not commit `~/.ebx/.env`, and rotate any key that has appeared in output or a transcript.
4. **No `curl | sh`:** download single files to disk, pin a tag/commit, verify the frontmatter and hash before use (section 4).
5. **Third-party code boundary:** marketplace plugins are third-party code with different review levels (Claude: official / community / third-party marketplace tiers; Cursor: every marketplace plugin is manually reviewed and must be open source; `cursor.directory` and registry listings are community). A skill folder may contain `scripts/` that the agent can run — treat those as code you are choosing to execute.

---

## Sources (verified 2026-09-29)

- `skills` CLI — [vercel-labs/skills](https://github.com/vercel-labs/skills) README and real `npx skills --help` output (npm package `skills@1.7.0`)
- Qoder — [Skills (IDE)](https://docs.qoder.com/zh/extensions/skills), [Skills (CLI)](https://docs.qoder.com/zh/cli/Skills)
- Claude Code — [Skills](https://docs.claude.com/en/docs/claude-code/skills), [Plugins](https://docs.claude.com/en/docs/claude-code/plugins)
- Cursor — [Agent Skills](https://cursor.com/docs/skills), [Plugins](https://cursor.com/docs/plugins)
- Qwen Code — [Agent Skills](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/skills.md)
- Codex — [Build skills](https://developers.openai.com/codex/skills)
- PyPI status — `pip index versions easy-sandbox` returned no matching distribution on 2026-09-29; the source-install command was dry-run verified (`pip install --dry-run … "easy-sandbox[cli] @ git+https://github.com/Easy-Sandbox/easy-sandbox.git"`)
