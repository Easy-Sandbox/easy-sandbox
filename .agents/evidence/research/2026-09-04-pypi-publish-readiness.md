# PyPI 发布就绪审计报告（Serverless Sandbox SDK + `sbox` CLI）

- 日期：2026-09-04
- 任务 ID：95
- 模式：只读审计（未修改任何代码/配置）
- 安全声明：本报告不包含、不引用任何 PyPI token/密钥值。发布应通过 CI 使用 GitHub Actions secret `PYPI_API_TOKEN` 完成。

---

## 1. Summary verdict（结论先行）

| 项目 | 结论 |
|---|---|
| **推荐发行名（distribution name）** | **`serverless-sandbox`** |
| `sbox` 作为发行名是否可用 | **不可用（已被占用）** — PyPI 已存在名为 `sbox` 的项目（v1.1.0，Owner `evryoneowo`，"A simple secret manager..."，MIT）。见证据 §5。 |
| `serverless-sandbox` 是否可用 | **可用（HTTP 404）** — PyPI 上尚无此发行名。见证据 §5。 |
| 当前 `pyproject.toml` 的 name | 已经是 `serverless-sandbox`（正确，无需改名） |
| 是否可以在修复前直接发布 | **否** — 存在若干 blocker（version 为 `0.1.0-dev`、URL 为 `anycodes/*` 占位符、无任何 CI/twine/build 自动化）。见 §4。 |

### 关键澄清：org 审批 ≠ 名称可用性
PyPI 的**发行名（distribution name）是全局唯一命名空间**。用户创建的 org 账户 `sbox`（display "Serverless Sandbox"）仍在审批中，该审批**只影响归属/组织命名空间与所有权管理**，**并不使 `sbox` 这个发行名变得可申请**。由于 `sbox` 发行名早已被第三方（`evryoneowo`，2026-01-08 上传）占用，**任何人（包括本 org）都无法再以 `sbox` 作为发行名发布**。因此：
- 发行名必须用 `serverless-sandbox`（已可用）。
- CLI 命令名 `sbox`（console script）与发行名相互独立，可继续使用（详见 §3 的命名冲突分析）。

---

## 2. Packaging metadata table（现状 vs 发布所需）

证据文件：`pyproject.toml`（1-108）、`src/serverless_sandbox/_version.py`（1）。

| 字段 | 当前值（file:line） | 发布所需 | 状态 |
|---|---|---|---|
| build-backend | `hatchling.build`（pyproject.toml:2-3） | hatchling/setuptools/poetry 任一 | OK（hatchling） |
| `[project].name` | `serverless-sandbox`（:6） | 全局唯一、可用 | OK（PyPI 404 可用） |
| version | dynamic → `_version.py:1` = `"0.1.0-dev"` | 稳定版如 `0.1.0` | **BLOCKER**（dev 预发布版） |
| description | `Serverless Sandbox SDK — ...`（:8） | 一句话摘要 | OK |
| readme | `README.md`（:9） | 存在且非空 | OK（README.md 129 行，hatchling 自动设 `Description-Content-Type: text/markdown`，无需手写 content-type） |
| license | `Apache-2.0`（SPDX 表达式, PEP 639）（:10） | 合法许可证 | OK（见 §4 关于 classifier 重复的小问题） |
| requires-python | `>=3.10`（:11） | 明确下限 | OK |
| authors | `Anycodes`（:12-14） | — | OK（可选：补 email） |
| keywords | sandbox/serverless/ai/agent/cloud/e2b（:15） | — | OK |
| classifiers | 见 :16-26（含 Alpha、Apache、Py3.10-3.13） | 与 license/python 一致 | 基本 OK（License classifier 与 SPDX 表达式并存，见 §4） |
| dependencies | httpx[http2]>=0.27, websockets>=12.0, pydantic>=2.0, python-dotenv>=1.0（:28-33） | 运行期最小集 | OK |
| optional-dependencies | cli / mcp / fast / declarative / session / all / dev（:35-67） | extras | OK（CLI 依赖在 `[cli]` extra，见 §3） |
| `[project.scripts]` | `sbox = "serverless_sandbox.cli.main:cli"`（:69-70） | 存在 `sbox` 入口 | OK（存在且指向正确） |
| `[project.urls]` | Homepage/Documentation/Repository/Issues 全部指向 `github.com/anycodes/serverless-sandbox*`（:72-76） | 真实公开 URL | **BLOCKER（占位符）** — 任务说明已计划后续修复，此处仅 FLAG |
| wheel packages | `packages = ["src/serverless_sandbox"]`（:81-82） | src-layout 正确 | OK |
| version 来源 | `[tool.hatch.version] path = "src/serverless_sandbox/_version.py"`（:78-79） | — | OK |
| package data / force-include | **无**（无 `[tool.hatch.build.targets.wheel.force-include]`、无 artifacts） | 若运行期需要模板数据则需配置 | 见 §4（本项目为纯 Python，无强依赖，属"提示级"） |

