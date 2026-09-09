# Decision: @sandbox.register 注册式命令（注册到常驻 HTTP Server 端点）

Status: proposed
Task: #98, #105, #118

## Problem
用户需要把 Python 函数注册为可通过 `sbox run` 调用的具名命令。当前 custom commands 只能通过 YAML 声明（`template.yaml` 的 `custom_commands:` 段），缺少从 Python 代码直接注册的途径。需要一个装饰器 API，使函数名映射为命令名、函数签名映射为 CLI 选项。

## Decision
新增 `@sandbox.register` 装饰器，命令注册到容器内常驻 HTTP server 的端点，客户端经 HTTP 调用。

> **⚠ 关键变更（2026-09-05）**：原 ADR 采用"源码投递执行"机制（`files.write` 投递脚本 + `commands.run` 执行），并明确不引入新容器内 server。此决策已推翻。原因：(1) 每次调用都需完整 files.write + commands.run 链路，延迟高；(2) 无法支持常驻状态；(3) 已新增 `serverless_sandbox.server` 模块（见 `2026-09-05-sandbox-server-module.md`），提供常驻 HTTP server 承载注册命令。

### 核心设计

1. **命令注册到常驻 HTTP server 端点**：`@sandbox.register` 装饰的函数，被注册为 `serverless_sandbox.server` 模块的 HTTP 端点。客户端通过 `POST /commands/{name}` 调用，body 为 JSON kwargs，响应为 `{"result": ...}` 或 `{"error": ..., "type": ...}`。

2. **函数名→命令名**：`@sandbox.register` 装饰的函数，其 `func.__name__` 即为命令名，与 YAML `custom_commands:` 的 key 同构。最终产出一个 `CustomCommand` 对象，与 YAML 解析产出的完全一致，下游（`Sandbox.run` 占位符替换、`list_commands` 发现输出、CLI `--arg` 解析）**全部零改动即可复用**。

3. **函数签名→CLI 选项**：装饰器在**导入时**运行 `inspect.signature(fn)`，把参数名/类型注解/默认值转成 `CustomCommandArg`（含 `type` 字段）。

4. **参数类型限制**：V1 只支持 `str`/`int`/`float`/`bool` 四种标量。
   - `dict`/`list` **必须排除**：复杂类型需要额外的 JSON schema 校验，V1 不支持。
   - `file` 排除：语义上是两步操作（先 `files.upload` 再传路径），不属于参数强制。
   - `bool` 需**显式白名单解析**（`{"true","1","yes"}` → True；`{"false","0","no"}` → False），不能用 Python `bool()` 转换（`bool("False") == True`）。

### WIRE CONTRACT（客户端→server 通信协议）

5. **请求格式**：`POST https://{port}-{sandbox_id}.{domain}/commands/{name}`
   - Content-Type: `application/json`
   - Body: `{"key": "value", ...}`（函数 kwargs）
6. **成功响应**：`200 OK`，`{"result": <return_value>}`
7. **失败响应**：`4xx/5xx`，`{"error": "<message>", "type": "<exception_class>"}`
8. **发现端点**：`GET /commands` → 返回所有已注册命令及其参数 schema

### O7 命名决策：保留 @sandbox.register

9. **命名冲突解决**：`declarative/decorator.py` 已有 `sandbox` 函数（装饰器工厂）。保留 `@sandbox.register` 命名，通过将 `sandbox` 改为**可调用对象**实现——即一个同时支持 `__call__`（原有 `@sandbox(template=...)` 语义）和 `register` 方法的类实例。

## API Design
```python
# 注册式命令（新机制：注册到 HTTP server 端点）
@sandbox.register
def demo(x: int, y: str = "hello") -> str:
    """Run a demo command."""
    return f"{x}: {y}"

# 客户端 SDK 调用
result = await sandbox.server.call("demo", x=42, y="world")
# → POST https://{port}-{sandbox_id}.{domain}/commands/demo
# → Body: {"x": 42, "y": "world"}
# ← Response: {"result": "42: world"}

# CLI 调用
# sbox run <sandbox_id> demo -a x=42 -a y="world"

# 发现端点
# GET /commands → [{"name": "demo", "args": [...], "description": "Run a demo command."}]
```

