# qwencli 融入状态 + .agents/design 文档沉淀审计

日期: 2026-09-04 | 任务: #104 | 性质: 只读审计，未修改任何产品代码

---

## Q2: qwencli 是否已融入本项目？

### 2.1 全局搜索 "qwen" 命中盘点

| 位置 | 命中内容 | 性质 |
|------|---------|------|
| `examples/templates/qwen-code/sandbox-template.yaml` | 模板名 `qwen-code`，tags 含 `qwen` | 模板定义 |
| `examples/templates/qwen-code/Dockerfile` | 安装 Python 3.11 + Node.js 22 + dashscope/openai/httpx/rich | **无 qwen-cli 安装** |
| `examples/templates/qwen-code/README.md` | "通义千问编码 Agent 运行环境" | 文档 |
| `src/serverless_sandbox/agent/infer.py:144-148` | `TemplateProfile(name="qwen-code", keywords=["qwen", ...])` | 推断引擎注册 |
| `docs/design/built-in-agents.md:59,63,99,101,108,212-229` | 描述 `qwen-cli browse` / `qwen-cli analyze` 映射 + `_build_command` 伪代码 | **设计愿景（未实现）** |
| `docs/DESIGN.md:49,235,626,636,671,1526-1527,1891,1904-1906` | "沙箱内置 AI CLI 工具（Codex / Qwen CLI）" | 设计愿景 |
| `docs/design/cli-design.md:511,524` | `llm_model` 默认 `qwen-plus` | LLM 推断配置 |
| `src/serverless_sandbox/agent/builtin.py` | **零 qwen 命中**；`browse()` 用 `curl -sL`，`analyze()` 用 `python -m py_compile` | 实际代码 |
| `src/serverless_sandbox/agent/tools.py` (MCP TOOL_SCHEMAS) | **零 qwen 命中**；7 个工具均为通用沙箱操作 | MCP server |
| `src/serverless_sandbox/cli/commands/` | **零 qwen 命中** | CLI 命令 |
| `src/serverless_sandbox/integrations/` | **零 qwen 命中** | Agent 框架集成 |

### 2.2 会话转录搜索

```
$ rg -i "qwen" /Users/anycodes/.qoder/cache/projects/chat-1-2d92c1f/conversation-history/628457aa/628457aa.jsonl
(零命中)

$ rg -i "qwen" .../6e51593d/6e51593d.jsonl
(零命中)

$ rg -i "qwen" .../9620c890/9620c890.jsonl
(零命中)
```

**结论：三个会话转录中 "qwen" 零命中。"融入 qwencli" 从未在可追溯的会话中被用户明确提出或决策。**

### 2.3 设计文档 vs 实际代码的断层

`docs/design/built-in-agents.md:212-229` 描述了一个 `_build_command` 方法：

```python
def _build_command(self, action, task, context=None):
    template = self._sandbox._template_name
    if template.startswith("codex"):
        return f"codex {safe_task}"
    elif template.startswith("qwen-"):
        return f"qwen-cli {action} {safe_task}"   # ← 设计愿景
```

但 `src/serverless_sandbox/agent/builtin.py` 的实际代码（131 行全文）：
- **没有** `_build_command` 方法
- **没有** `_template_name` 属性引用
- **没有** 任何 `qwen-cli` 字符串
- `browse()` 实现为 `commands.run(f"curl -sL {url}")`（`:74`）
- `analyze()` 实现为 `commands.run("python -m py_compile ...")`（`:91`）
- `shell()` 实现为直接 `commands.run(command)`（`:62`）

同时，`examples/templates/qwen-code/Dockerfile`（52 行全文）：
- 安装的是 `dashscope`、`openai`、`httpx`、`rich`（Python 包）
- **没有** `npm install -g qwen-cli` 或任何 qwen-cli 二进制安装
- 模板的 `custom_commands` 只有 `run: cmd: "python3 {script}"`（通用 Python 执行器）

### 2.4 诚实结论

