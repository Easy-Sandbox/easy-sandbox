# 过度设计 / 合理性 / 优化审计报告

> **审计编号**: #93  
> **日期**: 2026-09-04  
> **审计视角**: Research 对抗审计 — "一个真实用户会不会用到这个？"  
> **项目**: serverless-sandbox v0.1.0（CLI: sbox，后端: 阿里云 FC，E2B 兼容）

---

## 审计总览

| # | 审查点 | 判定 | 优先级 |
|---|--------|------|--------|
| 1 | 能力模型（Capability gating） | **可简化** | P1 |
| 2 | Session 管理（可插拔存储） | **应移除大部分** | P0 |
| 3 | SandboxPool（预热池） | **应移除** | P0 |
| 4 | NL 推断引擎 | **可简化** | P1 |
| 5 | Template 命令语义重叠 | **可简化** | P1 |
| 6 | Agent 框架集成 | **应移除** | P0 |
| 7 | MCP Server | **合理保留** | P2 |
| 8 | @sandbox 装饰器 | **可简化** | P1 |
| 9 | Secrets 管理（keychain） | **可简化** | P1 |
| 10 | 证据 harness / golden-file | **合理保留** | P2 |
| 11 | Qwen CLI 融入 | **应移除设计文档虚假承诺** | P0 |

---

## 1. 能力模型（Capability Gating）

**判定: 可简化 (P1)**

### 现状

- 5 个标准能力词汇: `shell`, `files`, `code`, `terminal`, `ports`（`src/serverless_sandbox/models/template.py:18-24`）
- 默认 3 个: `shell`, `files`, `code`；`terminal` 和 `ports` 需模板显式声明（L27-31）
- `check_capability()` 被 6 个模块调用共 **13 处**门控点（`api/code.py`, `api/files.py`, `api/commands.py`, `api/network.py`, `api/sandbox.py`）
- 解析器 `capability.py` 218 行，含本地 YAML 扫描 + fail-closed 安全策略

### 问题

1. **用户无法感知门控**：SDK 用户创建沙箱后直接调用 `sb.commands.run()` 或 `sb.network.get_host()`，如果因为模板没声明 `terminal` 而报 `CapabilityNotSupportedError`，用户体验是"我明明创建了沙箱为什么不能用"。E2B SDK 没有这个概念。
2. **0.1.0 阶段无真实安全需求**：细粒度门控适合多租户平台，但 SDK 用户是自己创建自己的沙箱，限制自己的能力没有意义。
3. **DEFAULT_CAPABILITIES 排除 terminal/ports 的理由不充分**：文档说"需要显式声明"，但实际上大多数沙箱模板都需要终端和端口。

### 证据

- E2B 官方 Python SDK（`e2b-dev/e2b-code-interpreter`）: 无 capability gating 概念，所有操作直接可用
- 5 个能力词汇中只有 2 个（`terminal`, `ports`）需要"额外声明"，其余 3 个默认开启，门控形同虚设

### 建议

保留能力词汇定义（作为模板元数据），但 **移除运行时门控**（删除所有 `check_capability` 调用）。如果未来需要平台侧多租户安全控制，在后端 API 网关层实现，不在 SDK 客户端侧。

---

## 2. Session 管理

**判定: 应移除大部分 (P0)**

### 现状

- 抽象基类: `session/base.py`（36 行）— `SessionStore` ABC with save/load/delete/list_all
- 4 个实现:
  - `session/local.py`（97 行）— FileStore，JSON 文件 + filelock
  - `session/database.py`（205 行）— SQLite + PostgreSQL 双后端
  - `session/oss.py`（128 行）— 阿里云 OSS 存储
  - 内存存储（在 `__init__.py` 中）
- Session Manager: `api/session_manager.py`（163 行）
- Session 数据模型: `models/session.py`（43 行）— `SessionInfo` + `SessionConfig`
- **总计约 672 行代码**

### 问题

