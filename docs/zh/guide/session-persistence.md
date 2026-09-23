# 会话持久化

> **项目更名说明**：本项目已从 Serverless Sandbox 更名为 **Easy Sandbox**。PyPI 包名: `easy-sandbox`（`pip install easy-sandbox`），CLI 命令: `ebx`，Python 导入: `easy_sandbox`。

会话（Session）将沙箱与一个人类可读名称关联，方便在不同终端或时间点反复连接同一个沙箱。

---

## 会话概念

会话是沙箱 ID 与名称的映射关系。通过会话，你可以：

- 用名称代替 sandbox ID 来操作沙箱
- 在不同终端窗口中连接同一个沙箱
- 暂时断开后重新连接

### 会话数据模型

每个会话包含以下信息（`SessionInfo`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 会话名称 |
| `sandbox_id` | `str` | 关联的沙箱 ID |
| `template` | `str` | 使用的模板 |
| `created_at` | `datetime` | 创建时间 |
| `metadata` | `dict` | 元数据 |

---

## 本地存储

会话默认使用本地文件系统存储，由 `LocalSessionStore` 实现。

### 存储位置

```text
~/.ebx/sessions/
├── my-project.json       # 会话 "my-project"
├── my-project.json.lock  # 并发锁文件
├── dev-env.json          # 会话 "dev-env"
└── ...
```

每个会话保存为一个 JSON 文件，文件名由会话名称派生（非字母数字/短横/下划线的字符替换为 `_`）。

### 并发保护

文件读写通过文件锁保护：
- 优先使用 `filelock` 库（如已安装）
- 回退到 POSIX `fcntl` 锁（macOS/Linux）

---

## CLI 使用

### 启动会话

```bash
ebx session start my-project --template base --timeout 600
ebx session start dev-env --template base --env MY_KEY=value
```

会话启动时会创建一个新沙箱并记录映射关系。

### 连接会话

```bash
ebx session connect my-project
# 进入交互式 Shell
```

### 列出会话

```bash
ebx session list
# 显示所有本地会话及其状态
```

### 查看会话信息

```bash
ebx session info my-project
```

### 停止会话

```bash
# 停止并销毁沙箱
ebx session stop my-project

# 仅取消跟踪，不销毁沙箱
ebx session stop my-project --keep-alive
```

---

## SDK 使用

```python
from easy_sandbox.session.local import LocalSessionStore
from easy_sandbox.models.session import SessionInfo

# 创建存储实例
store = LocalSessionStore()  # 默认 ~/.ebx/sessions/

# 保存会话
session = SessionInfo(
    name="my-project",
    sandbox_id="sbx-xxxx",
    template="base",
)
await store.save("my-project", session)

# 加载会话
session = await store.load("my-project")
if session:
    print(f"Sandbox: {session.sandbox_id}")

# 列出所有会话
sessions = await store.list_all()

# 删除会话
await store.delete("my-project")
```

---

## 自定义存储位置

```python
store = LocalSessionStore(base_dir="/path/to/custom/sessions")
```

---

## 下一步

- [CLI 教程](cli-tutorial.md) — 完整 CLI 使用教程
- [配置参考](../reference/configuration.md) — 配置文件位置