| 维度 | 判定 |
|------|------|
| **(a) 是否曾被要求 + 范围原文** | **从未被明确要求。** 三个会话转录中 "qwen"/"qwencli" 零命中。设计文档 `built-in-agents.md` 和 `DESIGN.md` 描述了 "Qwen CLI" 愿景，但这是项目自身的设计规划，不是用户在会话中提出的需求。 |
| **(b) 当前融入状态** | **完全没有融入。** 具体证据：① `builtin.py` 无 qwen-cli 映射代码；② qwen-code 模板 Dockerfile 未安装 qwen-cli 工具；③ MCP TOOL_SCHEMAS 无 qwen 相关工具；④ CLI commands 无 qwen 集成；⑤ integrations/ 无 qwen 适配。存在的只是：一个名为 `qwen-code` 的模板骨架（Python 环境 + dashscope SDK）+ 设计文档中的愿景描述。 |
| **(c) 最小融入路径** | 见下方。 |

### 2.5 最小融入路径（若决定做）

| 步 | 改动 | 工作量 |
|----|------|--------|
| 1 | 确认 "qwencli" 到底是什么：是 `npm install -g @anthropic/qwen-cli`？是 DashScope CLI？还是自研工具？**目前项目中无任何 qwen-cli 二进制的来源定义** | 需求澄清 |
| 2 | 在 `examples/templates/qwen-code/Dockerfile` 中安装该 CLI 工具 | XS |
| 3 | 在 `builtin.py` 中实现 `_build_command` 映射（按设计文档 `built-in-agents.md:212-229`） | S |
| 4 | 在 `sandbox-template.yaml` 的 `custom_commands` 中注册 qwen-cli 命令 | XS |
| 5 | （可选）在 MCP TOOL_SCHEMAS 中暴露 qwen-cli 工具 | S |

**前置阻塞**：步骤 1 是硬阻塞 —— 项目中从未定义 "qwen-cli" 是什么工具、从哪安装、其命令接口是什么。设计文档只写了 `qwen-cli browse` / `qwen-cli analyze` 但没有给出工具来源。

---

## Q3: 近期设计决策是否都沉淀进 .agents / design 文档？

### 3.0 .agents/notes/ 目录结构盘点

```
.agents/notes/
├── implemented/
│   ├── architecture/ (11 files)
│   │   ├── 2026-09-02-agent-as-cli-wrapper.md
│   │   ├── 2026-09-02-dual-auth-mode.md
│   │   ├── 2026-09-02-sbox-cli-naming.md
│   │   ├── 2026-09-02-self-implement-e2b-protocol.md
│   │   ├── 2026-09-02-session-pluggable-storage.md
│   │   ├── 2026-09-02-snapshot-hibernate-deferred.md
│   │   ├── 2026-09-03-capability-model.md
│   │   ├── 2026-09-03-cli-run-vs-exec.md
│   │   ├── 2026-09-03-command-source-resolution.md
│   │   ├── 2026-09-03-no-backward-compat-capability.md
│   │   └── 2026-09-03-sdk-capability-surface.md
│   ├── feature/ (2 files + .gitkeep)
│   │   ├── 2026-09-03-custom-commands-schema.md
│   │   └── 2026-09-03-minimal-template-repo.md
│   └── process/ (.gitkeep only)
├── proposed/
│   ├── architecture/ (.gitkeep only — 空)
│   ├── feature/ (15 files — 模块级实现提案)
│   └── process/ (1 file)
│       └── 2026-09-03-release-publish-flow.md
└── rejected/ (1 file + .gitkeep)
    └── 2026-09-03-capability-model-alternatives.md
```

### 3.1 逐项核对

#### 决策 1: envd 两层容器服务模型

