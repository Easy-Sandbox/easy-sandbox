# Decision: 本地 Docker 构建与 ACR 推送能力

Status: implemented

## Problem
自定义模板的构建流程之前仅支持平台端构建（上传 Dockerfile 到后端 API），存在以下限制：

1. **调试困难**：构建过程在远端执行，错误信息不直观，无法本地 `docker build` 调试。
2. **无 ACR 推送能力**：平台端构建需要镜像已在 ACR 中存在（v2 API `from_image` 参数），但 SDK 没有提供本地构建→ACR 推送的完整链路。
3. **CLI 缺少本地构建命令**：用户无法通过 `sbox` CLI 一键完成"构建→推送→注册模板"流程。

## Decision
新增 `api/docker_builder.py` 模块，提供 `DockerBuilder` 类封装完整的本地构建→ACR 推送→模板注册流程。

### 核心流程

1. **本地 Docker 构建**：调用 `docker build` 子进程，支持 `--platform`、`--build-arg`、`--no-cache` 等参数。
2. **ACR 登录**：使用阿里云 AK/SK 生成临时凭证，执行 `docker login` 登录 ACR 实例。
3. **镜像推送**：`docker tag` + `docker push` 将本地镜像推送到 ACR。
4. **模板注册**：调用 `protocol/template.py` 的 v3 API 创建模板元数据，再调用 v2 API 触发构建（from_image 指向 ACR 镜像）。

### 新增错误类

在 `models/errors.py` 中新增三个错误类（E7020–E7022）：
- `DockerBuildError(E7020)` — 本地 Docker 构建失败
- `ACRPushError(E7021)` — ACR 推送失败
- `ACRLoginError(E7022)` — ACR 登录失败

### CLI 命令

新增 `sbox template build-local` 子命令：
```bash
sbox template build-local ./examples/templates/python-hello \
    --acr-namespace my-ns --acr-repo python-hello

sbox template build-local ./my-template \
    --acr-namespace prod --acree-instance-id cri-xxx
```

### v3/v2 API 方法

`protocol/template.py` 新增两个方法（对齐 E2B SDK 2.31.0）：
- `create_v3(name, ...)` → `POST /v3/templates` — 创建模板元数据，返回 templateID + buildID
- `trigger_build_v2(template_id, build_id, from_image, ...)` → `POST /v2/templates/{tpl}/builds/{build}` — 从 ACR 镜像触发构建

## API Design
```python
# api/docker_builder.py
@dataclass
class ACRConfig:
    registry: str          # e.g. "registry.cn-hangzhou.aliyuncs.com"
    namespace: str
    repo: str
    username: str          # AK ID
    password: str          # AK Secret
    acree_instance_id: str | None = None  # ACR EE instance ID

class DockerBuilder:
    async def build_and_push(
        self,
        template_dir: str | Path,
        acr_registry: str,
        acr_namespace: str,
        acr_repo: str,
        acr_username: str,
        acr_password: str,
        *,
        acree_instance_id: str | None = None,
        platform: str = "linux/amd64",
        tag: str | None = None,
        no_cache: bool = False,
    ) -> dict[str, Any]: ...
```

```python
# protocol/template.py — 新增方法
class TemplateProtocol:
    async def create_v3(self, name, *, dockerfile=None, ...) -> dict[str, Any]: ...
    async def trigger_build_v2(
        self, template_id, build_id, from_image, *, acr_headers=None, ...
    ) -> dict[str, Any]: ...
```

```python
# models/errors.py — 新增错误码
class DockerBuildError(SandboxError):
    code = "E7020"

class ACRPushError(SandboxError):
    code = "E7021"

class ACRLoginError(SandboxError):
    code = "E7022"
```

## Alternatives considered
- **仅支持平台端构建（上传 Dockerfile）** — 调试困难、构建慢、无法利用本地 Docker 缓存。Rejected 作为唯一方式。
- **使用 Docker SDK for Python（docker-py）** — 引入额外依赖，且 `subprocess` 调用 `docker` CLI 更轻量、对用户更透明。Rejected。
- **ACR 推送使用 Registry HTTP API v2（不经 docker CLI）** — 需实现完整的 manifest/blob 上传协议，复杂度高。Rejected。
- **将 AK/SK 硬编码在脚本中** — 安全风险，应使用环境变量或 `.env` 文件。Rejected。

## Dependencies
- `models/errors.py`（`DockerBuildError`/`ACRPushError`/`ACRLoginError` 错误类）
- `protocol/template.py`（`create_v3`/`trigger_build_v2` 平台 API 方法）
- `transport/http.py`（`HttpClient.platform_request` HTTP 请求）
- `utils/logging.py`（结构化日志）
- 外部依赖：本地安装 `docker` CLI

## Test Strategy
- 单元测试：`DockerBuilder` 参数校验、`ACRConfig` 数据类构造。
- Mock 测试：mock `subprocess.run` 验证 `docker build`/`docker login`/`docker push` 命令拼接正确。
- 错误场景：Docker 未安装 → `DockerBuildError`；ACR 凭证错误 → `ACRLoginError`；推送失败 → `ACRPushError`。
- CLI 测试：`sbox template build-local --help` 参数完整性。
- E2E 测试：在 `scripts/cloud_e2e_test.py` 场景 B 中覆盖真实构建→推送→注册链路。

## Acceptance criteria
- `DockerBuilder.build_and_push()` 完成"构建→登录→推送→注册"全链路。
- 三个新增错误类（E7020/E7021/E7022）在对应失败场景中正确抛出。
- `sbox template build-local` CLI 命令可执行完整流程。
- `protocol/template.py` 的 v3/v2 API 方法与 E2B SDK 2.31.0 对齐。

## Files changed
- `api/docker_builder.py` — 新建，851 行
- `models/errors.py` — 新增 `DockerBuildError(E7020)`、`ACRPushError(E7021)`、`ACRLoginError(E7022)`
- `protocol/template.py` — 新增 `create_v3()`、`trigger_build_v2()` 方法
- `cli/commands/template.py` — 新增 `build-local` 子命令