---

## 3. 名称一致性分析（distribution vs import vs CLI）

| 维度 | 值 | 证据 |
|---|---|---|
| 发行名（pip install X） | `serverless-sandbox` | pyproject.toml:6；README.md:5-6；docs/DESIGN.md:18 |
| 导入名（import Y） | `serverless_sandbox` | src 目录名 `src/serverless_sandbox/`；entry point 目标 `serverless_sandbox.cli.main:cli`（:70） |
| CLI 命令名 | `sbox` | `[project.scripts] sbox = ...`（:70） |

**协调性结论**：三者是有意为之的标准组合（发行名连字符 `serverless-sandbox` ↔ 导入名下划线 `serverless_sandbox` ↔ 短命令 `sbox`），内部**一致、无技术缺口**。docs/DESIGN.md:18 明确记载该设计。

**但存在两个必须提示用户的"命名陷阱"**：

1. **`pip install sbox` 会装错包**。PyPI 上 `sbox` 是第三方的 "secret manager"（`evryoneowo`）。用户若直觉性执行 `pip install sbox`，装到的是别人的库，**不是本项目**。README/文档必须明确：安装用 `pip install serverless-sandbox`，安装后才有 `sbox` 命令。
2. **CLI 命令名 `sbox` 与第三方发行名 `sbox` 同名**。二者不会在文件层直接冲突（第三方 `sbox` 提供的是可导入模块 `site-packages/sbox/`，且其 metadata 未声明 console_scripts；本项目提供的是可执行文件 `bin/sbox`）。因此在同一环境同时安装两者通常不会互相覆盖脚本，但**用户心智层面易混淆**，建议在文档中说明。
3. **CLI 依赖是 extra**：`sbox` 命令依赖 click/rich/pyyaml，位于 `[project.optional-dependencies].cli`（:36-40），**不在核心 dependencies**。裸 `pip install serverless-sandbox` 后运行 `sbox` 可能因缺 click 而报错。建议文档指引 `pip install "serverless-sandbox[cli]"`（或 `[all]`）。（这是一个可用性 blocker，见 §4。）

---

## 4. Blockers / 待修清单

### 硬 Blocker（发布前必须解决）
1. **version 为预发布 `0.1.0-dev`**（_version.py:1）。PEP 440 会将其规范化为 `0.1.0.dev0`，上传后成为 dev 预发布版，`pip install serverless-sandbox` 默认**不会**安装 dev 版（除非 `--pre`）。→ 发布前须改为 `0.1.0`。
2. **`[project.urls]` 全为 `anycodes/*` 占位符**（pyproject.toml:72-76）。指向未确定/占位仓库，PyPI 页面会展示错误链接。→ 任务说明指出后续 push-ready 任务会修，此处**仅 FLAG，不修**。
3. **无任何发布自动化**（详见 §6）：无 `.github/workflows/`（整个目录不存在）、Makefile 无 `build/dist/publish/release` 目标、无 twine 配置。→ 需新增 CI 发布流程或至少本地 `python -m build` + `twine check` + `twine upload` 流程。

