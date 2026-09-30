# Agent Skill 安装与分发

本指南说明如何把 Easy Sandbox 的 **Agent Skill**（仓库根目录的 `SKILL.md`）引入你的 AI 编码工具——Qoder、Claude Code、Cursor、Qwen Code、Codex 以及其他支持 Skills 的工具——并且**在安装 `ebx` CLI 或 Python SDK 之前**即可完成。

该 Skill 是纯文本（YAML frontmatter + Markdown 指令）。安装它不会给本仓库引入任何运行时，不会给 CLI 增加注册表，也不含任何自行执行的代码；它只是教会 Agent 在你准备好之后如何操作 Easy Sandbox。

> **命令核验说明：** 本指南中的每条命令、选项与目录均在 2026-09-29 对照真实 `--help` 输出或工具官方文档逐项核实（来源见文末）。Agent Skills 生态**不存在跨工具的统一安装命令**——各工具做法不同的地方，本指南分别列出经核验的选项，而不是虚构一条"万能命令"。

---

## 1. 先装 Skill，后装 SDK

Skill 与 `ebx` / SDK 的安装刻意解耦：

1. **先安装 Skill**（本指南），无需 Python 环境。
2. 当 Agent（或你）准备真正运行沙箱时，**再安装软件包**：`pip install "easy-sandbox[cli]"`——见第 7 节。
3. **配置凭证**（`ebx config set sandbox_api_key …`，或 AK/SK）。
4. **选择接口**——对话类 Agent 用 MCP，脚本用 CLI，Python 代码用 SDK（见 `SKILL.md` 的 "Choosing an interface"）。

Agent 读取 Skill 指令后会自行完成第 2–4 步；第 1 步不依赖它们中的任何一步。

---

## 2. 各工具查找 Skill 的目录（已核实）

一个 Skill 就是一个包含 `SKILL.md` 的目录（`easy-sandbox/SKILL.md`）。下列工具加载的 frontmatter 格式完全相同：

