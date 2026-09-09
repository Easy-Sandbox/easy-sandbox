# Decision: Template Awesome — 社区沙箱模板索引

Status: proposed

## Problem
当前模板分发模式仅支持：(1) 本地 `examples/templates/` 目录下的内置模板；(2) 通过 `sbox template build-local` 手动构建推送。缺少一个社区驱动的模板发现和分发机制，用户无法：

1. 搜索和发现其他人创建的沙箱模板
2. 一键安装社区模板到本地
3. 将自己的模板发布到公共索引供他人使用

需要一个轻量级的社区模板注册中心，降低模板分享和复用的门槛。

## Decision
采用 **awesome-list + Git 索引文件** 模式，创建社区沙箱模板索引。

### 核心设计

1. **`awesome-templates.yaml` 索引文件**：仓库根目录下维护一个 YAML 索引文件，列出所有社区模板的元数据（名称、描述、作者、Git 仓库 URL、标签等）。任何人可通过 PR 添加自己的模板。

2. **模板元数据格式**：
```yaml
templates:
  - name: "data-science-notebook"
    description: "Jupyter notebook with pandas/numpy/matplotlib pre-installed"
    author: "community-user"
    repo: "https://github.com/user/sbox-data-science"
    tags: ["python", "data-science", "jupyter"]
    version: "1.0.0"
    capabilities: ["shell", "files", "code", "ports"]
```

3. **CLI 命令扩展**：
   - `sbox template search <keyword>` — 搜索社区模板索引
   - `sbox template install <name>` — 克隆模板到本地 `~/.sbox/templates/`
   - `sbox template publish` — 引导用户提交 PR 到索引文件

4. **分发机制**：
   - 索引文件托管在主仓库（或独立 awesome-sbox-templates 仓库）
   - 模板本身托管在作者的 Git 仓库中
   - `install` 命令执行 `git clone` 到本地缓存目录
   - 本地缓存目录与现有的 `~/.sbox/templates/` 模板解析目录一致

### 参考模式

- **awesome-docker** — curated list 模式，PR 驱动
- **Homebrew taps** — 公式索引 + 远程仓库分发
- **VS Code Extension Marketplace** — 集中索引 + 去中心化托管（远期参考）

## API Design
```yaml
# awesome-templates.yaml（索引文件格式）
version: "1"
templates:
  - name: "data-science-notebook"
    description: "Jupyter notebook sandbox with data science stack"
    author: "community-user"
    repo: "https://github.com/user/sbox-data-science"
    ref: "main"                    # Git ref（branch/tag）
    tags: ["python", "data-science", "jupyter"]
    capabilities: ["shell", "files", "code", "ports"]
    min_sbox_version: "0.1.0"     # 最低兼容 sbox 版本
```

```bash
# CLI 命令
sbox template search jupyter
# → data-science-notebook  Jupyter notebook with data science stack  [python, jupyter]

sbox template install data-science-notebook
# → Cloning https://github.com/user/sbox-data-science to ~/.sbox/templates/data-science-notebook

sbox template publish
# → 交互式引导：收集模板信息 → 生成 YAML 片段 → 提示用户提交 PR
```

```python
# api/template.py — 扩展方法
class TemplateManager:
    async def search_awesome(self, keyword: str) -> list[dict]: ...
    async def install_from_awesome(self, name: str) -> Path: ...
```

## Alternatives considered
- **集中式模板服务器（类似 npm registry）** — 需要维护服务器基础设施，MVP 阶段成本过高。Deferred to Phase 2。
- **将所有社区模板 vendored 到主仓库** — 仓库膨胀、版本管理困难、每个模板更新都需要主仓库发版。Rejected。
- **纯 GitHub Topics 标签发现** — 无结构化元数据、无法保证模板质量、搜索体验差。Rejected 作为唯一方式。
- **OCI Registry 分发模板（类似 Helm charts）** — 需要用户配置 registry 访问，门槛过高。Deferred。

## Dependencies
- `api/template.py`（扩展搜索和安装方法）
- `cli/commands/template.py`（新增 `search`/`install`/`publish` 子命令）
- `examples/templates/`（现有内置模板作为种子数据）
- Git CLI（`install` 命令依赖 `git clone`）

## Test Strategy
- 索引文件解析：YAML 格式校验、必填字段缺失报错、重复名称检测。
- `search` 命令：关键词匹配（名称 + 描述 + 标签）、无结果提示。
- `install` 命令：clone 到正确路径、已存在模板提示更新/覆盖。
- `publish` 引导：生成的 YAML 片段格式正确。

## Acceptance criteria
- `awesome-templates.yaml` 索引文件格式确定且有 JSON Schema 校验。
- `sbox template search/install/publish` 三个命令可用。
- 社区模板安装后可通过 `sbox create <template-name>` 直接使用。
- 贡献流程有清晰文档（如何提交 PR 添加模板）。
- 实现后，此 ADR 从 `proposed/` 移至 `implemented/`。

## Open questions
- 索引文件托管在主仓库还是独立仓库？
- 是否需要模板质量审核机制（CI 自动验证 template.yaml 格式）？
- 是否支持模板版本管理（同一模板多个版本）？
- 远期是否迁移到集中式模板服务器？
