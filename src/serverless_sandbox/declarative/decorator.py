"""@sandbox 装饰器 — 声明式远程执行 + 注册式命令。

用法::

    # 装饰器模式（不变）
    @sandbox(template="code-interpreter-v1")
    def analyze(data):
        import pandas as pd
        df = pd.DataFrame(data)
        return df.describe().to_dict()

    result = analyze({"col1": [1, 2, 3], "col2": [4, 5, 6]})

    # 注册式命令
    @sandbox.register
    def demo(x: int, y: str) -> str:
        return f"{y}={x}"

    result = sandbox.run("demo", x=1, y="hello")

    # 内置路由开关
    sandbox.register.upload()    # 启用 POST /upload
    sandbox.register.download()  # 启用 GET  /download

    # 启动容器内 HTTP server
    sandbox.server.start(port=9000)
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import shlex
import textwrap
import typing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from serverless_sandbox.models.template import CustomCommandArg

from .serializer import Serializer, SerializerType

if TYPE_CHECKING:
    from collections.abc import Callable

    from serverless_sandbox.api.image import Image


# ---------------------------------------------------------------------------
# Scalar type system
# ---------------------------------------------------------------------------

_SCALAR_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "float",
    bool: "boolean",
}

_BOOL_TRUE: frozenset[str] = frozenset({"true", "yes", "1"})
_BOOL_FALSE: frozenset[str] = frozenset({"false", "no", "0"})


def _annotation_to_type_str(annotation: Any) -> str:
    """Map a Python type annotation to a :class:`CustomCommandArg` type string.

    Only scalar types ``str``, ``int``, ``float``, ``bool`` are supported.
    Missing annotations default to ``"string"``.
    """
    if annotation is inspect.Parameter.empty:
        return "string"
    if annotation in _SCALAR_TYPE_MAP:
        return _SCALAR_TYPE_MAP[annotation]
    raise TypeError(
        f"Unsupported parameter type {annotation!r}; "
        f"only str, int, float, bool are allowed"
    )


def _parse_scalar(value: Any, type_str: str) -> Any:
    """Parse / coerce *value* according to its declared *type_str*.

    Bool parsing uses a whitelist (``true/false/yes/no/1/0``) to avoid the
    ``bool("False") == True`` pitfall.
    """
    if type_str == "string":
        return str(value)
    if type_str == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return int(value)
    if type_str == "float":
        if isinstance(value, float):
            return value
        return float(value)
    if type_str == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).lower()
        if s in _BOOL_TRUE:
            return True
        if s in _BOOL_FALSE:
            return False
        raise ValueError(
            f"Cannot parse {value!r} as boolean; "
            f"accepted values: true/false/yes/no/1/0"
        )
    raise ValueError(f"Unknown type: {type_str!r}")


# ---------------------------------------------------------------------------
# Registered command model
# ---------------------------------------------------------------------------


@dataclass
class _RegisteredCommand:
    """Metadata for a ``@sandbox.register``-ed function."""

    name: str
    source: str
    args: list[CustomCommandArg] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Server proxy (lazy import)
# ---------------------------------------------------------------------------


class _ServerProxy:
    """Lazy proxy to the ``serverless_sandbox.server`` module.

    Allows ``sandbox.server.start(port=9000)`` without eagerly importing
    the server package (which pulls in ``http.server`` etc.).
    """

    def start(self, port: int = 9000, host: str = "0.0.0.0") -> None:  # noqa: S104
        """Start the sandbox HTTP server (blocking).

        Args:
            port: TCP port to listen on (default ``9000``).
            host: Bind address (default ``"0.0.0.0"``).
        """
        from serverless_sandbox.server import start as _start

        _start(port=port, host=host)

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to :mod:`serverless_sandbox.server`."""
        import serverless_sandbox.server as _server_mod

        return getattr(_server_mod, name)


