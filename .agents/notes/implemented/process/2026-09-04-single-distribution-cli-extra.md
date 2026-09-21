# Decision: 单仓库单发行 + [cli] extra（不拆库、暂不做二进制）

Status: implemented
Task: #95, #105

## Problem
SDK 与 CLI 共存于同一仓库，需要决定打包结构：(1) 是否拆分为独立发行（SDK + CLI 元包）；(2) CLI 依赖如何隔离；(3) 是否提供预构建二进制（shiv/pex/PyInstaller）。

## Decision
维持**单仓库单发行 + `[cli]` extra** 结构。

### 命名体系

1. **发行名（pip install X）**：`easy-sandbox`。`ebx` 已被 PyPI 第三方占用（`evryoneowo` 的 "secret manager"，v1.1.0，MIT，2026-01-08 首传），不可用。
2. **导入名（import Y）**：`easy_sandbox`。与发行名的连字符/下划线对应关系是 Python 打包标准惯例。
3. **CLI 命令名**：`ebx`。`[project.scripts] ebx = "easy_sandbox.cli.main:cli"`。CLI 命令名与发行名无关，可自由选择。

### 安装方式

4. **纯 SDK**：`pip install easy-sandbox` — 核心依赖 httpx/websockets/pydantic/python-dotenv。
5. **SDK + CLI**：`pip install "easy-sandbox[cli]"` — 额外安装 click/rich/pyyaml。
6. **裸安装后 `ebx` 命令缺 click 会报错**：这是已知的可用性陷阱，文档须前置说明。

### 不拆库

7. **依赖方向干净、单向**：CLI → SDK。反向为零（全量 Grep `easy_sandbox.cli` / `from .cli` 在 SDK 层 = 0 匹配）。无循环依赖。
8. **拆分技术可行但收益有限**：
   - `ebx` 发行名不可用（硬约束），CLI 独立包只能叫 `easy-sandbox-cli`，削弱初衷。
   - 需版本协同（锁版本、双份 CI、发布节奏同步）。
   - 当前 extra 机制已满足"只装 SDK / 装 SDK+CLI"两种诉求。

### 暂不做二进制

9. **freeze 不是结构修复，是分发 UX 选项**。当前阻断点：
   - `cli/main.py` 的 `LazyGroup` 使用 `importlib.import_module` 动态导入（PyInstaller 需 `--hidden-import`）。
   - `@click.version_option(package_name="easy-sandbox")` 依赖 `importlib.metadata`（frozen 内通常无 `*.dist-info`）。
   - `pydantic-core`（Rust）、`orjson`（Rust）、`msgpack`（C）使产物平台相关。

## API Design
```toml
# pyproject.toml（现状）
[project]
name = "easy-sandbox"
# ...

[project.optional-dependencies]
cli = ["click>=8.0", "rich>=13.0", "pyyaml>=6.0"]

[project.scripts]
ebx = "easy_sandbox.cli.main:cli"

[tool.hatch.build.targets.wheel]
packages = ["src/easy_sandbox"]
```

```bash
# 安装方式
pip install easy-sandbox            # 纯 SDK
pip install "easy-sandbox[cli]"     # SDK + CLI
pip install "easy-sandbox[all]"     # 全部 extras
```

## Alternatives considered
- **拆为两个发行（SDK + CLI 元包）** — 技术可行（依赖单向无环），但 `ebx` 发行名被占、版本协同成本高、收益有限。Rejected（暂不建议）。
- **拆为两个仓库** — 在双发行成本上再加分仓协作/issue/CI 复杂度，当前团队规模不划算。Rejected。
- **freeze 为单文件二进制** — 纯 UX 加分项，需解决 LazyGroup 动态导入、version_option metadata、原生扩展跨平台构建。可选增强（非必需）。
- **CLI 依赖并入核心 dependencies** — 裸 `pip install easy-sandbox` 会装 click/rich/pyyaml，对只用 SDK 的用户是不必要的膨胀。Rejected。

## Dependencies
- `pyproject.toml`（发行配置）
- `src/easy_sandbox/_version.py`（版本来源）
- `cli/main.py`（entry point + LazyGroup）

## Test Strategy
- `pip install easy-sandbox` 后 `import easy_sandbox` 成功、`ebx` 命令因缺 click 报明确错误。
- `pip install "easy-sandbox[cli]"` 后 `ebx --help` 正常。
- Grep `easy_sandbox.cli` / `from .cli` 在 `api/`/`models/`/`transport/`/`protocol/` 等 SDK 层 = 0 匹配（持续验证无循环依赖）。

## Acceptance criteria
- 单一发行名 `easy-sandbox`，单一导入名 `easy_sandbox`，CLI 命令 `ebx`。
- `[cli]` extra 隔离 CLI 依赖，SDK 核心无 click/rich/pyyaml。
- SDK → CLI 依赖方向为零。

## Evidence
- `.agents/evidence/research/2026-09-04-pypi-publish-readiness.md` §3, §10