### 可用性 Blocker（强烈建议发布前解决）
4. **CLI 依赖未在核心 dependencies**（:28-40）。裸安装后 `sbox` 命令缺 click/rich/pyyaml。→ 文档须指引 `[cli]`/`[all]` extra，或考虑将 CLI 依赖并入核心。

### 提示级（非阻断，但建议关注）
5. **License classifier 与 SPDX 表达式并存**：`license = "Apache-2.0"`（PEP 639 表达式，:10）同时又有旧式 classifier `"License :: OSI Approved :: Apache Software License"`（:19）。新版 core-metadata 下二者并存可能触发工具弃用告警（`twine check` 一般仍 PASS，但属不一致）。建议二选一（保留 SPDX 表达式，移除 License classifier）。
6. **package data（examples/templates/*.yaml、各 README）未纳入 wheel**：wheel 仅打包 `src/serverless_sandbox`（:81-82），而 `examples/templates/**/sandbox-template.yaml`（10 个模板）与 README 均位于 `src/` **之外**。经核查，包内代码**无 `importlib.resources` / `__file__` 加载这些数据文件**（Grep 无匹配），即项目为**纯 Python 包、运行期不依赖这些数据**，故**不构成技术 blocker**；这些属于示例资产，随 sdist/仓库分发即可。若未来将模板内置进包，需补 `[tool.hatch.build.targets.wheel.force-include]` 或 artifacts。
7. **long_description content-type**：无需手写。`readme = "README.md"`（:9）由 hatchling 自动注入 `text/markdown`，**不是 blocker**（任务清单里列的"content-type 缺失"在本项目不成立）。

---

## 5. Web 检查证据（PyPI 名称可用性）

PyPI 网页版有 JS 挑战，故改用 **PyPI JSON API**（返回干净的 200/404）验证：

### `sbox` — HTTP 200（**已占用，不可用**）
- URL：`https://pypi.org/pypi/sbox/json`
- 关键字段（引自响应）：
  - `"name":"sbox"`，`"version":"1.1.0"`
  - `"summary":"A simple secret manager with Pydantic model migration support"`
  - `"author_email":"evryoneowo <...>"`（邮箱已在本报告隐去细节）
  - `"license":"MIT"`，`"project_urls":{"Homepage":"https://github.com/evryoneowo/sbox"}`
  - `"ownership":{"organization":null,"roles":[{"role":"Owner","user":"evryoneowo"}]}`
  - 首次上传 `2026-01-08T13:02:56`（1.0.0），最新 1.1.0 上传 `2026-01-09`
- 结论：`sbox` 发行名归属第三方，**无法申请**。

### `serverless-sandbox` — HTTP 404（**可用**）
- URL：`https://pypi.org/pypi/serverless-sandbox/json` → 返回 `404`（工具响应：`error: code = 60001 message = 404`）
- 结论：`serverless-sandbox` 发行名**当前无人占用，可申请发布**。

> 说明：404 = 名称未注册 = 可用；200 = 已存在 = 被占用。此为 PyPI 官方 JSON API 的标准行为。

---

## 6. 现有发布自动化盘点（存在 vs 缺失）

| 类别 | 现状 | 证据 |
|---|---|---|
| `.github/workflows/*.yml` | **完全不存在** | Glob `.github/workflows/*` → 0 结果；Glob `**/*.yml` → 0 结果；`.github/` 目录仅含 CODE_OF_CONDUCT/CONTRIBUTING/PULL_REQUEST_TEMPLATE/SECURITY 及模板目录，**无 workflows/ 子目录** |
| Makefile `build/dist/publish/release` | **无** | Makefile(1-30) 仅有 install/dev/test/test-cov/lint/format/typecheck/clean/help；`.PHONY`(:1) 未含 build/publish/release/dist；`clean`(:27-28) 会 `rm -rf dist/` 但无构建目标 |
| twine 配置 | **无** | 全仓 Grep `twine|python -m build|pypi` → 仅 README 徽章与文档提及，无任何 twine/构建脚本；无 `.pypirc`、无 `tox.ini` 发布环境 |
| 版本来源 | 有（dynamic） | `[tool.hatch.version]`(:78-79) 读 `_version.py` |
| CI secret | 已配置（用户侧） | GitHub repo secret `PYPI_API_TOKEN`（用户已配置，本报告不涉及其值） |