# ---------------------------------------------------------------------------
# Register proxy (callable + upload / download helpers)
# ---------------------------------------------------------------------------


class _RegisterProxy:
    """Callable that doubles as ``@sandbox.register`` decorator and exposes
    ``.upload()`` / ``.download()`` helpers for enabling built-in server routes.

    Using a callable class instead of a plain method allows attaching
    auxiliary methods while keeping the bare ``@sandbox.register`` syntax.
    """

    def __init__(self, factory: _SandboxFactory) -> None:
        self._factory = factory

    # -- decorator --------------------------------------------------------- #

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Register a function as a named sandbox command.

        Usage::

            @sandbox.register
            def demo(x: int, y: str) -> str:
                return f"{y}={x}"

        Only scalar parameter types are supported:
        ``str``, ``int``, ``float``, ``bool``.

        Args:
            func: The function to register (used as a bare decorator,
                  **not** a decorator factory).

        Returns:
            The original function, unmodified.
        """
        name = func.__name__
        source = _get_function_source(func)
        sig = inspect.signature(func)
        # Resolve string annotations (from __future__ annotations) to real types
        try:
            hints = typing.get_type_hints(func)
        except Exception:  # noqa: BLE001
            hints = {}
        args: list[CustomCommandArg] = []
        for pname, param in sig.parameters.items():
            annotation = hints.get(pname, param.annotation)
            arg_type = _annotation_to_type_str(annotation)
            has_default = param.default is not inspect.Parameter.empty
            args.append(
                CustomCommandArg(
                    name=pname,
                    type=arg_type,
                    required=not has_default,
                    default=(
                        str(param.default) if has_default else None
                    ),
                )
            )
        cmd = _RegisteredCommand(
            name=name,
            source=source,
            args=args,
        )
        self._factory._registry[name] = cmd

        # Bridge to server registry (effective only inside a container)
        try:
            from serverless_sandbox.server.registry import CommandArg as ServerCommandArg
            from serverless_sandbox.server.registry import default_registry

            server_registry = default_registry()

            server_args = [
                ServerCommandArg(
                    name=arg.name,
                    type=arg.type,
                    required=arg.required,
                    default=arg.default,
                    description=arg.description,
                )
                for arg in cmd.args
            ]

            server_registry.register(
                name=cmd.name,
                fn=func,
                args=server_args,
                description=getattr(cmd, "description", ""),
            )
        except ImportError:
            pass  # server module not installed
        except RuntimeError:
            pass  # registry already frozen

        return func

    # -- built-in route helpers -------------------------------------------- #

    def upload(self) -> None:
        """Enable the built-in ``upload`` route on the sandbox server.

        Calls ``serverless_sandbox.server.enable_builtin("upload")``.
        """
        from serverless_sandbox.server import enable_builtin

        enable_builtin("upload")

    def download(self) -> None:
        """Enable the built-in ``download`` route on the sandbox server.

        Calls ``serverless_sandbox.server.enable_builtin("download")``.
        """
        from serverless_sandbox.server import enable_builtin

        enable_builtin("download")


# ---------------------------------------------------------------------------
# _SandboxFactory — the module-level ``sandbox`` object
# ---------------------------------------------------------------------------


class _SandboxFactory:
    """Callable object that unifies ``@sandbox(...)`` decorator,
    ``.register`` / ``.run``, and ``.server`` access.

    ``sandbox`` is a module-level singleton of this class.

    Three usage patterns coexist:

    1. **Decorator factory** — ``@sandbox(template=..., ...)``:
       wraps a function so calls execute remotely in a sandbox.

    2. **Register + run** — ``@sandbox.register`` then
       ``sandbox.run("name", ...)``: registers a function by name;
       ``run`` creates a sandbox, invokes ``POST /commands/{name}``
       on its HTTP server, and returns the result.

    3. **Server proxy** — ``sandbox.server.start(port=9000)``:
       lazy proxy to :mod:`serverless_sandbox.server`.
    """

    def __init__(self) -> None:
        self._registry: dict[str, _RegisteredCommand] = {}
        self.register: _RegisterProxy = _RegisterProxy(self)
        self._server_proxy: _ServerProxy | None = None

    # ------------------------------------------------------------------ #
    # Server proxy
    # ------------------------------------------------------------------ #

    @property
    def server(self) -> _ServerProxy:
        """Lazy proxy to :mod:`serverless_sandbox.server`.

        Example::

            sandbox.server.start(port=9000)
        """
        if self._server_proxy is None:
            self._server_proxy = _ServerProxy()
        return self._server_proxy

    # ------------------------------------------------------------------ #
    # Decorator factory  (@sandbox(...))
    # ------------------------------------------------------------------ #

    def __call__(
        self,
        template: str = "code-interpreter-v1",
        timeout: int = 300,
        envs: dict[str, str] | None = None,
        packages: list[str] | None = None,
        serializer: str = "json",
        sandbox_id: str | None = None,
        keep_alive: bool = False,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        image: Image | None = None,
        cpu: int | None = None,
        memory: int | None = None,
    ) -> Callable[..., Any]:
        """远程沙箱执行装饰器。

        被装饰的函数将在远程沙箱中执行：

        1. 创建沙箱（或连接已有沙箱）
        2. 序列化函数和参数
        3. 上传并执行
        4. 反序列化结果返回
        5. 销毁沙箱（除非 *keep_alive=True*）

        Args:
            template: 沙箱模板名称。
            timeout: 沙箱超时时间（秒）。
            envs: 环境变量映射。
            packages: 远程需要预安装的 pip 包。
            serializer: 序列化模式 (``json`` / ``pickle`` / ``msgpack``)。
            sandbox_id: 复用已有沙箱 ID，不为 ``None`` 时跳过创建。
            keep_alive: 执行后不销毁沙箱。
            api_key: API key 覆盖。
            api_url: 平台 API URL 覆盖。
            domain: 平台域名。
            image: 可选的 :class:`~serverless_sandbox.api.image.Image` 对象。
                提供时会先调用 ``Image.build()`` 获取 template id，再用该
                id 创建沙箱。若同时指定了 *image* 和 *template*，*image* 优先。
            cpu: 沙箱 CPU 核数（传递给 ``Sandbox.create``）。
            memory: 沙箱内存大小 MB（传递给 ``Sandbox.create``）。
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            ser = Serializer(SerializerType(serializer))

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                """同步调用入口。"""
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(
                            asyncio.run, _execute(func, args, kwargs)
                        )
                        return future.result()
                return asyncio.run(_execute(func, args, kwargs))

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                """异步调用入口。"""
                return await _execute(func, args, kwargs)

            async def _execute(
                fn: Callable[..., Any],
                args: tuple[Any, ...],
                kwargs: dict[str, Any],
            ) -> Any:
                from serverless_sandbox.api.sandbox import Sandbox

                # 1. 获取或创建沙箱
                sb: Any
                if sandbox_id:
                    sb = await Sandbox.connect(
                        sandbox_id,
                        api_key=api_key,
                        api_url=api_url,
                        domain=domain,
                    )
                else:
                    # Resolve effective template: image wins over template.
                    effective_template = template
                    if image is not None:
                        tpl_info = await image.build(
                            api_key=api_key,
                            api_url=api_url,
                        )
                        effective_template = tpl_info.template_id

                    sb = await Sandbox.create(
                        template=effective_template,
                        timeout=timeout,
                        envs=envs or {},
                        cpu=cpu,
                        memory=memory,
                        api_key=api_key,
                        api_url=api_url,
                        domain=domain,
                    )

                try:
                    # Detect python command once (python3 preferred)
                    py_cmd = await _detect_python_cmd(sb)

                    # 2. 安装依赖
                    if packages:
                        pip_cmd = (
                            f"{py_cmd} -m pip install "
                            f"{' '.join(shlex.quote(p) for p in packages)}"
                        )
                        await sb.commands.run(pip_cmd)

                    # 3. 序列化参数
                    args_data = ser.serialize(
                        {"args": list(args), "kwargs": kwargs}
                    )

                    # 4. 生成执行脚本
                    func_source = _get_function_source(fn)
                    script = _build_execution_script(
                        func_name=fn.__name__,
                        func_source=func_source,
                        args_data=args_data,
                        serializer_type=serializer,
                    )

                    # 5. 上传并执行（UUID 唯一路径）
                    script_path = f"/tmp/_sbox_{uuid4().hex}.py"
                    await sb.files.write(script_path, script)
                    result = await sb.commands.run(
                        f"{py_cmd} {script_path}"
                    )

                    # 清理临时脚本
                    with contextlib.suppress(Exception):
                        await sb.commands.run(
                            f"rm -f {shlex.quote(script_path)}"
                        )

                    if result.exit_code != 0:
                        raise RuntimeError(
                            f"Remote execution failed "
                            f"(exit {result.exit_code}):\n"
                            f"stderr: {result.stderr}\n"
                            f"stdout: {result.stdout}"
                        )

                    # 6. 反序列化结果
                    output = result.stdout.strip()
                    return ser.deserialize(output)
                finally:
                    if not keep_alive and not sandbox_id:
                        await sb.kill()

            if inspect.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    # ------------------------------------------------------------------ #
    # Register + Run  (@sandbox.register / sandbox.run)
    # ------------------------------------------------------------------ #

    def list_registered(self) -> list[dict[str, Any]]:
        """Return metadata for all registered commands.

        Each entry::

            {
                "name": str,
                "args": [
                    {"name": str, "type": str, "required": bool,
                     "default": str | None},
                    ...
                ],
            }
        """
        result: list[dict[str, Any]] = []
        for name, cmd in self._registry.items():
            result.append(
                {
                    "name": name,
                    "args": [
                        {
                            "name": arg.name,
                            "type": arg.type,
                            "required": arg.required,
                            "default": arg.default,
                        }
                        for arg in cmd.args
                    ],
                }
            )
        return result

    def run(self, name: str, **kwargs: Any) -> Any:
        """Execute a registered command synchronously.

        Creates a sandbox with a persistent HTTP server and sends
        ``POST /commands/{name}`` with coerced arguments.

        Args:
            name: The registered command name.
            **kwargs: Arguments for the command (coerced to declared
                types).

        Returns:
            The return value of the remote function.

        Raises:
            ValueError: If *name* is not registered, a required arg
                is missing, or an undeclared arg is passed.
            RuntimeError: If the server responds with an error.
        """
        cmd = self._get_registered(name)
        coerced = _coerce_kwargs(cmd.args, kwargs)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self._execute_registered(cmd, coerced),
                )
                return future.result()
        return asyncio.run(self._execute_registered(cmd, coerced))

    async def run_async(self, name: str, **kwargs: Any) -> Any:
        """Execute a registered command asynchronously.

        Same as :meth:`run` but ``await``-able.
        """
        cmd = self._get_registered(name)
        coerced = _coerce_kwargs(cmd.args, kwargs)
        return await self._execute_registered(cmd, coerced)

    # -- internal helpers ------------------------------------------------

    def _get_registered(self, name: str) -> _RegisteredCommand:
        if name not in self._registry:
            available = ", ".join(sorted(self._registry)) or "(none)"
            raise ValueError(
                f"Unknown registered command {name!r}; "
                f"available: {available}"
            )
        return self._registry[name]

    async def _execute_registered(
        self,
        cmd: _RegisteredCommand,
        coerced_kwargs: dict[str, Any],
    ) -> Any:
        """Execute a registered command via the sandbox HTTP server.

        Creates a sandbox whose template runs a persistent
        :mod:`serverless_sandbox.server`, then sends
        ``POST /commands/{name}`` with *coerced_kwargs* as the JSON body
        via :meth:`~serverless_sandbox.api.sandbox.Sandbox.run_command`.
        """
        from serverless_sandbox.api.sandbox import Sandbox

        sb = await Sandbox.create(
            template="code-interpreter-v1",
            timeout=300,
        )
        try:
            return await sb.run_command(cmd.name, **coerced_kwargs)
        finally:
            await sb.kill()