| 工具 | 用户级（所有项目） | 项目级（当前仓库） | 核实来源 |
|------|--------------------|--------------------|----------|
| **Qoder** | `~/.qoder/skills/easy-sandbox/SKILL.md` | `<project>/.qoder/skills/easy-sandbox/SKILL.md` | Qoder 文档——[IDE Skills](https://docs.qoder.com/zh/extensions/skills)、[CLI Skills](https://docs.qoder.com/zh/cli/Skills) |
| **Claude Code** | `~/.claude/skills/easy-sandbox/SKILL.md` | `<project>/.claude/skills/easy-sandbox/SKILL.md` | [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) |
| **Cursor** | `~/.cursor/skills/easy-sandbox/SKILL.md` 或 `~/.agents/skills/easy-sandbox/SKILL.md` | `<project>/.cursor/skills/easy-sandbox/SKILL.md` 或 `<project>/.agents/skills/easy-sandbox/SKILL.md` | [Cursor skills](https://cursor.com/docs/skills) |
| **Qwen Code** | `~/.qwen/skills/easy-sandbox/SKILL.md` | `<project>/.qwen/skills/easy-sandbox/SKILL.md` | [Qwen Code skills](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/skills.md) |
| **Codex** | `$HOME/.agents/skills/easy-sandbox/SKILL.md` | `<repo-root>/.agents/skills/easy-sandbox/SKILL.md`（从当前目录向上扫描至仓库根） | [Codex skills](https://developers.openai.com/codex/skills) |

同一批来源中核实到的补充说明：

- **Cursor** 为兼容起见还会加载 Claude 与 Codex 的技能目录：`.claude/skills/`、`.codex/skills/`、`~/.claude/skills/`、`~/.codex/skills/`。
- **Codex** 还支持管理员级目录（`/etc/codex/skills`）和符号链接形式的技能目录；要停用某个技能而不删除文件，可在 `~/.codex/config.toml` 中用 `[[skills.config]]` 配置。
- **Qoder CN** 的用户级目录为 `~/.qoder-cn/skills/`（项目级仍为 `.qoder/skills/`）。
- 项目级目录可以随 Git 提交、与团队共享；用户级目录对你本机所有项目生效。

如果这里没有列出你使用的工具（如 Gemini CLI、GitHub Copilot、Windsurf……），请查阅该工具自身文档——格式兼容，但目录名不同。

---

## 3. 方式 A —— `skills` CLI（`npx skills add`）

[`skills` CLI](https://github.com/vercel-labs/skills)（npm 包 `skills`，核验时为 v1.7.0）可把 Agent Skills 安装到第 2 节所列目录，并支持一次安装到多个工具。

### 先预览（不写盘）

```bash
npx skills add Easy-Sandbox/easy-sandbox --list
```

### 安装

```bash
# 单个工具、项目级（默认）、非交互：
npx skills add Easy-Sandbox/easy-sandbox --skill easy-sandbox -a qoder -y

# 一次安装到多个工具：
npx skills add Easy-Sandbox/easy-sandbox --skill easy-sandbox \
  -a qoder -a claude-code -a cursor -a qwen-code -y

# 安装到用户级（对全部项目生效）：
npx skills add Easy-Sandbox/easy-sandbox --skill easy-sandbox -a qoder -g -y
```

`--agent` 取值（来自 `npx skills --help` 与 CLI README）：`qoder`、`qoder-cn`、`claude-code`、`cursor`、`qwen-code`、`codex`；`'*'` 表示全部已检测到的工具。

### 选项（真实 `--help` 输出）

| 选项 | 含义 |
|------|------|
| `-g, --global` | 安装到用户级目录而非项目级 |
| `-a, --agent <agents>` | 指定目标工具（`'*'` = 全部） |
| `-s, --skill <skills>` | 只安装指定技能（`'*'` = 仓库内全部技能） |
| `-l, --list` | 仅列出可用技能，不安装 |
| `-y, --yes` | 跳过全部确认提示（适合 CI） |
| `--copy` | 使用复制而非默认的链接/复制策略 |
| `--all` | 等价于 `--skill '*' --agent '*' -y` |

### 文件落在哪里（实测）

项目级安装写入 `<project>/<agent-dir>/skills/easy-sandbox/`（例如 `.qoder/skills/easy-sandbox/`），并在项目根生成 `skills-lock.json` 记录本次安装：

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

把 `skills-lock.json` 与技能一起提交，团队成员与 CI 可用 `npx skills experimental_install` 还原完全一致的安装。

### 本仓库特有的两个注意事项

- `SKILL.md` 位于**仓库根目录**，因此 skills CLI 会把整个仓库根当作技能目录，将仓库内容快照（不含 `.git` 的全新克隆，撰写时约 6 MB）复制进技能目录。装进去的仍然只是文件——在 Agent 读取指令之前不会执行任何东西。
- 从**本地路径**安装（`npx skills add ./easy-sandbox`）会**原样复制你的工作区，包括被 `.gitignore` 忽略的文件**——例如本地 `.env`。请始终使用上文给出的已发布仓库形式安装，或在一个不含凭证的全新克隆中执行。
- 该 CLI 默认收集匿名遥测；如需关闭，设置 `DISABLE_TELEMETRY=1` 或 `DO_NOT_TRACK=1`。

### 更新 / 查看 / 卸载

```bash
npx skills list                                   # 查看已安装的技能
npx skills update easy-sandbox -y                 # 更新（自动识别作用域）
npx skills update -g                              # 只更新用户级技能
npx skills remove easy-sandbox                    # 从项目级移除
npx skills remove easy-sandbox -g                 # 从用户级移除
```

需要 Node.js（`npx`）。如果你不想使用 Node 工具链，请用下面两种方式之一。

---

## 4. 方式 B —— 复制或下载单个文件

`SKILL.md` 是自包含的单文件，手工复制是受支持的完整安装方式。

1. 打开 <https://github.com/Easy-Sandbox/easy-sandbox/blob/main/SKILL.md>，使用 **Raw** / **Download** 下载，然后按下表把你所用工具的目录放成 `easy-sandbox/SKILL.md`（见第 2 节）。例如：

   ```bash
   mkdir -p ~/.qoder/skills/easy-sandbox
   # 将下载的文件保存为：
   # ~/.qoder/skills/easy-sandbox/SKILL.md
   ```

2. 也可以用 `curl` 直接下载——单个文件，**绝不通过管道交给 shell 执行**：

   ```bash
   mkdir -p ~/.claude/skills/easy-sandbox
   curl -fsSL "https://raw.githubusercontent.com/Easy-Sandbox/easy-sandbox/<TAG-OR-COMMIT>/SKILL.md" \
     -o ~/.claude/skills/easy-sandbox/SKILL.md
   ```

   把 `<TAG-OR-COMMIT>` 替换为发布 tag 或完整 commit SHA。需要可复现版本时，不要使用会移动的分支（`main`）。

3. 在交给 Agent 使用前先核验下载内容：

   ```bash
   head -n 3 ~/.claude/skills/easy-sandbox/SKILL.md   # 必须以 "---" 开头
   grep -m1 '^name: easy-sandbox$' ~/.claude/skills/easy-sandbox/SKILL.md
   shasum -a 256 ~/.claude/skills/easy-sandbox/SKILL.md   # 记录/比对哈希
   ```

**本项目不推荐 `curl … | sh` 之类的管道式安装**——请先下载到文件、检查内容，再安装。

### 手工安装后的加载时机

| 工具 | 如何感知新技能 |
|------|----------------|
| Qoder | 运行中的 CLI 会话执行 `/skills reload`，或重启 IDE |
| Claude Code | 新会话自动加载（个人/项目技能目录） |
| Cursor | 重启，或 **Developer: Reload Window** |
| Qwen Code | 会自动监听个人/项目技能目录；bare 模式下需重启 |
| Codex | 自动检测技能变更；若未出现更新则重启 |

---

## 5. 方式 C —— `git clone` / 稀疏检出

当你希望文件来自可追踪、可校验的版本时，使用 Git。

完整克隆（然后只复制需要的技能目录）：

```bash
git clone https://github.com/Easy-Sandbox/easy-sandbox.git
mkdir -p ~/.qwen/skills/easy-sandbox
cp easy-sandbox/SKILL.md ~/.qwen/skills/easy-sandbox/SKILL.md
```

稀疏检出（只要 `SKILL.md`，不拉取仓库其他内容）：

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/Easy-Sandbox/easy-sandbox.git
cd easy-sandbox
git sparse-checkout set --no-cone /SKILL.md
```

随时可用 `git checkout <TAG-OR-COMMIT>` 固定版本；稀疏工作区会跟随检出，从 tag 重新复制 `SKILL.md` 即可得到该精确版本。完成后删除克隆目录即可。

---

## 6. Marketplace 与插件路径（已核实，以及它们不是什么）

插件市场分发的是**打包产物**；Easy Sandbox 目前未发布任何插件包（仓库中没有 `.claude-plugin/` 或 `.cursor-plugin/` manifest）。对单个 Skill 而言，上述方式 A–C 才是当前可用路径。以下机制仅出于完整性与将来打包时的参考而记录（均经官方文档核实）：

- **Claude Code** —— 插件来自市场（含 `.claude-plugin/marketplace.json` 的仓库或目录）。用 `/plugin marketplace add <marketplace-repo>` 添加市场，再用 `/plugin install <plugin>@<marketplace>` 安装；插件内的技能以 `/plugin-name:skill-name` 形式运行。独立技能根本不需要插件——`~/.claude/skills/` 与 `.claude/skills/` 已足够。
- **Cursor** —— 官方插件从 **Customize**（市场）安装，或通过团队市场分发（Teams/Enterprise 套餐）；本地插件开发目录为 `~/.cursor/plugins/local`。市场上的每个插件都经过人工审核且必须开源；社区插件与 MCP 服务器见 [cursor.directory](https://cursor.directory)。
- **Qoder** —— [Marketplace](https://qoder.com/en/marketplace) 用于浏览与获取 Skill；按 Qoder 官方文档，安装 Skill 的方式是 skills CLI 或把 `SKILL.md` 放入技能目录（见第 2 节）。目前没有经核实的"一键写入本地目录"命令可供文档化。
- **Codex** —— 内置的 `$skill-installer` 可安装精选技能（例如来自 `openai/skills`）；自有技能的可复用分发走插件。
- **Qwen Code** —— 扩展可以打包技能（扩展的 `qwen-extension.json` 中的 `skills` 字段）；直接用目录安装则无需涉及这些。

如果将来出现 Easy Sandbox 的市场上架，请先核对该仓库的 release notes 再选用。

---

## 7. 装完 Skill 之后：安装 easy-sandbox、配置凭证、选择接口

Agent 加载的技能指南（`SKILL.md`）中有完整操作细节；要点如下：

```bash
# 1. 安装软件包（CLI + MCP STDIO 服务）
pip install "easy-sandbox[cli]"

# 若 pip 提示 "No matching distribution"（撰写时 PyPI 尚无公开发布，
# 可用下面的命令核实），改用源码安装：
pip index versions easy-sandbox
pip install "easy-sandbox[cli] @ git+https://github.com/Easy-Sandbox/easy-sandbox.git"

# 2. 验证
ebx --version

# 3. 配置凭证（存储于 ~/.ebx/.env，展示时自动打码）
ebx config set sandbox_api_key <YOUR_API_KEY>
ebx config set region cn-hangzhou

# 4. 选择接口
ebx mcp install --target cursor   # 对话类 Agent 用 MCP（或 --target claude / vscode）
ebx exec <sandbox-id> "echo hi"   # 脚本用 CLI
```

- **凭证规则**——绝不把真实密钥写进 Skill、仓库、聊天消息或沙箱文件；完整规则见 `SKILL.md` 的 "Credentials and security"。
- **接口选择**——对话类 Agent 用 MCP，脚本用 CLI，Python 编排用 SDK；见 `SKILL.md` 的 "Choosing an interface" 与 [MCP 集成指南](mcp-integration.md)。
- 使用阿里云 AK/SK 替代 API Key 的认证方式见[认证配置指南](authentication.md)。

---

## 8. 版本锁定、升级与卸载

| 方式 | 锁定版本 | 升级 | 卸载 |
|------|----------|------|------|
| `skills` CLI | `skills-lock.json`（记录来源 + 内容哈希；用 `npx skills experimental_install` 还原） | `npx skills update easy-sandbox -g` / `-p` | `npx skills remove easy-sandbox [-g]` |
| 手工复制 | 从 tag/commit 的 raw URL 下载 | 重新下载并覆盖文件 | 删除 `easy-sandbox/` 技能目录 |
| Git 克隆 / 稀疏检出 | `git checkout <TAG-OR-COMMIT>` | `git fetch` + checkout 后重新复制 | 删除克隆目录与已安装的技能目录 |

卸载意味着只删除一个目录——例如 `~/.qoder/skills/easy-sandbox/`——然后重新加载工具。不要删除共享的 `skills/` 父目录：其他技能也在那里。

---

## 9. 安全提示与第三方代码边界

1. **Skill 是给以你的权限运行的 Agent 的指令。** 安装前先阅读 `SKILL.md`；优先从官方仓库安装。`skills` CLI 自身也会提示 "Review skills before use; they run with full agent permissions."
2. **本地路径安装会复制被忽略的文件**（`.env`、缓存）。绝不要在含凭证的本地工作区执行本地路径安装（见第 3 节）。
3. **凭证卫生：**该 Skill 从不要求你打印密钥；它指导 Agent 使用打码命令（`ebx config get sandbox_api_key`），并把凭证保存在 `~/.ebx/.env`。不要提交 `~/.ebx/.env`；任何已经出现在输出或会话记录中的密钥都必须立即轮换。
4. **不要 `curl | sh`：**单文件下载到磁盘，固定 tag/commit，使用前核验 frontmatter 与哈希（见第 4 节）。
5. **第三方代码边界：**市场插件是审查等级各异的第三方代码（Claude：官方 / 社区 / 第三方市场分级；Cursor：市场插件均经人工审核且必须开源；`cursor.directory` 与注册表列表属社区来源）。技能目录里可能包含 Agent 可执行的 `scripts/`——请把它们当作你选择执行的代码对待。

---

## 来源（2026-09-29 核验）

- `skills` CLI——[vercel-labs/skills](https://github.com/vercel-labs/skills) README 与真实 `npx skills --help` 输出（npm 包 `skills@1.7.0`）
- Qoder——[Skills（IDE）](https://docs.qoder.com/zh/extensions/skills)、[Skills（CLI）](https://docs.qoder.com/zh/cli/Skills)
- Claude Code——[Skills](https://docs.claude.com/en/docs/claude-code/skills)、[Plugins](https://docs.claude.com/en/docs/claude-code/plugins)
- Cursor——[Agent Skills](https://cursor.com/docs/skills)、[Plugins](https://cursor.com/docs/plugins)
- Qwen Code——[Agent Skills](https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/skills.md)
- Codex——[Build skills](https://developers.openai.com/codex/skills)
- PyPI 状态——`pip index versions easy-sandbox` 在 2026-09-29 无匹配分发；源码安装命令已通过 dry-run 验证（`pip install --dry-run … "easy-sandbox[cli] @ git+https://github.com/Easy-Sandbox/easy-sandbox.git"`）