**结论**：发布自动化 **从零开始**——无 workflow、无 build/publish make 目标、无 twine 配置。全部需要新建。

---

## 7. 推荐的安全发布路径（含两种鉴权方案对比）

### 7.1 前置修复（发布前）
1. `_version.py` → `__version__ = "0.1.0"`（去掉 `-dev`）。
2. `[project.urls]` → 替换为真实公开 URL（后续 push-ready 任务处理，本任务仅 FLAG）。
3. （建议）移除重复的 License classifier，保留 SPDX `license = "Apache-2.0"`。
4. （建议）README 顶部明确安装命令：`pip install "serverless-sandbox[cli]"`，并提示"`sbox` 是命令名，PyPI 上同名发行名不属于本项目"。

### 7.2 构建 + 校验（本地或 CI）
```
python -m pip install --upgrade build twine
python -m build                 # 生成 dist/*.whl 与 dist/*.tar.gz
twine check dist/*              # 校验 metadata / long_description 渲染
```
`twine check` 应输出 PASSED；若报 license classifier 与 expression 冲突告警，回到 7.1.3 处理。

### 7.3 先 TestPyPI 演练（DRY-RUN），再正式 PyPI
- TestPyPI 演练：`twine upload --repository testpypi dist/*`，随后在干净虚拟环境 `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "serverless-sandbox[cli]"` 验证 `import serverless_sandbox` 与 `sbox --help`。
- 正式发布：`twine upload dist/*`（CI 中用 secret 注入，绝不硬编码 token）。

> **PyPI 不可逆性（务必周知）**：
> - 同一发行名的**同一版本号一旦上传即永久占用，不可重传/覆盖**（即使删除文件，版本号也不能复用）。
> - **yank（撤回）只是标记，仍消耗该版本号**——`0.1.0` 一旦 yank 也不能再发 `0.1.0`，只能升 `0.1.1`。
> - 因此正式发布前务必先在 TestPyPI 演练，并对 `0.1.0` 的 metadata 做最终确认。

### 7.4 CI 发布 workflow 的两种鉴权方案对比

| 维度 | 方案 A：`pypa/gh-action-pypi-publish` + `PYPI_API_TOKEN`（token 方式） | 方案 B：PyPI Trusted Publishing（OIDC，无长期 token） |
|---|---|---|
| 现状契合度 | **高**——用户已配置 repo secret `PYPI_API_TOKEN`，可立即使用 | 需在 PyPI 项目侧预先配置 trusted publisher（owner/repo/workflow/environment），且**要求发行名已存在或先创建项目** |
| 密钥管理 | 需长期保管 token；泄漏风险高（本次即因 token 在聊天中暴露，应视为已泄漏并**轮换/吊销**） | **无长期密钥**，CI 运行时用短时 OIDC 令牌，安全性最佳 |
| 权限范围 | token 作用域可能覆盖账户多个项目（除非用 project-scoped token） | 精确绑定到单个 PyPI 项目 + 单个 workflow |
| 配置复杂度 | 低（`with: password: ${{ secrets.PYPI_API_TOKEN }}`） | 中（PyPI 侧 + workflow `permissions: id-token: write`） |
| 推荐 | 作为**立即可行的过渡方案** | 作为**中长期首选**；建议 `serverless-sandbox` 首发后尽快切换到 Trusted Publishing |

