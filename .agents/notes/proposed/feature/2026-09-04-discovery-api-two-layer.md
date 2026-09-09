# Decision: Discovery API 两层模型（本地静态 + 远程鉴权）

Status: proposed
Task: #103, #105, #118

## Problem
SDK 的 `Sandbox.list_commands()` 已实现基础的命令发现（`api/sandbox.py` 返回 plain dicts），但存在三个缺口：(1) 只能发现本地 YAML 声明的命令，完全无法发现项目内 `@sandbox.register` 注册的 Python 命令；(2) 零鉴权零门控（是全仓库唯一不做 `check_capability` 的公开 API 之二）；(3) 参数缺少 `type` 字段。需要定义清晰的两层发现模型。

## Decision
采用**两层发现模型**：Layer 1 本地静态发现 + Layer 2 server 远程发现。

### Layer 1：本地静态发现（无需鉴权、无需连服务器）

1. **YAML 分支（已实现）**：`api/capability.py` 的 `_find_local_template()` 扫描 `~/.sbox/templates/**/template.yaml`，解析 `custom_commands:` + `capabilities:`。由 `resolve_capabilities()` 在 `Sandbox.create()`/`Sandbox.connect()` 时触发。
2. **Python 命令模块内省（缺口，由 @sandbox.register 填补）**：装饰器在导入时产出 `CustomCommand` 对象，注入同一个 `custom_commands` 字典。CLI 内省只需 `import` 用户模块即可发现。
3. **权限**：纯本地操作，只需读 `~/.sbox/templates` 目录或导入 Python 模块。不需要、也不应该要求鉴权。

### Layer 2：server 远程发现（运行时注册的命令）

> **⚠ 关键变更（2026-09-05）**：原 ADR 仅考虑平台 `GET /templates/{id}` 作为远程发现来源，并将"用户自建 server 暴露发现端点"列为 Rejected。此决策已推翻。新增的 `serverless_sandbox.server` 模块（见 `2026-09-05-sandbox-server-module.md`）提供 `GET /commands` 发现端点，成为 Layer 2 的主要来源。

4. **server 模块提供 `GET /commands` 发现端点**：`serverless_sandbox.server` 启动后，`GET https://{port}-{sandbox_id}.{domain}/commands` 返回所有已注册命令及其参数 schema。这是运行时注册命令的标准发现方式。
5. **平台模板发现（辅助）**：`protocol/template.py` 的 `GET /templates/{id}` + `transport/http.py:84` 的 `auth_headers = await self._auth.get_headers()` 自动注入 L1 凭证。`sbox template info` 是活的端到端实证。接线缺口：`api/capability.py:196` 仅一行 `# 3. TODO(Phase2): online fallback`。
6. **鉴权复用**：
   - Platform 平面 → `AuthProvider.get_headers()`（`transport/auth.py` 的 `ApiKeyAuth` 或 `AkSkAuth`）
   - envd 平面 → `EnvdTokenManager.get_headers()`（4 header）
   - server 模块发现端点 → 与命令执行共用同一传输认证（`X-Access-Token`）
   - **不是** `NetworkModule.get_access_headers()`。后者被 `ports` 能力门控（`api/network.py:63`），且 `ports` ∉ `DEFAULT_CAPABILITIES`。用它做发现鉴权 = 给发现强加绝大多数沙箱不具备的能力前置条件，**直接违反"发现权限 ⊆ 执行权限"原则**。

### 鉴权原则

7. **发现权限 ⊆ 执行权限**：
   - **身份级**：接入 Layer 2 后**自动成立**。发现与执行共用同一 L1 身份；token 无效则 `platform_request` 的 `raise_for_status()` 先抛。
   - **命令级（细粒度）**：今天不成立，且我们**无法单方面实现**。平台返回的是模板级清单，细粒度需服务端按 caller 身份过滤（超出协议客户端能力范围）。V1 明确标注"只保证身份级鉴权，不保证命令级最小可见性"。
   - **现状**（Layer 1 only）：零鉴权，泄露面仅限本地 `~/.sbox/templates`，方向安全（发现比执行更宽）。

### 现有 list_commands() 缺陷

8. **缺参数 `type` 字段**：`CustomCommandArg`（`models/template.py`）无 `type`，`list_commands()` 输出的 args 只有 `name/required/default/description`。由 `@sandbox.register` ADR 的 M1 补齐。
9. **零鉴权是正确的设计（Layer 1）**：它是同步方法、读本地字典、不发网络请求——不应也不能加鉴权。Layer 2 接线时，鉴权由 `platform_request` 自动处理。

