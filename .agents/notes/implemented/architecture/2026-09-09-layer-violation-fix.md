# Decision: L3→L2 层级违规修复与错误码重分配

Status: implemented

## Problem
项目分层架构（L0 Models/Utils → L1 Transport → L2 Protocol → L3 API）存在多处违规，导致循环依赖风险和架构退化：

1. **`session/__init__.py` 上向依赖**：`session` 模块（与 L1 同级）导入了 `api.session_manager.SessionManager`（L3 层），形成低层→高层的反向依赖。
2. **错误类型位置错误**：`TemplateBuildError` 和 `TemplateBuildTimeoutError` 定义在 `protocol/template.py`（L2 层），但错误类型属于 L0 Models 层的职责。
3. **错误码冲突**：原错误码 E7001/E7002 与已有的 `TemplateNotFoundError`（E7001）/ `TemplateParseError`（E7002）冲突。
4. **CLI 命令组缺失**：`cli/commands/` 目录缺少 `session.py`、`secret.py`、`skill.py`、`auth.py` 四个命令模块。

## Decision
### 1. 移除 session 上向依赖

从 `session/__init__.py` 移除 `SessionManager` 导入，`__all__` 仅暴露 L0/L1 级别的 `SessionStore`（base）和 `LocalSessionStore`（local）。用户需要 `SessionManager` 时从 `api.session_manager` 直接导入。

### 2. 错误类迁移到 models/errors.py

将 `TemplateBuildError` 和 `TemplateBuildTimeoutError` 从 `protocol/template.py` 迁移到 `models/errors.py`（L0 层），使所有异常类型集中在错误模块中。

### 3. 错误码重分配

- `TemplateBuildError`: E7001 → **E7010**
- `TemplateBuildTimeoutError`: E7002 → **E7011**

E7010+ 段预留给 Template Build 相关错误，与已有的 E7000–E7003（TemplateError/TemplateNotFoundError/TemplateParseError/TemplateValidationError）不冲突。

### 4. CLI 命令组补齐

新增四个 CLI 命令模块：
- `cli/commands/auth.py` — 认证管理（login/logout/status）
- `cli/commands/session.py` — 会话管理（list/save/restore/delete）
- `cli/commands/secret.py` — 密钥管理（set/get/list/delete）
- `cli/commands/skill.py` — 技能管理（list/install/remove/run）

## API Design
```python
# session/__init__.py — 修复后
from easy_sandbox.session.base import SessionStore
from easy_sandbox.session.local import LocalSessionStore

__all__ = ["SessionStore", "LocalSessionStore"]
# 不再导入 SessionManager（L3 层）

# models/errors.py — 新增错误码段
# --- Template Build Errors (E7010+) ---
class TemplateBuildError(SandboxError):
    """Template build failed."""
    code = "E7010"

class TemplateBuildTimeoutError(SandboxError):
    """Template build timed out."""
    code = "E7011"
```

## Alternatives considered
- **在 session/__init__.py 中使用 TYPE_CHECKING 惰性导入** — 运行时仍不可用，且给使用者造成"可以导入"的误导。Rejected。
- **保持 E7001/E7002 错误码不变** — 与 `TemplateNotFoundError(E7001)` 和 `TemplateParseError(E7002)` 冲突，破坏错误码唯一性。Rejected。
- **在 protocol 层保留错误定义，models 层 re-export** — 违反"错误类型统一归属 models/errors.py"的惯例，增加查找复杂度。Rejected。

## Dependencies
- `models/errors.py`（错误类定义的统一位置）
- `protocol/template.py`（消费 `TemplateBuildError`/`TemplateBuildTimeoutError`）
- `session/__init__.py`（公共 API 导出）
- `cli/main.py`（注册新增命令组）

## Test Strategy
- 验证 `session/__init__.py` 不包含任何 `api` 层导入（Grep 验证）。
- 验证 `TemplateBuildError.code == "E7010"` 和 `TemplateBuildTimeoutError.code == "E7011"`。
- 验证所有 E7xxx 错误码无冲突（E7000–E7003 + E7010–E7011 + E7020–E7022）。
- 验证四个新增 CLI 命令组可通过 `ebx <group> --help` 正常加载。

## Acceptance criteria
- `session/__init__` 仅暴露 `SessionStore` 和 `LocalSessionStore`，无 L3 层导入。
- `TemplateBuildError`/`TemplateBuildTimeoutError` 定义在 `models/errors.py`，错误码分别为 E7010/E7011。
- `cli/commands/` 包含 `auth.py`、`session.py`、`secret.py`、`skill.py` 四个完整命令模块。
- Grep `from easy_sandbox.api` 在 `session/`、`models/`、`protocol/` 目录下 = 0 匹配。

## Files changed
- `session/__init__.py` — 移除 `SessionManager` 导入
- `models/errors.py` — 新增 `TemplateBuildError(E7010)`、`TemplateBuildTimeoutError(E7011)`
- `protocol/template.py` — 错误类改为从 `models.errors` 导入
- `cli/commands/auth.py` — 新建
- `cli/commands/session.py` — 新建
- `cli/commands/secret.py` — 新建
- `cli/commands/skill.py` — 新建
