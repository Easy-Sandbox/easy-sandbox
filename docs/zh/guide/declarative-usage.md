# 声明式用法（@sandbox 装饰器）

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

`@sandbox` 装饰器让你以声明式方式在远程沙箱中执行 Python 函数，无需手动管理沙箱生命周期。

---

## 基本用法

```python
from easy_sandbox.declarative import sandbox

@sandbox(template="code-interpreter-v1")
def analyze(data):
    import pandas as pd
    df = pd.DataFrame(data)
    return df.describe().to_dict()

# 调用时自动：创建沙箱 → 上传函数 → 执行 → 返回结果 → 销毁沙箱
result = analyze({"col1": [1, 2, 3], "col2": [4, 5, 6]})
print(result)
```

---

## 参数配置

```python
@sandbox(
    template="code-interpreter-v1",  # 模板名称（默认 "code-interpreter-v1"）
    timeout=300,                      # 沙箱超时秒数（默认 300）
    envs={"MY_KEY": "value"},         # 环境变量
    packages=["pandas", "numpy"],     # 远程预安装的 pip 包
    serializer="json",                # 序列化方式（默认 "json"）
    sandbox_id=None,                  # 复用已有沙箱 ID（不为 None 时跳过创建）
    keep_alive=False,                 # True 时执行后不销毁沙箱
    api_key=None,                     # API Key 覆盖
    api_url=None,                     # 平台 API URL 覆盖
    domain=None,                      # 域名覆盖
    image=None,                       # Image 对象（优先于 template）
    cpu=None,                         # CPU 核数
    memory=None,                      # 内存 MB
)
def my_func():
    pass
```

### 参数详解

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `template` | `str` | `"code-interpreter-v1"` | 沙箱模板名称 |
| `timeout` | `int` | `300` | 沙箱超时秒数 |
| `envs` | `dict` | `None` | 注入的环境变量 |
| `packages` | `list[str]` | `None` | 远程预安装的 pip 包 |
| `serializer` | `str` | `"json"` | 序列化模式（`json`/`pickle`/`msgpack`） |
| `sandbox_id` | `str` | `None` | 复用已有沙箱 ID |
| `keep_alive` | `bool` | `False` | 执行后不销毁沙箱 |
| `api_key` | `str` | `None` | API Key 覆盖 |
| `api_url` | `str` | `None` | 平台 URL 覆盖 |
| `domain` | `str` | `None` | 平台域名 |
| `image` | `Image` | `None` | Image 对象（优先于 template） |
| `cpu` | `int` | `None` | CPU 核数 |
| `memory` | `int` | `None` | 内存 MB |

---

## 序列化规则

`serializer` 参数控制函数参数和返回值的序列化方式：

| 模式 | 额外依赖 | 支持类型 | 说明 |
|------|----------|----------|------|
| `json`（默认） | 无 | JSON 可序列化类型 | 最安全，跨语言兼容 |
| `pickle` | `cloudpickle` | 任意 Python 对象 | 支持复杂对象，但有安全风险 |
| `msgpack` | `msgpack` | msgpack 兼容类型 | 二进制格式，更紧凑 |

**JSON 模式**：参数通过 `json.dumps` 序列化，结果通过 `json.loads` 反序列化。不支持的类型会使用 `default=str` 回退。

**Pickle 模式**：使用 `cloudpickle` 进行序列化和 base64 编码传输。支持 lambda、闭包等复杂对象。需要远程沙箱中安装 `cloudpickle`（通过 `packages` 参数）。

**Msgpack 模式**：使用 `msgpack` 进行序列化和 base64 编码传输。需要远程沙箱中安装 `msgpack`。

---

## 与 async 结合

装饰器会自动检测被装饰函数是否为异步函数：

```python
@sandbox(template="code-interpreter-v1")
async def async_analyze(data):
    import pandas as pd
    df = pd.DataFrame(data)
    return df.describe().to_dict()

# 异步调用
result = await async_analyze({"col": [1, 2, 3]})
```

对于同步函数，装饰器生成同步包装器。若在已有事件循环中调用同步包装器，会通过 `ThreadPoolExecutor` 避免阻塞。

---

## 复用沙箱

```python
# 创建沙箱并保持运行
@sandbox(template="code-interpreter-v1", keep_alive=True)
def setup():
    import subprocess
    subprocess.run(["pip", "install", "flask"])
    return "ready"

sandbox_id = "sbx-xxxx"  # 获取沙箱 ID

# 复用已有沙箱
@sandbox(sandbox_id=sandbox_id)
def use_flask():
    from flask import Flask
    return "Flask imported successfully"
```

---

## 使用 Image 对象

`image` 参数优先于 `template`，先构建镜像再创建沙箱：

```python
from easy_sandbox.api.image import Image
from easy_sandbox.declarative import sandbox

image = (
    Image.from_template("python-base")
    .pip_install("flask", "sqlalchemy")
    .apt_install("postgresql-client")
)

@sandbox(image=image)
def my_app():
    from flask import Flask
    return "Flask app ready"
```

---

## 注册式命令

除了装饰器模式，`sandbox` 对象还支持注册式命令：

```python
from easy_sandbox.declarative import sandbox

@sandbox.register
def demo(x: int, y: str) -> str:
    """简单的演示命令"""
    return f"{y}={x}"

# 同步调用
result = sandbox.run("demo", x=1, y="hello")
print(result)  # "hello=1"

# 异步调用
result = await sandbox.run_async("demo", x=2, y="world")

# 查看已注册的命令
commands = sandbox.list_registered()
```

注册函数的参数仅支持标量类型：`str`、`int`、`float`、`bool`。

### 内置路由

```python
sandbox.register.upload()    # 启用 POST /upload 路由
sandbox.register.download()  # 启用 GET /download 路由
```

### 启动 HTTP Server

```python
sandbox.server.start(port=9000, host="0.0.0.0")
```

---

## 限制

1. **参数序列化**：函数参数和返回值必须能被选定的序列化器处理
2. **函数源码**：装饰器通过 `inspect.getsource()` 获取函数源码，Lambda 和动态生成的函数不支持
3. **导入**：远程沙箱中需要的库必须通过 `packages` 参数预安装，或已包含在模板中
4. **注册命令参数类型**：`@sandbox.register` 仅支持标量类型（`str`/`int`/`float`/`bool`），不支持复杂类型
5. **闭包变量**：函数中引用的外部变量不会被自动序列化（除非使用 `pickle` 序列化器且变量可序列化）
6. **执行环境隔离**：被装饰的函数在独立的远程 Python 进程中执行，不共享本地进程的状态

---

## 下一步

- [SDK 使用指南](sdk-usage.md) — 直接使用 Sandbox API
- [编写模板](authoring-templates.md) — 创建自定义模板
- [API 参考](../reference/api-reference.md) — 完整 API 签名