# Module-level singleton ------------------------------------------------- #
sandbox = _SandboxFactory()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_kwargs(
    args: list[CustomCommandArg],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Validate *kwargs* against declared *args* and coerce types."""
    declared = {arg.name for arg in args}
    undeclared = sorted(k for k in kwargs if k not in declared)
    if undeclared:
        raise ValueError(
            f"Unexpected argument(s) {undeclared}; "
            f"declared: {sorted(declared) or '(none)'}"
        )

    coerced: dict[str, Any] = {}
    for arg in args:
        if arg.name in kwargs:
            coerced[arg.name] = _parse_scalar(kwargs[arg.name], arg.type)
        elif arg.required:
            raise ValueError(f"Required argument {arg.name!r} missing")
        elif arg.default is not None:
            coerced[arg.name] = _parse_scalar(arg.default, arg.type)
    return coerced


async def _detect_python_cmd(sb: Any) -> str:
    """Detect available python command: prefer ``python3``, fall back to ``python``."""
    try:
        result = await sb.commands.run("python3 --version")
        if result.exit_code == 0:
            return "python3"
    except Exception:  # noqa: BLE001
        pass
    return "python"


def _get_function_source(func: Callable[..., Any]) -> str:
    """获取函数源码（移除装饰器行）。"""
    source = inspect.getsource(func)
    lines = source.split("\n")
    func_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            func_start = i
            break
    return textwrap.dedent("\n".join(lines[func_start:]))


def _build_execution_script(
    func_name: str,
    func_source: str,
    args_data: str,
    serializer_type: str,
) -> str:
    """构建远程执行脚本。

    脚本在沙箱内运行：反序列化参数 → 定义函数 → 执行 → 将结果序列化输出到 stdout。
    """
    if serializer_type == "json":
        return _build_json_script(func_name, func_source, args_data)
    if serializer_type == "pickle":
        return _build_pickle_script(func_name, func_source, args_data)
    if serializer_type == "msgpack":
        return _build_msgpack_script(func_name, func_source, args_data)
    raise ValueError(f"Unknown serializer type: {serializer_type}")  # pragma: no cover


def _build_json_script(func_name: str, func_source: str, args_data: str) -> str:
    return f"""\
import json
import sys

args_data = json.loads({repr(args_data)})
args = args_data["args"]
kwargs = args_data["kwargs"]

{func_source}

result = {func_name}(*args, **kwargs)
print(json.dumps(result, default=str))
"""


def _build_pickle_script(func_name: str, func_source: str, args_data: str) -> str:
    return f"""\
import base64
import json
import sys
import cloudpickle

args_data = cloudpickle.loads(base64.b64decode({repr(args_data)}))
args = args_data["args"]
kwargs = args_data["kwargs"]

{func_source}

result = {func_name}(*args, **kwargs)
print(base64.b64encode(cloudpickle.dumps(result)).decode())
"""


def _build_msgpack_script(func_name: str, func_source: str, args_data: str) -> str:
    return f"""\
import base64
import json
import sys
import msgpack

args_data = msgpack.unpackb(base64.b64decode({repr(args_data)}), raw=False)
args = args_data["args"]
kwargs = args_data["kwargs"]

{func_source}

result = {func_name}(*args, **kwargs)
print(base64.b64encode(msgpack.packb(result, use_bin_type=True)).decode())
"""