1. **用户真实需求只是 sandbox_id 重连**：`Sandbox.connect(sandbox_id)` 已经存在。Session 管理本质是给 sandbox_id 起个名字持久化到本地——但用户可以自己存一个 ID 字符串。
2. **4 个存储后端对 0.1.0 来说荒谬**：PostgreSQL 后端？OSS 后端？一个 CLI 工具什么场景需要把 session ID 存到 PostgreSQL？models/session.py L4 注释自己也承认："Session 管理为 SDK 扩展功能，阿里云官方文档中未定义此概念。"
3. **可插拔抽象过早**：4 个后端实现完整的 Strategy 模式，但没有任何用户场景证明需要在运行时切换存储后端。
4. **无测试覆盖真实场景**：session 恢复需要远端沙箱还活着，但沙箱有 TTL（默认 300s），session 恢复大概率失败。

### 证据

- E2B 官方 SDK: 无 session 概念。重连用 `Sandbox.connect(sandbox_id)`
- `models/session.py:4`: 自己注释承认非官方概念
- `session/database.py` 引入 `aiosqlite` + `asyncpg` 两个可选依赖，仅为存一个 JSON 字段

### 建议

**P0 删除**: `session/database.py`（SQLite/PG）、`session/oss.py`（OSS）、`session/base.py`（ABC）。
**P1 简化**: 如果保留命名 session，用一个简单的 JSON 文件读写即可（把 `session/local.py` 内联到 session_manager），无需抽象基类。

---

## 3. SandboxPool（预热池）

**判定: 应移除 (P0)**

### 现状

- `api/pool.py`（225 行）: 完整的预热池实现，含 `start/acquire/release/shutdown` + async context manager
- 支持 `min_ready`（最少就绪数）、`max_size`（最大池大小）、并发预热、自动补充

### 问题

1. **E2B 没有这个概念**: E2B 官方 Python SDK 无 SandboxPool。用户需要时创建、用完销毁，这是 Serverless 的核心理念。
2. **预热与 Serverless 理念矛盾**: Serverless 的卖点是按需创建，预热池意味着用户持续付费持有空闲沙箱。
3. **0.1.0 无用户场景**: 预热池适合高吞吐的 SaaS 平台（如 ChatGPT 的代码执行后端），不是 SDK 用户的需求。SDK 用户的典型场景是创建 1-2 个沙箱交互使用。
4. **列表实现有性能问题**: `_pool` 用 `list`，`acquire` 用 `pop(0)` 是 O(n) 操作（应该用 `collections.deque`），说明这个模块没经过性能验证。

### 证据

- `pool.py:136`: `self._pool.pop(0)` — O(n) list 操作
- E2B SDK: 无 pool 概念
- 无任何示例或文档引用 SandboxPool

### 建议

**P0 删除**。如果未来有用户需求，可以作为 `serverless-sandbox-extras` 包发布。

---

## 4. NL 推断引擎

**判定: 可简化 (P1)**

### 现状

- `agent/infer.py`（393 行）: 三级 fallback（关键词 → LLM → 默认）
- 12 个模板 profile，含中英文关键词列表
- LLM 推断调用 DashScope API（OpenAI 兼容格式）
- 关键词匹配用 word boundary regex

### 合理的部分

- `sbox create "我要分析 CSV 数据"` → 自动选择 `python-data-science` 模板，这是**好的用户体验**
- 关键词匹配是 offline、零延迟的，设计合理
- 三级 fallback 逻辑清晰

### 问题

1. **12 个模板 profile 中大部分是空壳**: `qwen-code`、`openclaw`、`hermes-agent`、`deepseek-harness` 等模板在后端不一定存在，推断出来用户也用不了
2. **LLM 推断增加了外部依赖和延迟**: 用户执行 `sbox create "xxx"` 可能触发一次 HTTP 请求到 DashScope（最多 30s 超时），这对 CLI 体验影响大
3. **关键词匹配的置信度打分逻辑硬编码**: 1 个词命中 = 0.80，2 个 = 0.85，3+ = 0.82 + n*0.03（L298-303）——这些魔法数字没有数据支撑
4. **CJK 与英文混合匹配策略合理但脆弱**: 中文用 substring 匹配，英文用 word boundary，但 "node.js" 中的点号会干扰 regex

