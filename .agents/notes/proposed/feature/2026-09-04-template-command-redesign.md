# Decision: template 命令批评与重构方向

Status: proposed
Task: #105

## Problem
现有 `ebx template` 子命令族存在多处设计缺陷：假设了不存在的中央 registry、命令间职责冗余、用户在无 repo 的情况下完全无法找到模板。这些问题会在首次公开发布时直接影响用户体验。

## Decision
记录现有问题并明确重构方向。

### 现有问题

1. **`ebx template list` 假设了不存在的中央 registry**：该命令调用 `GET /templates`（`protocol/template.py`），语义是"列出**我的**已创建模板"，但命名暗示"列出所有可用模板"。不存在公共模板目录/市场，用户第一次运行此命令大概率得到空列表。
2. **`ebx template delete` 与 `ebx template cache --clear` 职责冗余**：`delete` 删远程模板（`DELETE /templates/{id}`），`cache --clear` 清本地缓存。但从用户心智看，"删除模板"和"清除模板缓存"容易混淆，且 `delete` 是不可逆的破坏性操作。
3. **用户不给 repo 完全找不到模板**：没有 `ebx template search` 或"推荐模板"机制。`ebx template install` 需要显式的 `owner/repo` 或本地路径，没有发现入口。
4. **`ebx template cache` 只列文件路径**：不解析 `custom_commands`，无法离线打印"某模板有哪些命令+参数"。

### 重构方向

5. **`list` 只列本地已安装模板**：改为扫描 `~/.ebx/templates/` 并展示名称、版本、capabilities、custom_commands 概要。不发网络请求。
6. **`info <template>` 查单个模板详情**：本地优先，回落到远程 `GET /templates/{id}`。展示完整的 capabilities + custom_commands + args（含 type）。
7. **`install <source>` 从 GitHub repo 安装**：`ebx template install owner/repo`（GitHub release 资产）或 `ebx template install ./path`（本地目录）。这是唯一的模板获取入口。
8. **移除或重命名 `delete`**：考虑 `ebx template uninstall`（清本地缓存）+ `ebx template destroy`（删远程，需二次确认）。

## Alternatives considered
- **保持现状** — 用户首次体验差（`list` 空、找不到模板），公开发布前必须修。Rejected。
- **建设中央 registry** — 工作量大，当前模板规模不支持。暂不建设，用 GitHub repo 作为模板发现入口。
- **`ebx install`（顶层命令）** — 当前实现是 `ebx template install`（嵌套在 template 子命令下），ADR `minimal-template-repo.md` 的测试策略里写了 `ebx install` 但实际不存在。保持 `ebx template install` 避免顶层命名空间膨胀。

## Dependencies
- `cli/commands/template.py`（现有 template 子命令族）
- `api/capability.py`（本地模板发现）
- `2026-09-04-discovery-api-two-layer.md`（Layer 1 本地发现增强）

## Test Strategy
- `ebx template list` 扫描本地缓存，无网络请求，空缓存时给出友好提示。
- `ebx template info <name>` 展示 capabilities + custom_commands 详情。
- `ebx template install <source>` 从 GitHub 或本地路径安装到 `~/.ebx/templates/`。

## Acceptance criteria
- `list` 只展示本地已安装模板，不依赖中央 registry。
- `info` 展示单个模板的完整详情（含参数类型）。
- `install` 是唯一的模板获取入口。
- `delete` 的破坏性操作有二次确认。
- 实现后，此 ADR 从 `proposed/` 移至 `implemented/`。

## Evidence
- 用户反馈（会话记录）
- `.agents/evidence/research/2026-09-04-container-serve-boundary.md` §6.2（发现链分析）