**建议**：因用户已备好 `PYPI_API_TOKEN`，首版 CI 用**方案 A** 快速打通；但因该 token 已在聊天中暴露，**必须在 PyPI 侧吊销/轮换该 token**，且 CI 只通过 secret 引用、绝不打印。**发布流程跑通后尽快迁移到方案 B（Trusted Publishing）** 以消除长期 token 风险。

> 注意：`sbox` org 审批 pending **不阻塞**以 `serverless-sandbox` 名义发布——发行名可用性与 org 归属是两回事。org 审批通过后仅影响该项目的组织归属管理，可在发布后再把项目纳入 org。

---

## 8. Evidence 汇总（file:line + web）

代码/配置证据：
- `pyproject.toml:2-3` build-backend = hatchling
- `pyproject.toml:6` name = "serverless-sandbox"
- `pyproject.toml:7` dynamic = ["version"]
- `pyproject.toml:9` readme = "README.md"
- `pyproject.toml:10` license = "Apache-2.0"（SPDX）
- `pyproject.toml:11` requires-python = ">=3.10"
- `pyproject.toml:19` License classifier（与 :10 并存）
- `pyproject.toml:28-33` core dependencies
- `pyproject.toml:35-67` optional-dependencies（cli/mcp/fast/declarative/session/all/dev）
- `pyproject.toml:69-70` `[project.scripts] sbox = "serverless_sandbox.cli.main:cli"`
- `pyproject.toml:72-76` `[project.urls]` 全部 `github.com/anycodes/serverless-sandbox*`（占位符）
- `pyproject.toml:78-79` `[tool.hatch.version] path = src/serverless_sandbox/_version.py`
- `pyproject.toml:81-82` `[tool.hatch.build.targets.wheel] packages = ["src/serverless_sandbox"]`（无 force-include）
- `src/serverless_sandbox/_version.py:1` `__version__ = "0.1.0-dev"`
- `Makefile:1,6-29` 无 build/dist/publish/release 目标
- `.github/`（list_dir）无 `workflows/` 子目录；Glob `.github/workflows/*`=0、`**/*.yml`=0
- Grep `importlib.resources|__file__|files(` 于 `src/serverless_sandbox/`：无数据文件加载（纯 Python 包）
- `examples/templates/**/sandbox-template.yaml`（10 个模板，位于 `src/` 之外，未纳入 wheel）
- `README.md:5-6` 徽章已指向 `pypi.org/project/serverless-sandbox/`
- `docs/DESIGN.md:18` "Python 包名 `serverless-sandbox`（PyPI），导入名 `serverless_sandbox`"

Web 证据：
- `https://pypi.org/pypi/sbox/json` → **200**：`"name":"sbox"`, `"version":"1.1.0"`, `"summary":"A simple secret manager with Pydantic model migration support"`, owner `evryoneowo`, MIT, 首传 2026-01-08 → **名称已占用**
- `https://pypi.org/pypi/serverless-sandbox/json` → **404** → **名称可用**
- （网页版 `https://pypi.org/project/sbox/` 与 `/project/serverless-sandbox/` 因 JS 挑战无法直接抓取，故采用官方 JSON API 判定 200/404）

---

## 9. 只读声明
本次审计未修改 `pyproject.toml`、未新增 workflow、未构建包、未接触任何 token 值。占位符 URL 修复由后续 push-ready 任务处理，本报告仅 FLAG。

---

## 10. SDK/CLI packaging structure options（追加范围：结构评估）

> 应 leader 追加范围（2026-09-04）补充。仍为只读评估，不涉及任何 token。