### 建议

保留关键词匹配（实用且 offline），但：
- **精简模板 catalog 到实际可用的模板**（base, code-interpreter, node-web, browser-automation，约 4-5 个）
- **将 LLM 推断标注为 experimental**，默认关闭
- 移除魔法数字，简化为"匹配到就选、匹配多个选最长匹配"

---

## 5. Template 命令语义重叠

**判定: 可简化 (P1)**

### 现状（`cli/commands/template.py`, 340 行）

| 命令 | 功能 | 数据源 |
|------|------|--------|
| `sbox template list` | 列出模板 | 后端 API `GET /templates` |
| `sbox template info <id>` | 查看模板详情 | 后端 API `GET /templates/{id}` |
| `sbox template build -f Dockerfile` | 从 Dockerfile 构建 | 后端 API `POST /templates` |
| `sbox template delete <id>` | 删除模板 | 后端 API `DELETE /templates/{id}` |
| `sbox template install <ref>` | 从 GitHub/本地安装 | GitHub → Dockerfile → 后端 API |
| `sbox template cache` | 查看本地缓存 | 本地 `~/.sbox/templates/` |
| `sbox template cache --clear` | 清除本地缓存 | 本地 `~/.sbox/templates/` |

### 问题

1. **`template delete` vs `template cache --clear`**: `delete` 删后端模板，`cache --clear` 清本地缓存——功能不同但名字令人困惑。这是两个不同维度的操作混在同一个命令组里。
2. **`template list` 只列后端模板**: 没有中央 registry，也不列本地缓存。用户不知道有哪些"可安装"的模板。
3. **`template install` 是 GitHub 拉取 + 后端构建的组合操作**: 这个 workflow 对 0.1.0 来说太复杂了。用户需要先有一个 GitHub repo，里面放 sandbox-template.yaml，然后 `sbox template install owner/repo`——但没有文档说明怎么写 sandbox-template.yaml。

### 建议

- **合并 cache 到 template 命令的自然语义**: `sbox template cache` 改为 `sbox template local`
- **简化 install**: 0.1.0 只支持 `sbox template build -f Dockerfile`（已有），`install` 标记为 experimental
- **对 delete 和 cache --clear 加注释区分**: 或者在 help 文本里明确说明一个是远端一个是本地

---

## 6. Agent 框架集成（LangChain / CrewAI / AutoGen）

**判定: 应移除 (P0)**

### 现状

- `integrations/langchain.py`（95 行）
- `integrations/crewai.py`（96 行）
- `integrations/autogen.py`（112 行）
- `integrations/base.py`（61 行）
- **总计约 364 行代码**

### 问题

1. **三个文件是 copy-paste**: `langchain.py` 和 `crewai.py` 除了类名不同，代码完全一样（都是生成 dict，用内联 `_Mgr` class mock SandboxManager）。`autogen.py` 多了一个 `register_tools()` 方法。
2. **不是真正的集成**: 没有 `import langchain`/`import crewai`/`import autogen`。生成的是通用 dict，用户还是需要自己包装成框架原生的 Tool 对象。注释也承认了: "不依赖 langchain 包 — 生成标准的 tool dict"（langchain.py L20-21）。
3. **内联 `_Mgr` class 是 hack**: 在 handler 闭包内定义匿名类来满足 `dispatch_tool` 的接口，而不是正常的依赖注入（langchain.py L79-86）。
4. **无法单独测试**: 因为不 import 任何框架，也无法验证生成的 dict 是否真的兼容目标框架的当前版本。
5. **对 0.1.0 来说过早**: 用户还没开始用 SDK 本身，就先做框架集成是本末倒置。

### 证据

- `langchain.py` 和 `crewai.py` 的 `get_tools()` + `_make_handler()` 方法逐行相同
- 三个文件均无 `import langchain`/`import crewai`/`import autogen`
- 无集成测试验证实际兼容性

### 建议

