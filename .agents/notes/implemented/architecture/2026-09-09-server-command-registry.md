# Decision: Server CommandRegistry 独立命令注册表

Status: implemented

## Problem
`server/routes.py` 之前依赖 `declarative` 层的 `_registry` 字典（属于 `_SandboxFactory` 实例），并通过 `exec(source)` 动态执行用户注册的函数源码。这造成两个问题：

1. **层级违规**：`server` 模块（stdlib-only 容器内模块）反向依赖了 `declarative` 层，破坏了 server 模块零外部依赖的设计原则。
2. **安全风险**：`exec()` 动态执行源码字符串，存在代码注入风险，且调试困难。

需要一个独立的、零外部依赖的命令注册机制，使 server 模块可以自主管理命令注册，同时保持与 declarative 层 `@sandbox.register` 装饰器的兼容。

## Decision
在 `server/registry.py` 中创建独立的 `CommandRegistry` 类，使用 stdlib `dataclasses` 构建数据模型，完全不依赖 Pydantic 或 SDK 其他层。

### 关键设计

1. **`CommandArg` 类型验证**：使用 `@dataclasses.dataclass` 定义，`__post_init__` 校验 `type` 字段仅允许 `{"string", "integer", "float", "boolean"}` 四种标量类型。

2. **`RegisteredCommand` 直接函数引用**：`fn` 字段持有可调用对象的直接引用，不再存储源码字符串。消除了 `exec()` 的使用。

3. **`freeze()` 锁定机制**：`CommandRegistry.freeze()` 将注册表标记为只读，`register()` 在 frozen 状态下抛出 `RuntimeError`。确保 server 启动后命令集不可变。

4. **`default_registry` 单例**：模块级 `_default_registry` 实例通过 `default_registry()` 函数暴露，`routes.py` 和 `app.py` 均引用同一实例。

5. **declarative → server 单向桥接**：`declarative/decorator.py` 的 `_RegisterProxy.__call__` 在注册命令到 `_factory._registry` 后，通过 `try/except ImportError` 同步注册到 `server.registry.default_registry()`，实现单向桥接。server 模块不知道 declarative 层的存在。

## API Design
```python
# server/registry.py — stdlib dataclasses, 零外部依赖

@dataclasses.dataclass
class CommandArg:
    name: str
    type: str = "string"          # {"string", "integer", "float", "boolean"}
    required: bool = False
    default: str | None = None
    description: str = ""

@dataclasses.dataclass
class RegisteredCommand:
    name: str
    fn: Any                       # 直接函数引用，非源码字符串
    args: list[CommandArg] = field(default_factory=list)
    description: str = ""

class CommandRegistry:
    def register(self, name: str, fn: Any, *, args=None, description=""): ...
    def command(self, name: str | None = None, **kwargs): ...  # 装饰器
    def freeze(self) -> None: ...
    def get(self, name: str) -> RegisteredCommand | None: ...
    def list_all(self) -> dict[str, RegisteredCommand]: ...

def default_registry() -> CommandRegistry: ...  # 模块级单例
```

```python
# declarative/decorator.py — 桥接片段
self._factory._registry[name] = cmd

# Bridge to server registry (effective only inside a container)
try:
    from easy_sandbox.server.registry import CommandArg as ServerCommandArg
    from easy_sandbox.server.registry import default_registry
    server_registry = default_registry()
    server_registry.register(name=cmd.name, fn=func, args=server_args, ...)
except ImportError:
    pass  # server module not installed
except RuntimeError:
    pass  # registry already frozen
```

## Alternatives considered
- **保留 `exec()` + 源码投递机制** — 安全风险高（代码注入）、调试困难（无行号信息），且无法持有函数闭包状态。Rejected。
- **将 `declarative._registry` 暴露为公共接口供 server 直接引用** — 引入 server→declarative 的反向依赖，违反零依赖原则。Rejected。
- **使用 Pydantic 模型定义 `CommandArg`** — server 模块需 stdlib-only 以在容器内无 pip 环境下运行，Pydantic 是第三方依赖。Rejected。

## Dependencies
- `server/routes.py`（消费 `default_registry()` 的命令进行路由分发）
- `server/app.py`（`SandboxServer.__init__` 接受可选 `registry` 参数）
- `declarative/decorator.py`（桥接层，可选依赖 server registry）
- `2026-09-05-sandbox-server-module.md`（server 模块总体架构）

## Test Strategy
- 注册命令后 `registry.get(name)` 返回正确的 `RegisteredCommand`。
- `CommandArg` 拒绝无效 `type` 值（如 `"list"`）。
- `freeze()` 后 `register()` 抛出 `RuntimeError`。
- `command()` 装饰器从函数签名自动推断参数类型和默认值。
- `default_registry()` 返回同一单例实例。
- declarative 桥接：`@sandbox.register` 注册的命令同时出现在两个 registry 中。

## Acceptance criteria
- `server/registry.py` 仅使用 Python 标准库（`dataclasses`, `inspect`），零第三方依赖。
- `routes.py` 和 `app.py` 不再 import `declarative` 层任何符号。
- `exec()` 在整个 server 模块中不再使用。
- declarative → server 桥接为可选的（`try/except ImportError`），server 可独立运行。

## Files changed
- `server/registry.py` — 新建，288 行
- `server/routes.py` — 重构，从 `default_registry` 获取命令
- `server/app.py` — 重构，`SandboxServer` 接受 `registry` 参数
- `declarative/decorator.py` — 新增桥接逻辑