### O5 平台 custom_commands 承载

10. **`GET /templates/{id}` 响应是否携带 `custom_commands` 待验证**。`models/template.py` 的 `TemplateInfo` 无该字段，只有泛型 `metadata: dict[str, Any]`。`custom_commands` 是本仓库的客户端侧 YAML 扩展，不是 E2B/FC 模板模型的一部分。**需 #103 的真实 E2E 验证**：`sbox template info <id> --json` 看响应是否含 `metadata`/`customCommands`。此验证直接决定 M6b（远程发现接线）是"一次函数调用"还是"需平台侧支持"。

## API Design
```python
# Layer 1: 本地发现（已实现，待增强）
commands = sandbox.list_commands()
# → [{"name": "demo", "description": "...",
#     "args": [{"name": "x", "type": "int", "required": True,
#               "default": None, "description": "..."}]}]

capabilities = sandbox.capabilities
# → frozenset({"shell", "files", "code"})

# Layer 2: 远程发现（待接线）
# resolve_capabilities() 第 3 顺位：
#   template_info = await template_protocol.get(template_id)  # GET /templates/{id}
#   # auth_headers 由 platform_request 自动注入 Authorization: Bearer
#   return parse_metadata(template_info.metadata)
```

## Alternatives considered
- **envd 暴露命令清单端点** — 结构性不可行。envd 端点面封闭且已完整枚举（Process/Filesystem/CodeInterpreter/File/Terminal），E2B OpenAPI 的 `Envd` tag 只有 health/stats/envs，envd 版本由镜像掌控。Rejected。
- **`process.Process/List` 当发现 API** — 语义错误，它返回的是"当前运行的 OS 进程"（PID 级运行时状态），不是"支持哪些命名命令 + 参数 schema"。Rejected。
- **用户自建 server 暴露发现端点** — ~~原标为 Rejected~~。**已采纳（2026-09-05）**：`serverless_sandbox.server` 模块提供 `GET /commands` 发现端点，需 `ports` 能力门控。这成为 Layer 2 运行时发现的主要方式。
- **用 `NetworkModule.get_access_headers()` 做鉴权** — 被 `ports` 门控 + `secure=False` 返回空 dict，会让发现权限小于执行权限。Rejected。

## Dependencies
- `api/capability.py` (`resolve_capabilities`, `_find_local_template`)
- `protocol/template.py` (`TemplateProtocol.get()`)
- `transport/auth.py` (`AuthProvider`, `EnvdTokenManager`)
- `transport/http.py` (`platform_request` 自动注入 L1)
- `2026-09-03-sdk-capability-surface.md` (Discovery API 定义)
- `2026-09-03-command-source-resolution.md` (解析顺位 + Phase 2 TODO)
- `2026-09-04-sandbox-register-command.md` (M1 补 `type` 字段)
- `2026-09-05-sandbox-server-module.md` (server 模块提供 `GET /commands` 发现端点)

## Test Strategy
- Layer 1：本地 YAML 发现，`list_commands()` 返回含 `type` 的 args。
- Layer 1：`@sandbox.register` 的命令在 `list_commands()` 中可见。
- Layer 2（接线后）：无 L1 凭证时 `resolve_capabilities` 回落 `DEFAULT_CAPABILITIES` + warn，不抛异常。
- Layer 2：有效凭证时能取到远程模板的 capabilities + custom_commands。
- 鉴权：Layer 2 必须走 `platform_request`（自动注入 `Authorization: Bearer`），禁止另建 `httpx.AsyncClient`。

## Acceptance criteria
- `list_commands()` 输出的 args 包含 `type` 字段。
- Layer 1 本地发现零鉴权、可离线。
- Layer 2 接线后，鉴权由 `AuthProvider.get_headers()` / `EnvdTokenManager.get_headers()` 提供（不用 `get_access_headers`）。
- O5 验证完成后，更新此 ADR 的 Layer 2 状态。
- 实现后，此 ADR 从 `proposed/` 移至 `implemented/`。

## Evidence
- `docs/evidence/research/2026-09-04-container-serve-boundary.md` §6.4
- `docs/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`（确认 Gateway routeDynamic 支持动态端口路由）