**P0 移除整个 `integrations/` 目录**。如果要做集成，应该在各框架的生态里做（如 `langchain-sandbox` 包），而不是在 SDK 里硬编码。保留 `base.py` 的 `get_tool_schema()` 作为通用导出即可。

---

## 7. MCP Server

**判定: 合理保留 (P2)**

### 现状

- `agent/mcp.py`（384 行）: 自包含 JSON-RPC 2.0 over STDIO
- `agent/tools.py`（327 行）: 7 个工具定义 + handler
- 7 个工具: `create_sandbox`, `run_code`, `run_command`, `read_file`, `write_file`, `list_files`, `kill_sandbox`

### 为什么合理

1. **MCP 是 2024-2025 年 AI IDE 生态的真实热点**: Cursor、Claude Desktop、VS Code Copilot 都支持 MCP，SDK 提供 MCP Server 能直接让用户在 IDE 里操作远程沙箱。
2. **7 个工具全部是核心操作**: 创建、执行代码、执行命令、读/写/列文件、销毁——没有冗余工具。
3. **自包含实现避免了外部依赖**: 不依赖 `mcp` SDK 包，用标准 `asyncio` + `json` 实现，保持轻量。
4. **SandboxManager 的 "default sandbox" 概念合理**: IDE 场景下用户通常只操作一个沙箱，auto-create + 复用默认沙箱减少了工具调用次数。

### 小问题

- STDIO transport 实现是 newline-delimited JSON（L335-337），但 MCP 规范倾向于用 JSON-RPC over HTTP/SSE。不过 Cursor 确实用 STDIO，所以可以接受。
- `mcp.py:322`: `asyncio.get_event_loop()` 在 Python 3.12+ 中已 deprecated。

### 建议

保留，标记为 **stable**。修复 `asyncio.get_event_loop()` 废弃警告。

---

## 8. @sandbox 装饰器

**判定: 可简化 (P1)**

### 现状

- `declarative/decorator.py`（261 行）: 将普通函数远程执行
- `declarative/serializer.py`（92 行）: JSON / cloudpickle / msgpack 三种序列化
- 支持同步/异步函数、环境变量、pip 包安装、keep_alive、Image 构建

### 合理的部分

- **用户体验确实好**: `@sandbox() def analyze(data): ...` 然后 `analyze(data)` 就在远程执行了。这比 E2B SDK 的手动创建+上传+执行+下载流程简洁很多。
- **E2B 没有这个**: 这是真正的差异化功能。

### 问题

1. **三种序列化对 0.1.0 过度**: `cloudpickle` 和 `msgpack` 是 optional 依赖，增加了复杂度。99% 的用户用 JSON 就够了。
2. **`inspect.getsource()` 的限制**: 不支持 lambda、嵌套函数、动态生成的函数。文档没说明这些限制。
3. **Jupyter 环境的 ThreadPoolExecutor hack**: `sync_wrapper` 里检测 running event loop 然后用线程池启新 loop（L82-88），这是已知的 asyncio footgun。
4. **Image 参数增加理解成本**: `image: Image | None = None` 参数让装饰器同时承担模板构建职责，违反单一职责。

### 建议

- **保留核心装饰器功能**
- **P1 简化**: 移除 `pickle` 和 `msgpack` 序列化器（或标记 experimental），只保留 JSON
- **文档补充 `inspect.getsource()` 限制**

---

## 9. Secrets 管理（keychain.py）

**判定: 可简化 (P1)**

### 现状

- `utils/keychain.py`（160 行）: `SecretStore` class
- macOS Keychain 集成（通过 `security` 命令行工具）
- Fallback 到 `~/.sbox/secrets.json`（chmod 600 保护）
- 支持 set/get/delete/list_names

### 问题

1. **Linux 不支持**: `_set_keychain` 在非 macOS 上直接 `raise NotImplementedError`（L87），然后 fallback 到明文 JSON 文件。
2. **JSON 文件存储是明文**: 虽然 chmod 600，但密码以明文存在文件系统中。对于 API key 来说，环境变量（`E2B_API_KEY`）或 `.env` 文件是更标准的做法。
3. **subprocess 调用安全风险**: 直接 `subprocess.run(["security", "add-generic-password", ..., "-w", value])` 把密钥传给命令行参数，可能出现在 `ps aux` 输出中。
4. **与 config 命令的 .env 存储重叠**: CLI 的 `sbox config set api_key xxx` 已经能把 API key 存到 `.env` 文件，keychain 是另一套独立机制。