**内容**：平台注入 envd + 用户 server 基于 envd 而非替代；SDK 不 ship 兜底 in-container agent

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **missing** — 全量 grep `envd` 在 .agents/notes/** 只命中 5 个文件（`transport-http.md`、`transport-streaming.md`、`transport-auth.md`、`2026-09-02-dual-auth-mode.md`、`2026-09-02-self-implement-e2b-protocol.md`），**全部只讨论客户端如何调 envd，无一讨论 envd 从哪来、两层模型、SDK 不 ship 兜底 agent** |
| docs/design/ | **partial** — `architecture.md:56-57` 区分了 Platform API 与 envd API（方向正确），但没有讨论 envd 来源、builder/direct 模式、用户 server 与 envd 的关系 |
| 证据文件 | **documented** — `docs/evidence/research/2026-09-04-container-serve-boundary.md` §2-§3, §6.7 完整覆盖 |
| **总判定** | **missing**（.agents/notes 中无 ADR；证据文件不是 ADR） |

#### 决策 2: @sandbox.register 源码投递执行 + 函数名→命令名 + 参数类型限 str/int/float/bool

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **missing** — 没有任何 ADR 讨论 `@sandbox.register`。`sdk-capability-surface.md` 讨论了 `sandbox.run("name", **args)` 但明确否决了 `__getattr__` 魔法属性，没有讨论装饰器注册 |
| docs/design/ | **missing** — `sdk-api-design.md` 提到了 `sandbox.run` 但没有 `@sandbox.register` |
| 证据文件 | **documented** — `container-serve-boundary.md` §5.3, §6.1, §6.3 完整讨论了源码投递机制、函数名→命令名映射、参数类型限制（str/int/float/bool，排除 dict/list/file） |
| **总判定** | **missing**（这是一个**尚未实现的设计提案**，只在证据文件中被分析，没有 ADR） |

#### 决策 3: Discovery API 设计

**内容**：Sandbox.list_commands 现状、Layer1 本地静态发现 vs Layer2 server 远程发现、鉴权应复用 AuthProvider.get_headers/EnvdTokenManager.get_headers 而非 api/network.py 的 get_access_headers

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **partial** — `sdk-capability-surface.md:13` 定义了 "Discovery API"（`sandbox.capabilities` + `sandbox.list_commands()`），`command-source-resolution.md` 讨论了两层解析（本地缓存 + 在线元数据）。但**没有讨论**：Layer1/Layer2 的区分、鉴权复用（AuthProvider vs EnvdTokenManager vs network.get_access_headers）、`get_access_headers` 是错的复用对象 |
| docs/design/ | **partial** — `sdk-api-design.md:526,618-626` 提到了 `list_commands()` |
| 证据文件 | **documented** — `container-serve-boundary.md` §6.4 完整讨论了三层子问题 |
| **总判定** | **partial**（基本 Discovery API 有 ADR，但鉴权复用分析、Layer1/Layer2 区分、get_access_headers 陷阱没有沉淀） |

#### 决策 4: 单仓库单发行 + [cli] extra 决策

**内容**：不拆两个库、暂不做二进制

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **missing** — 没有任何 ADR 讨论打包结构。`proposed/process/2026-09-03-release-publish-flow.md` 讨论的是模板发布流程，不是 SDK 打包结构 |
| docs/design/ | **missing** — `DESIGN.md:18` 只记录了包名，没有讨论"为什么不拆" |
| 证据文件 | **documented** — `pypi-publish-readiness.md` §10 完整讨论了拆分可行性、二进制可行性、推荐方案 A |
| **总判定** | **missing**（没有 ADR 沉淀"维持单发行 + [cli] extra、不拆分、暂不做二进制"这个决策） |

#### 决策 5: template 命令批评（list/delete/cache 假设了不存在的中央 registry）

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **missing** — 没有任何 ADR 讨论 template 命令的设计缺陷 |
| docs/design/ | **missing** — `cli-design.md` 和 `DESIGN.md` 描述了 template 命令但没有批评 |
| 证据文件 | **missing** — 没有找到专门讨论此批评的证据文件 |
| 代码现实 | `cli/commands/template.py:148` 的 `list_templates` 调用 `GET /templates`（假设平台 registry）；`:272` 的 `delete` 调用 `DELETE /templates/{id}`（同样假设）；`:279-299` 的 `cache` 只扫本地目录（不假设 registry） |
| **总判定** | **missing**（这个批评从未被沉淀为任何文档。注：`command-source-resolution.md:53-57` 记录了"内置模板无本地 YAML"的已知限制，间接相关但不是对 template 命令的批评） |

#### 决策 6: PyPI 打包决策

**内容**：发行名 serverless-sandbox、缺 py.typed、缺 CI workflow、[project.urls] 占位符

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **missing** — 没有 ADR 讨论 PyPI 打包决策。`proposed/process/2026-09-03-release-publish-flow.md` 讨论的是**模板**发布流程（sbox install），不是 SDK 的 PyPI 发布 |
| docs/design/ | **missing** |
| 证据文件 | **documented** — `pypi-publish-readiness.md` 全文 + `ai-native-oss-completeness.md` §5.1-5.2 完整覆盖 |
| **总判定** | **missing**（证据文件详尽但没有 ADR 沉淀决策） |

#### 决策 7: O5/O7 开放决策

**O5**：平台 TemplateInfo 是否承载 custom_commands
**O7**：@sandbox.register 命名冲突

| 维度 | 判定 |
|------|------|
| .agents/notes ADR | **missing** — 没有任何 ADR 记录这两个开放问题 |
| docs/design/ | **missing** |
| 证据文件 | **documented** — `container-serve-boundary.md` §7.2 O5, O7 明确标注为"需要实测或外部确认" |
| **总判定** | **missing**（开放问题只在证据文件中记录，没有进入 ADR 体系） |

### 3.2 ADR/issue 编号在 .agents/notes/** front-matter 的命中情况

```
$ rg -i "#\d+|issue.*\d+|Issue:" .agents/notes/
(零命中)
```

**确认：.agents/notes/** 的所有 ADR 文件中，没有任何 issue 编号（#76/#83/#85/#87/#94 等）。**
ADR front-matter 只有 `Status: implemented/proposed/rejected`，没有 `Issue: #NN` 字段。
issue ↔ ADR 的映射**只存在于 git log / 工单系统**，不在 ADR 文件内。

这与 `container-serve-boundary.md` §8 D8 的发现一致。

### 3.3 汇总表

| # | 决策 | .agents/notes | docs/design | 证据文件 | 总判定 |
|---|------|--------------|-------------|---------|--------|
| 1 | envd 两层容器服务模型 | missing | partial | documented | **missing** |
| 2 | @sandbox.register 源码投递 + 类型限制 | missing | missing | documented | **missing** |
| 3 | Discovery API（Layer1/2 + 鉴权复用） | partial | partial | documented | **partial** |
| 4 | 单仓库单发行 + [cli] extra | missing | missing | documented | **missing** |
| 5 | template 命令批评 | missing | missing | missing | **missing** |
| 6 | PyPI 打包决策 | missing | missing | documented | **missing** |
| 7 | O5/O7 开放决策 | missing | missing | documented | **missing** |
| — | ADR front-matter 无 issue 编号 | confirmed (零命中) | — | — | **confirmed** |

---

## 附录：证据索引

| 证据 | 路径 |
|------|------|
| qwen-code 模板 YAML | `examples/templates/qwen-code/sandbox-template.yaml` |
| qwen-code 模板 Dockerfile | `examples/templates/qwen-code/Dockerfile`（52 行，无 qwen-cli 安装） |
| AgentModule 实际代码 | `src/serverless_sandbox/agent/builtin.py`（131 行，无 qwen-cli 映射） |
| 设计愿景（qwen-cli） | `docs/design/built-in-agents.md:59,63,99,101,108,212-229` |
| 推断引擎注册 | `src/serverless_sandbox/agent/infer.py:144-148` |
| MCP TOOL_SCHEMAS | `src/serverless_sandbox/agent/tools.py:19-158`（零 qwen 命中） |
| 会话转录 | `/Users/anycodes/.qoder/cache/projects/chat-1-2d92c1f/conversation-history/{628457aa,6e51593d,9620c890}/*.jsonl`（零 qwen 命中） |
| envd 证据文件 | `docs/evidence/research/2026-09-04-container-serve-boundary.md`（1467 行） |
| PyPI 证据文件 | `docs/evidence/research/2026-09-04-pypi-publish-readiness.md`（262 行） |
| OSS 完整性证据 | `docs/evidence/research/2026-09-04-ai-native-oss-completeness.md`（183 行） |
| ADR 目录 | `.agents/notes/implemented/architecture/`（11 files） |
| template CLI 代码 | `src/serverless_sandbox/cli/commands/template.py`（340 行） |

---

*报告结束。全文为只读审计产物，未修改任何产品代码或现有文档。*
