# Python Hello 模板

基础 Python 开发环境模板。

## 安装

```bash
ebx install ./examples/templates/python-hello --registry-type local
```

## 使用

```bash
ebx create --template python-hello
```

### 命名命令（端到端）

容器启动后会自动运行 `commands.py`，监听端口 9000，提供以下命名命令：

```bash
# 打招呼
ebx run <sandbox-id> hello --name Alice
# → Hello, Alice!

# 执行 Python 代码
ebx run <sandbox-id> run_script --code "print(1+1)"
# → 2
```

SDK 侧等价写法：

```python
from easy_sandbox import Sandbox

sandbox = Sandbox.create(template="python-hello")
result = sandbox.run("hello", name="Alice")
print(result)  # Hello, Alice!
```

### 上传 / 下载

```bash
ebx upload <sandbox-id> ./local_file.txt /app/remote.txt
ebx download <sandbox-id> /app/remote.txt ./local_file.txt
```

## 环境

- 基础镜像: Ubuntu 22.04
- Python 3 + pip
- 工作目录: /app