### 建议

- **P1 简化**: 移除 macOS Keychain 集成，统一用 `.env` + `config.toml` 方式管理配置
- 如果要做 keychain，用 `keyring` 库（跨平台，支持 macOS/Linux/Windows）而不是手动调 `security` 命令

---

## 10. 证据 harness / golden-file 测试

**判定: 合理保留 (P2)**

### 现状

- `scripts/evidence_cases.py`（868 行）: 定义 ~70+ CLI 测试用例
- `tests/test_cli_evidence/golden/`（77 个 golden 文件）
- `tests/test_cli_evidence/test_evidence_snapshots.py`（90 行）: parametrized 测试
- 支持 `SBOX_UPDATE_EVIDENCE=1` 更新 golden files

### 为什么合理

1. **CLI 输出回归是真实问题**: CLI 工具的输出格式如果改了，用户脚本可能 break。Golden-file 测试是检测这类回归的标准做法。
2. **77 个 golden 文件覆盖全面**: 帮助、配置、创建、列表、执行、错误、模板——主要 CLI 路径都有覆盖。
3. **normalize() 函数设计合理**: 掩盖 sandbox ID、时间戳、临时路径等非确定性片段，使 golden 比较稳定。
4. **实现复杂度集中在 mock 工厂**: 868 行中大部分是 mock 构建器（`_cfg`, `_rs`, `_exec` 等），测试运行器本身只有 90 行。

### 小问题

- 868 行的 mock 工厂文件可以考虑拆分（但不是 0.1.0 的优先事项）
- 对 0.1.0 来说，这套机制的 ROI 已经体现（有 77 个通过的测试用例）

### 建议

保留。这是成熟的工程实践，不是过度设计。

---

## 11. Qwen CLI 融入问题

**判定: 应移除设计文档虚假承诺 (P0)**

### 现状

