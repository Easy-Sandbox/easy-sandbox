# Decision: 云端端到端测试基础设施

Status: implemented

## Problem
项目此前仅有本地单元测试（mock 后端），无法验证 SDK/CLI/Server 在真实阿里云 FC Agent Sandbox 环境下的完整功能。需要一套云端 E2E 测试基础设施，覆盖：

1. 官方预置模板（`code-interpreter-v1`、`base`）的基础能力验证
2. 自定义模板（`examples/templates/` 下 10 个模板）的构建→部署→运行全链路验证
3. 并行执行以缩短总测试时间

## Decision
创建 `scripts/cloud_e2e_test.py` 脚本，分两大场景（Part）组织测试用例，支持并行执行。

### 场景 A：官方预置模板（Part 1）

验证平台已有模板的 CLI + SDK envd 能力（shell/files/code）：
- **模板**：`code-interpreter-v1`（templateID: `8d926meb1xzckz1a83ib`）、`base`（templateID: `216g37mamkdfhzrauvxk`）
- **测试内容**：`sbox create`/`sbox exec`（CLI）+ `Sandbox.create()`/`sandbox.commands.run()`（SDK）
- **覆盖能力**：shell 命令执行、文件读写、代码解释器

### 场景 B：自定义模板（Part 2）

验证 CLI 本地构建→ACR 推送→模板创建→沙箱启动→Server 能力全链路：
- **模板**：`examples/templates/` 下的 10 个模板（python-hello, codex, node-web, browser-automation, claude-code, deepseek-harness, hermes-agent, openclaw, qoder, qwen-code）
- **测试内容**：`sbox template build-local`（CLI）+ `DockerBuilder`（SDK）+ Sandbox Server 能力
- **覆盖能力**：Docker 构建、ACR 推送、模板注册、沙箱创建、Server 启动与调用

### 并行架构

- `MAX_CONCURRENCY = 5` — 最大并行沙箱数
- 使用 `asyncio.Semaphore` 控制并发
- 每个测试用例独立创建/销毁沙箱，互不影响
- 测试结果汇总输出（通过/失败/跳过）

### 凭证配置

通过项目根目录 `.env` 文件配置（已加入 `.gitignore`）：
- `E2B_API_KEY` — FC Agent Sandbox 平台 API Key
- `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` — ACR 推送所需的阿里云 AK/SK

## API Design
```bash
# 运行全部 E2E 测试
cd <project-root>
python3 scripts/cloud_e2e_test.py

# 依赖项
pip install "serverless-sandbox[cli]" httpx pyyaml python-dotenv
```

```python
# 核心结构
OFFICIAL_TEMPLATES = {
    "code-interpreter-v1": "8d926meb1xzckz1a83ib",
    "base": "216g37mamkdfhzrauvxk",
}

CUSTOM_TEMPLATES = [
    "python-hello", "codex", "node-web", "browser-automation",
    "claude-code", "deepseek-harness", "hermes-agent",
    "openclaw", "qoder", "qwen-code",
]

MAX_CONCURRENCY = 5
```

## Alternatives considered
- **使用 pytest + pytest-asyncio 集成到标准测试套件** — E2E 测试需要真实凭证且耗时长（分钟级），混入单元测试会拖慢 `make test`。独立脚本更灵活。Rejected 作为默认方式（但可通过 `@pytest.mark.integration` 桥接）。
- **单线程顺序执行** — 10 个自定义模板顺序构建耗时过长。Rejected。
- **使用 GitHub Actions 中的 service container** — FC 沙箱是远程服务非本地容器，无法用 service container 模拟。Rejected。

## Dependencies
- `api/sandbox.py`（`Sandbox.create()` SDK 接口）
- `api/template.py`（`TemplateManager` 模板管理）
- `api/docker_builder.py`（`DockerBuilder` 本地构建）
- `transport/auth.py`（`create_auth_provider` 认证）
- `transport/config.py`（`load_config` 配置加载）
- `examples/templates/`（10 个自定义模板目录）

## Test Strategy
- 场景 A 的每个官方模板验证：创建沙箱 → 执行 shell 命令 → 验证输出 → 销毁沙箱。
- 场景 B 的每个自定义模板验证：构建镜像 → 推送 ACR → 创建模板 → 创建沙箱 → 启动 Server → 调用命令 → 销毁。
- 失败用例记录详细 traceback，不阻塞其他用例。
- 最终输出汇总表（通过数/失败数/跳过数）。

## Acceptance criteria
- `python3 scripts/cloud_e2e_test.py` 可在配置 `.env` 凭证后端到端运行。
- 官方模板和自定义模板均有独立测试用例。
- 并行执行不超过 `MAX_CONCURRENCY` 个并发沙箱。
- 测试结果有清晰的汇总输出。

## Files changed
- `scripts/cloud_e2e_test.py` — 新建，922 行