### 10.a 现状确认：单一发行（single distribution）
SDK 与 CLI **当前打包在同一个发行内**，共用一个 wheel 与一个 `sbox` console-script 入口：
- 一个包目录 `src/serverless_sandbox/`，同时含 SDK 层（`api/ transport/ protocol/ models/ session/ agent/ declarative/ integrations/`）与 CLI 层（`cli/`）。
- 入口点：`pyproject.toml:69-70` `[project.scripts] sbox = "serverless_sandbox.cli.main:cli"`。
- 打包范围：`pyproject.toml:81-82` `[tool.hatch.build.targets.wheel] packages = ["src/serverless_sandbox"]`（整个包，含 `cli/`）。
- CLI 依赖被隔离为 extra：`pyproject.toml:36-40` `[project.optional-dependencies].cli = [click, rich, pyyaml]`（**核心 dependencies 不含 CLI 依赖**）。

结论：**未拆分**，是"one-repo-one-distribution + CLI 作为 extra"的结构。

### 10.b 拆分可行性（split feasibility）
**依赖方向干净、单向（CLI → SDK），无导入环，拆分在技术上可行。**
- CLI 依赖 SDK：`cli/commands/sandbox.py:40-51` 导入 `api.sandbox`、`agent.infer`；`cli/commands/sandbox.py:179-184` 导入 `models.sandbox / protocol.sandbox / transport.auth / transport.config / transport.http / utils.async_bridge`；`cli/main.py:81-96` 导入 `models.errors`、`cli.formatters`。
- **反向为零**：对 `api/ models/ transport/ protocol/ session/ agent/ declarative/ integrations/ compat/ extensions/ utils/` 全量 Grep `serverless_sandbox.cli` / `from .cli` → **0 匹配**。即 SDK 从不导入 CLI。
- 因此可安全拆为：`serverless-sandbox`（纯 SDK）+ 独立 `sbox` CLI 元包（`install_requires = ["serverless-sandbox==<version>"]`）。无循环依赖阻碍。