Owen(#104) 审计已详细列出。关键发现：

| 文件/位置 | 内容 | 性质 |
|-----------|------|------|
| `docs/DESIGN.md:49,235,626-647` | "沙箱内置 AI CLI 工具（Codex / Qwen CLI）"、`qwen-cli browse '打开百度并截图'` 示例 | **设计愿景** |
| `docs/design/built-in-agents.md:59,63,99-108,212-229` | `qwen-cli browse/analyze` 映射、`_build_command` 伪代码 | **未实现的设计** |
| `examples/templates/qwen-code/` | sandbox-template.yaml + Dockerfile | **模板骨架，无 qwen-cli 安装** |
| `agent/infer.py:144-148` | `TemplateProfile(name="qwen-code")` 注册到推断引擎 | **引用存在但模板可能不可用** |
| `agent/builtin.py` | 零 qwen 命中；`browse()` 用 `curl`，`analyze()` 用 `py_compile` | **实际实现与设计文档不符** |

### 问题

1. **设计文档画饼但没落地**：DESIGN.md 承诺的 "qwen-cli browse/analyze" 在 `builtin.py` 中完全没有实现。`browse()` 实际用 `curl -sL`（L74），`analyze()` 用 `python -m py_compile`（L91）。
2. **模板 Dockerfile 没装 qwen-cli**: `examples/templates/qwen-code/Dockerfile` 只装了 `dashscope`/`openai`/`httpx`/`rich`，没有任何 qwen-cli 的安装步骤。
3. **推断引擎注册了不可用的模板**: `infer.py` 的 `TEMPLATE_CATALOG` 包含 `qwen-code`、`openclaw`、`hermes-agent`、`deepseek-harness` 等模板，但这些模板在后端是否存在是未知的。
4. **这是典型的"设计先行、实现未跟上"**: 不是过度设计，而是**虚假承诺**，对用户的误导比过度设计更严重。

### 建议

- **P0**: 清理 DESIGN.md 和 built-in-agents.md 中的 qwen-cli 愿景描述，标注为 "Future / Not Implemented"
- **P0**: 从 `infer.py` 的 `TEMPLATE_CATALOG` 中移除后端不存在的模板（保留实际可用的）
- 保留 `examples/templates/qwen-code/` 作为**示例模板**（但 README 注明这是 example，不是内置功能）

---

## 简化建议清单（优先级排序）

### P0 — 应该立刻移除

| 项 | 影响文件 | 节省代码量 | 理由 |
|----|----------|-----------|------|
| Session DB/OSS 存储 | `session/database.py`, `session/oss.py`, `session/base.py` | ~369 行 | 无真实用户场景；PostgreSQL/OSS 存 session ID 对 SDK 用户无意义 |
| Agent 框架集成 | `integrations/langchain.py`, `crewai.py`, `autogen.py` | ~303 行 | copy-paste 代码，不是真正的集成，无框架依赖验证 |
| SandboxPool | `api/pool.py` | ~225 行 | 与 Serverless 理念矛盾，E2B 无此概念，无用户场景 |
| 设计文档虚假承诺清理 | `docs/DESIGN.md`, `docs/design/built-in-agents.md` | N/A（文档修改） | qwen-cli 等未实现功能的描述误导用户 |
| 推断引擎不可用模板 | `agent/infer.py` TEMPLATE_CATALOG | ~60 行 | 移除后端不存在的模板 profile |

**P0 总计可移除约 957 行产品代码 + 文档修正**

### P1 — 应该简化

| 项 | 当前 | 建议 | 影响 |
|----|------|------|------|
| 能力门控 | 13 处 check_capability 调用 | 移除运行时门控，保留能力词汇作为元数据 | 6 个文件 |
| @sandbox 序列化 | JSON + pickle + msgpack (3 种) | 只保留 JSON，其余标记 experimental | `serializer.py` |
| NL 推断 LLM 调用 | 默认启用 | 默认关闭 LLM 推断，标记 experimental | `infer.py` |
| Template 命令 | 7 个子命令 | 合并/重命名语义重叠的命令 | `cli/commands/template.py` |
| Secrets keychain | macOS subprocess + JSON fallback | 移除 keychain，统一用 .env/config.toml | `utils/keychain.py` |
| Session 管理 | 可插拔架构 | 内联 LocalSessionStore，无需 ABC | `session/local.py`, `api/session_manager.py` |

### P2 — 合理保留

| 项 | 理由 |
|----|------|
| MCP Server (7 tools) | 真实 IDE 使用场景，工具集精简合理 |
| 证据 harness / golden-file | 成熟的 CLI 回归测试实践，ROI 已体现 |
| @sandbox 装饰器核心 | E2B 没有的差异化功能，用户体验好 |
| NL 关键词匹配（不含 LLM） | 实用且零延迟的模板推荐 |
| Template install (GitHub) | 虽然 0.1.0 不急需，但 workflow 设计合理 |
| integrations/base.py | get_tool_schema() 通用导出，61 行，保留无害 |

---

## 量化总结

| 指标 | 数值 |
|------|------|
| P0 可移除代码 | ~957 行（不含测试） |
| P1 可简化代码 | ~300-400 行 |
| 总 src/ 代码量（估） | ~6000+ 行 |
| 过度设计代码占比 | ~15-20% |
| 受影响模块 | 8 个（session, integrations, pool, capability, infer, keychain, declarative/serializer, template CLI） |

---

## 方法论说明

本审计以"一个真实用户会不会用到这个？"为判断标准，参照：
1. **E2B 官方 SDK** 的功能范围作为 baseline
2. **0.1.0 版本阶段** 的合理功能边界
3. **SDK vs 平台** 的职责划分（门控、多租户安全等属于平台侧）
4. **代码实现质量**（copy-paste、hack 解法、未实现承诺等）

对每个判定附具体文件路径和行号作为证据，不做主观臆断。