```python
# CustomCommandArg 扩展（M1）
class CustomCommandArg(BaseModel):
    name: str
    default: str | None = None
    required: bool = False
    description: str = ""
    type: str | None = None  # 新增：str/int/float/bool，省略=str（向后兼容）

# sandbox 可调用对象实现（O7）
class _SandboxFactory:
    def __call__(self, template=..., ...):
        """原有 @sandbox(template=...) 语义"""
        ...
    def register(self, fn):
        """@sandbox.register 语义"""
        ...

sandbox = _SandboxFactory()
```

## Alternatives considered
- **源码投递执行（files.write + commands.run）** — 原 ADR 的主方案。每次调用需完整投递链路（写临时脚本→执行→回传 stdout），延迟高、无法常驻状态、不支持并发。Rejected in favor of persistent HTTP server。
- **cloudpickle 序列化函数体** — 容器内需预装 `cloudpickle`，部署成本高。Rejected。
- **走 envd Code Interpreter 原语** — `protocol/code_interpreter.py` 自陈"逆向推断、未实测"。Rejected 作为主路径。
- **CLI 动态生成 `--x`/`--y` 选项（在 Click 层）** — 需先连沙箱才能建选项，`--help` 变慢且离线不可用。Rejected 作为唯一层。
- **`@remote.register` 命名** — 引入新顶层名，增加心智负担。Rejected。
- **每命令完整 JSON-schema** — V1 过重，V2 可考虑。Deferred。

## Dependencies
- `declarative/decorator.py` (复用 `_get_function_source`, `_build_execution_script` 用于 server 模块投递)
- `models/template.py` (`CustomCommand`, `CustomCommandArg` 扩展)
- `2026-09-03-sdk-capability-surface.md` (custom commands 走 `sandbox.run("name", **args)`)
- `2026-09-04-envd-container-service-model.md` (两层模型，envd 为基础层)
- `2026-09-05-sandbox-server-module.md` (server 模块架构决策，承载注册命令)

## Test Strategy
- `@sandbox.register` 装饰后，函数名成为可发现的命令名（`GET /commands` 包含它）。
- `inspect.signature` 正确提取参数名/类型/默认值 → `CustomCommandArg` 含 `type` 字段。
- 不支持的参数类型（`dict`/`list`/自定义类）在装饰时**立即报错**。
- `bool` 参数的白名单解析：`"true"` → True，`"false"` → False，`"maybe"` → 报错。
- 类型转换在 JSON 反序列化时完成；转换失败 fail-fast（不静默降级为字符串）。
- `mypy --strict` 对 `sandbox()` 与 `sandbox.register` 均能通过类型检查。
- 端到端：`POST /commands/demo` 调用 → 返回正确 JSON 响应。

## Acceptance criteria
- `@sandbox.register` 的函数注册为 HTTP server 端点，可通过 `POST /commands/{name}` 调用。
- YAML 声明的命令与 Python 注册的命令收敛到同一个 `CustomCommand` 模型。
- 参数类型仅限 `str/int/float/bool`；`dict/list/file` 报明确拒绝错误。
- `sandbox` 既是可调用装饰器又有 `.register` 方法，且 `py.typed` + `mypy --strict` 通过。
- WIRE CONTRACT：请求 `POST /commands/{name}` + JSON body，成功 `{"result"}` 失败 `{"error","type"}`。
- 实现后，此 ADR 从 `proposed/` 移至 `implemented/`。

## Evidence
- `docs/evidence/research/2026-09-04-container-serve-boundary.md` §5, §6.1–§6.3, §7 O7
- `docs/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`（确认容器内 Gateway 支持 routeDynamic 端口路由）