拆分的**成本与复杂点**：
1. **命名占用（硬约束）**：独立 CLI 发行名想叫 `sbox` **不可行**——PyPI 上 `sbox` 已被第三方占用（见 §5）。CLI 元包只能另取名（如 `serverless-sandbox-cli`），console script 仍可叫 `sbox`。这削弱了"拆出 `sbox` 包"的初衷。
2. **版本协同成本**：两发行须锁版本（CLI 依赖 SDK 精确/兼容版本），发布节奏需同步，CI 需两次构建+两次上传+版本矩阵测试。
3. **package data（examples/templates/*.yaml）**：这些资产位于 `src/` 之外（§4.6），当前**不随任何 wheel 分发**、运行期也**无代码加载**（Grep `importlib.resources/__file__` = 0）。因此拆分**不会新增 package-data 冲突**——但反过来说，若未来想让 `sbox install <template>` 内置模板，需决定模板数据归 SDK 还是 CLI 包，并补 `force-include`，这会成为拆分后的归属争议点。
4. **收益有限**：当前用 extra（`[cli]`）已能实现"只装 SDK / 装 SDK+CLI"的分离效果，拆成两发行带来的额外收益（独立版本、独立依赖）相对其协同成本偏低。

### 10.c 二进制（freeze）可行性：shiv / pex / PyInstaller
运行期依赖集合（CLI 实际用到）：
- 核心：`httpx[http2]>=0.27`、`websockets>=12.0`、`pydantic>=2.0`、`python-dotenv>=1.0`（pyproject.toml:28-33）
- CLI extra：`click>=8.0`、`rich>=13.0`、`pyyaml>=6.0`（:36-40）
- 可选 extras：`mcp`（:41-43）、`orjson`（fast, :44-46）、`cloudpickle`+`msgpack`（declarative, :47-51）

**原生/二进制依赖（影响 freeze）**：
- `pydantic>=2` → 依赖 `pydantic-core`（**Rust 编译扩展**）。PyInstaller 需 pydantic hook（社区已有，通常可用）；shiv/pex 打包平台轮子即可，但产物**平台相关**。
- `pyyaml` → 可选 `libyaml` C 扩展（`yaml.CParser`），有纯 Python 回退。
- `websockets` → 可选 C 加速扩展，有纯 Python 回退。
- `orjson`（fast extra）→ **Rust 编译**；`msgpack`（declarative extra）→ **C 编译**。仅当启用相应 extras 时进入依赖图。
- 结论：原生依赖使 shiv/pex 产物**非跨平台通用**（需按 OS/arch/Python 分别构建），PyInstaller 需正确 hooks。均可行但增加构建矩阵复杂度。

**动态导入（freeze 的主要破坏点）**：
- `cli/main.py:44-51` `_load_command()` 使用 `importlib.import_module(mod_path)`，模块路径来自字符串字典 `lazy_subcommands`（`main.py:144-158`，13 条，如 `"serverless_sandbox.cli.commands.sandbox:create"`）。**freeze 工具做静态分析，看不到这些字符串动态导入** → 直接 freeze 会漏收 `cli.commands.*` 子模块，运行时 `sbox create` 报 ModuleNotFound。
  - 缓解：PyInstaller `--hidden-import`/`--collect-submodules serverless_sandbox.cli.commands`；shiv/pex 无静态分析（打包整包 wheel），此问题较小，但仍需确保所有子模块在 wheel 内（当前满足）。
- `cli/main.py:167` `@click.version_option(package_name="serverless-sandbox")` → 运行时用 `importlib.metadata` 读取已安装发行元数据。**frozen 二进制内通常无 `*.dist-info`** → `sbox --version` 可能抛错。需在 freeze 前改为静态版本或补 metadata。
- 其余大量 CLI→SDK 导入采用**函数内惰性 import**（如 `cli/commands/sandbox.py:40,179-184`），属正常静态可分析导入，freeze 工具可识别。

**插件/entry-point 发现**：未发现基于 `entry_points`/`pkg_resources` 的插件发现（Grep = 0）；唯一 entry point 是自身的 console script。动态性集中在上面的 LazyGroup。

**数据文件访问**：包内**无** `importlib.resources/__file__` 数据加载（§4.6）→ 模板 yaml 由用户路径读入，非包内资源，**freeze 无数据文件收集问题**。

**重要定性**：二进制（freeze）是**分发 UX 选项**（免 Python 环境、单文件执行），**不是**依赖环的修复手段——本项目本就无依赖环（§10.b）。是否 freeze 取决于"是否想给用户免安装的单文件 CLI"，与打包结构正确性无关。

### 10.d 推荐

| 方案 | 评价 | 推荐度 |
|---|---|---|
| **A. one-repo-one-dist（现状：单发行 + `[cli]` extra）** | 依赖单向无环、发布简单、版本天然一致；extra 已能区分 SDK-only 与 SDK+CLI | **首选（推荐维持）** |
| B. two-dist（SDK + 独立 CLI 元包） | 技术可行但收益有限：`sbox` 名不可用、需版本协同、双份 CI；仅在 CLI 需完全独立发布节奏时才值得 | 次选（暂不建议） |
| C. two-repo（SDK 与 CLI 分仓） | 在 B 的成本上再加分仓协作/issue/CI 复杂度，当前团队规模不划算 | 不建议 |
| D. binary（shiv/pex/PyInstaller 冻结 `sbox`） | 纯 UX 加分项（免环境单文件）；需处理 LazyGroup 动态导入的 hidden-imports、`version_option` 的 metadata、pydantic-core/orjson/msgpack 原生扩展与跨平台构建矩阵 | 可选增强（非必需，且非结构修复） |

**结论**：维持 **方案 A（单发行 `serverless-sandbox` + `[cli]` extra）**。理由：SDK→CLI 依赖单向且无环，extra 机制已满足"轻量 SDK / 完整 CLI"两种安装诉求；拆分会引入 `sbox` 命名不可用、版本协同与双 CI 成本而收益有限。二进制冻结仅作为**未来可选的分发 UX 增强**，且必须先解决 LazyGroup 动态导入与 `version_option` metadata 两处 freeze 阻断点——它与"是否拆分""是否有依赖环"无关。
