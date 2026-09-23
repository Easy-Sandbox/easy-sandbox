# 模板目录（Templates Catalog）设计

> `examples/templates/` 是 Easy Sandbox 的**官方模板集合**，被刻意设计成
> 「一个 README + 一堆模板文件夹」的极简形态，以便**整份原样**抽出为独立仓库
> `awesome-easy-sandbox-templates`。本文档定义该目录的形态契约、发布流程、
> 主仓库与独立仓库之间的链接方式，以及让两侧都能跑的离线校验方法。
>
> 相关文档：[模板体系设计](./template-system.md)（模板分层与分发机制）、
> [CLI 设计](./cli-design.md)（`ebx install` / `ebx run` / `ebx exec`）、
> [能力模型](./template-system.md#关键设计要点)（capabilities 门控，见「关键设计要点」的能力模型条目；权威定义见 ADR `2026-09-03-capability-model.md`）。

---

## 1. 为什么是「README + 文件夹」

模板集合的索引方案有两条路：

| 方案 | 形态 | 问题 |
|------|------|------|
| 结构化清单 | `registry.json` / `index.json` / 多层 manifest | 清单与模板文件**双写**，必然漂移；抽仓库时要重写路径；贡献者要先学会清单格式 |
| **极简目录**（本方案） | `README.md` + 每模板一个文件夹 | 索引是**给人看的**，一致性由测试保证而非靠人肉同步 |

选择极简形态的理由：

1. **模板文件夹本身就是自描述的**。`template.yaml` 是唯一权威定义，
   `Dockerfile` 是可独立构建的等价产物，`README.md` 是人类说明。
   任何额外的 index 文件都是这三者的投影，投影就有失真风险。
2. **抽出为独立仓库是零成本操作**。`git filter-repo` 或直接 `cp -r` 即可，
   不需要改写任何路径引用——因为**没有任何文件引用绝对位置**。
3. **贡献门槛最低**。新增模板 = 复制一个文件夹、改三个文件、在总览表加一行。
4. **一致性可以机器保证**。见 [§5 离线校验](#5-离线校验让独立仓库能跑同样的检查)。

### 1.1 目录契约

```
examples/templates/                 ← 抽出后即独立仓库根
├── README.md                       ← 唯一索引（模板总览表 + 安装/使用/贡献指南 + schema）
├── browser-automation/
│   ├── template.yaml       ← 必需：权威定义
│   ├── Dockerfile                  ← 必需：与 YAML 等价的构建产物
│   └── README.md                   ← 必需：模板说明
├── claude-code/
├── codex/
├── deepseek-harness/
├── hermes-agent/
├── node-web/
├── openclaw/
├── python-hello/
├── qoder/
└── qwen-code/
```

硬性约束：

- **文件夹名 == `template.yaml` 的 `name` == 安装后的默认 `alias`**。
  三者一致，`api/capability.py::resolve_capabilities()` 才能在
  `~/.ebx/templates/` 里按名字反查到模板；否则 capabilities 会静默回落到
  `DEFAULT_CAPABILITIES`（只打 warning，不报错），是最难排查的一类故障。
- 命名 kebab-case，无空格、无下划线、无大写。
- 三个必需文件缺一不可，且不能为空。
- 索引表在 `README.md` 内，**不新增任何 json/yaml 清单文件**。

### 1.2 索引表字段

`README.md` 的「模板总览」表是 7 列，全部来自 YAML：

| 列 | 数据来源 |
|----|----------|
| 模板 | 文件夹名（链接到 `./<name>/`） |
| 描述 | `description` |
| 关键词 | `tags`（顺序敏感） |
| base 镜像 | `base` |
| resources | `resources.cpu` / `resources.memory` / `ports` |
| capabilities | `capabilities`（顺序敏感；`*` 号标注见下） |
| custom commands | `custom_commands` 的键 + 各自 `args`，形如 `` `run(task*)` ``，`*` = `required: true` |

「顺序敏感」是刻意的：测试做的是**列表相等**而不是集合相等，
这样表格能真实反映 YAML 的声明顺序，而不是被排序掩盖差异。

---

## 2. 发布流程（定义完成的标准）

模板集合的发布是一条**四段式流水线**，任何一段没过都不算完成：

```
①  离线校验 + 本地 install E2E 全绿
        │   python -m pytest tests/test_templates/ -q
        ▼
②  用户 push 到 GitHub（推 git tag / 分支即可，无需发 Release）
        │   （人工步骤，Agent 不代为执行 git push）
        ▼
③  真实 ebx install <owner>/<repo>//<template> --registry-type github 端到端通过
        │   （真网络、真 GitHub API、真 ~/.ebx/templates 缓存）
        ▼
④  才算完成
```

### 2.1 阶段①：本地 install 测试（Agent 的硬 gate）

`tests/test_templates/test_local_install.py` 用 `CliRunner` 驱动真实 CLI：

```bash
python -m pytest tests/test_templates/ -q
```

它跑的是**真实代码路径**：`RegistryClient.resolve()` → `RegistryClient.fetch()` →
`load_template_from_yaml()` → `SandboxTemplate.to_dockerfile()` → 构造
`POST /templates` 请求体。只在两处打桩：

| 被打桩的边界 | 原因 |
|--------------|------|
| `transport.config.load_config` / `transport.auth.create_auth_provider` / `transport.http.HttpClient` | 需要真实后端与凭据 |
| `httpx.AsyncClient.get` | 需要真实网络（GitHub tarball 字节） |

注意 `_download_and_extract()` **没有**被打桩——tarball 顶层目录剥离与 `//subdir`
子目录抽取、路径穿越防护都是被真实执行的，喂给它的是内存里现造的
GitHub 风格 .tar.gz 副本（`build_repo_tarball()`）。因此「ref 解析 → 下载 → 解压
→ 缓存 → 加载 → 生成 Dockerfile → 提交构建」整条链路除了 HTTP 字节本身，全部走过真实代码。

整个模块还挂了一个 `socket.getaddrinfo` / `socket.create_connection` 绊线
（autouse fixture），任何意外的域名解析都会让测试直接失败——「全离线」是**可执行**的
承诺，不是注释里的口号。

> 绊线刻意**不**patch `socket.socket`：asyncio 的 self-pipe（`socketpair()`）
> 依赖它，patch 掉会让 `run_sync()` 里的 `asyncio.run()` 直接崩。
> `getaddrinfo` 与 `create_connection` 才是所有出站 HTTP 的必经收口。

### 2.2 阶段②：人工 push（tag / 分支即可）

由用户执行，Agent 不碰：

```bash
# 独立仓库形态
git remote add templates git@github.com:<owner>/awesome-easy-sandbox-templates.git
git subtree push --prefix=examples/templates templates main
git tag v1.0.0 && git push origin v1.0.0     # 推一个 git tag 即可
```

**无需发 GitHub Release**：`RegistryClient` 走 GitHub tarball API
（`/repos/{owner}/{repo}/tarball[/{ref}]`）按 tag/branch/sha 拉取，GitHub 会
自动把 ref 解析为 tag/branch/sha；不带 `@ref` 时拉取默认分支。只有默认分支、
只推 git tag、甚至仅用 commit sha 都能 `ebx install`。

### 2.3 阶段③：真实 GitHub 端到端

发布后必须用**真网络**验证一次，覆盖阶段①无法覆盖的部分
（真实 API 响应结构、真实 tarball 顶层前缀、真实鉴权、真实缓存目录）：

```bash
# 清掉缓存，确保不是命中阶段①留下的东西
ebx template cache --clear

# 单模板（本集合的标准用法）
ebx install <owner>/awesome-easy-sandbox-templates//node-web \
  --registry-type github --registry-url https://github.com

# 锁版本
ebx install <owner>/awesome-easy-sandbox-templates//node-web@v1.0.0 \
  --registry-type github

# 验证缓存落地
ebx template cache
ls ~/.ebx/templates/<owner>/awesome-easy-sandbox-templates/v1.0.0/node-web

# 验证 capabilities / custom_commands 真的被解析到（不是回落到默认值）
ebx create --template node-web
ebx run <sandbox_id> start
ebx exec <sandbox_id> "node -v"
ebx kill <sandbox_id> -y
```

`ebx run <sandbox_id> start` 能成功，就证明 `custom_commands` 从缓存里的
YAML 正确解析出来了——这是整条链路最有信息量的一次断言。

### 2.4 为什么整仓库 ref（不带 `//`）不适用

```bash
ebx install <owner>/awesome-easy-sandbox-templates --registry-type github
```

会把**仓库根**解到缓存目录，而仓库根只有 `README.md` 与各模板文件夹，
没有自己的 `template.yaml`，install 会以
`No template.yaml found in ...` 失败。

这是**设计如此**而非缺陷：本集合是多模板仓库，`//<template>` 才是正确用法。
`test_github_install_whole_repo_without_subdir_fails` 把这条行为钉住了，
`README.md` 的安装章节也明确写了子目录语法。只有「一个仓库 = 一个模板」时
整仓库 ref 才成立。

---

## 3. 主仓库 ↔ 独立仓库的链接方式

两种形态并存，靠**引用格式**而非文件内容区分：

### 3.1 留在主仓库内（当前状态）

```bash
ebx install ./examples/templates/node-web --registry-type local
```

主仓库的关联点：

| 位置 | 关联方式 | 是否随抽出而失效 |
|------|----------|------------------|
| `README.md`（根）→ `examples/templates/` | 相对链接 | 抽出后需改指向独立仓库 URL |
| `examples/README.md` 目录树 | 相对路径说明 | 抽出后需删该段 |
| `src/easy_sandbox/agent/infer.py::TEMPLATE_CATALOG` | **按模板名**引用，不含路径 | ❌ 不失效 |
| `examples/templates/README.md` 内的 schema 链接 | `../../src/...` 相对链接 | 抽出后需改为主仓库 blob URL |
| `tests/test_templates/` | `parents[2] / "examples" / "templates"` | 抽出后按 §5.3 调整 |

关键设计：**`TEMPLATE_CATALOG` 只按名字引用模板，不引用路径**。
所以模板目录被抽走后，自然语言推断（`ebx create "……"`）依然工作——
它推荐的是模板名，用户拿到名字后自行 `ebx install <owner>/<repo>//<name>`。

### 3.2 抽出为独立仓库后

主仓库侧只保留**指针**，不再持有内容：

````markdown
<!-- 主仓库 README.md -->
## Templates

开箱即用的沙箱模板见独立仓库
[awesome-easy-sandbox-templates](https://github.com/<owner>/awesome-easy-sandbox-templates)：

```bash
ebx install <owner>/awesome-easy-sandbox-templates//node-web --registry-type github
```
````

同步方式二选一：

| 方式 | 说明 | 适用 |
|------|------|------|
| `git subtree push --prefix=examples/templates` | 主仓库仍是唯一编辑入口，独立仓库是发布产物 | 模板改动频繁、由核心团队维护 |
| `git submodule` / 直接删除主仓库副本 | 独立仓库是唯一入口，主仓库只留链接 | 想接受社区 PR、模板生态外溢 |

**当前推荐 subtree push**：`tests/test_templates/` 依赖主仓库的
`easy_sandbox` 包（真实加载器、真实 CLI），submodule 化后离线校验会分裂成两套。

### 3.3 版本对齐

独立仓库的 git tag/ref 与每个模板 `template.yaml` 的 `version` 字段
是**两个独立维度**：

- git tag/ref（`v1.0.0`）= 整个集合的快照版本，用于 `@ref` 锁定与缓存分目录。
- 模板 `version` = 单个模板的语义版本，用于展示与兼容性判断。

约定：集合推新 git tag 时，若有模板内容变更则同步 bump 该模板的 `version`。
缓存路径按 ref 分目录（`~/.ebx/templates/<owner>/<repo>/<ref|default>/`），
所以两个维度的不一致不会造成缓存串味。

---

## 4. `ebx run` vs `ebx exec` 的边界

模板集合的存在让这条边界变得有意义，因此写进设计文档而非只写在 README：

| | `ebx run <id> <command_name>` | `ebx exec <id> "<shell>"` |
|---|---|---|
| 命令来源 | 模板 `custom_commands` 声明 | 调用方临时拼写 |
| 参数模型 | `--arg k=v` 填充 `{placeholder}`，`shlex.quote` 自动转义 | 无，全靠自己 |
| `cwd` / `env` / `timeout` | 模板声明，调用方不重复指定 | `--cwd` / `--timeout` 显式传，`env` 不可传 |
| 可发现性 | `sandbox.list_commands()` 可枚举 | 不可枚举 |
| 失败模式 | 命令名不存在 / 必填参数缺失 / 占位符未填充 → 明确 `ValueError` | shell 语法错误、非零退出码 |
| 依赖 | 需要 capabilities 解析成功（见 §1.1 命名约束） | 只需 `shell` capability |

设计意图：`custom_commands` 是模板作者对「这个环境应该怎么用」的**声明式封装**，
把 `cwd`/`env`/`timeout`/转义这些易错细节从每个调用点收敛到模板里一次。
`ebx exec` 保留给一次性探索与调试。两者不是替代关系。

---

## 5. 离线校验：让独立仓库能跑同样的检查

### 5.1 校验清单

`tests/test_templates/test_template_catalog.py` 逐模板参数化断言：

| # | 契约 | 说明 |
|---|------|------|
| a | YAML 可被**真实加载器**解析 | `utils.registry.load_template_from_yaml()` → `SandboxTemplate`，不复刻解析逻辑 |
| b1 | 必需字段齐全 | `name` / `version` / `description` / `base` / `author` / `tags` 显式声明（模型有默认值，但发布的模板必须写出来） |
| b2 | capabilities 合法 | 全部落在 `STANDARD_CAPABILITIES`；显式声明；无重复；`ports` capability 与顶层 `ports:` 列表互为充要 |
| b3 | custom_commands 结构合法 | 命令名 kebab/identifier；`cmd` 非空；`timeout > 0`；`cwd` 绝对路径；`env` 为 `str→str`；`{placeholder}` 与 `args` **双向**覆盖；`required: true` 不得同时有 `default`，非必填**必须**有 `default` |
| c | 三个必需文件存在且非空 | `template.yaml` / `Dockerfile` / `README.md`；并拦截 `sandbox_template.yaml`、`dockerfile` 之类拼写变体 |
| d | 与 `TEMPLATE_CATALOG` 对账 | 无孤儿、无缺失（见 §5.2） |
| e | `README.md` 索引表与 YAML 逐字段一致 | 描述/关键词/base/cpu/memory/ports/capabilities/custom commands；外加 capabilities 分布矩阵；外加安装与 schema 章节存在性 |
| f | `Dockerfile` 的 `FROM` == YAML `base` | 防止手写 Dockerfile 与 YAML 各说各话 |

### 5.2 对账规则（契约 d）

`TEMPLATE_CATALOG`（`src/easy_sandbox/agent/infer.py`）与磁盘文件夹
不是 1:1，因此用两张显式白名单把「有意为之的不对称」写死，
剩下任何偏差都是 bug：

```python
# 由平台内置镜像 / 在线目录提供，本集合刻意不含文件夹
PLATFORM_ONLY_TEMPLATES = {"base", "code-interpreter", "python-data-science", "full-stack"}

# 仅作示例与测试夹具，不参与自然语言推断
EXAMPLE_ONLY_TEMPLATES = {"python-hello"}
```

四条断言：

1. `TEMPLATE_CATALOG` 的每一项，要么有对应文件夹，要么在 `PLATFORM_ONLY_TEMPLATES`（**无缺失**）。
2. 每个文件夹，要么在 `TEMPLATE_CATALOG` 里，要么在 `EXAMPLE_ONLY_TEMPLATES`（**无孤儿**）。
3. `PLATFORM_ONLY_TEMPLATES` 的名字**不得**出现为文件夹（避免遮蔽平台内置模板，
   `utils.registry.BUILTIN_TEMPLATES` 会把裸名 `base` 直接判为内置而跳过拉取）。
4. 有对应文件夹的条目，其 `cpu` / `memory` / `ports` 必须与 YAML 的
   `resources` / `ports` 一致（推断引擎给出的资源默认值不能和模板真实声明打架）。

> 刻意**不**断言「catalog keywords 必须包含 YAML tags」。
> keywords 是面向自然语言匹配的**人类措辞**（`node.js`、`web服务`、`做网站`），
> tags 是面向检索的**规范标识符**（`nodejs`、`web`、`api`），两者本就不该强行对齐；
> 强行断言会逼着 `infer.py` 塞进一批没人会说的关键词，反而降低推断质量。

### 5.3 在独立仓库里跑同一套检查

`tests/test_templates/` 只依赖 `pydantic` + `pyyaml` + `click` + `pytest` +
`easy_sandbox` 包本身，不依赖主仓库任何其它资产。抽出时：

**步骤 1 — 复制测试**

```bash
mkdir -p tests/test_templates
cp <main-repo>/tests/__init__.py tests/__init__.py
cp <main-repo>/tests/test_templates/*.py tests/test_templates/
```

（`tests/__init__.py` 与 `tests/test_templates/__init__.py` 都必须存在，
测试模块用的是包内相对导入 `from .conftest import ...`。）

**步骤 2 — 改路径常量**

`tests/test_templates/conftest.py` 顶部只有一处需要动：

```python
# 主仓库：tests/test_templates/conftest.py → parents[2] 是仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "examples" / "templates"

# 独立仓库：模板文件夹就在仓库根下
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT                      # ← 只改这一行
```

**步骤 3 — 装 SDK**

独立仓库 CI 需要装 `easy-sandbox[cli]`（测试要用真实加载器与真实 CLI）：

```yaml
# .github/workflows/validate.yml
name: validate-templates
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install "easy-sandbox[cli]>=0.1" pytest
      - run: python -m pytest tests/test_templates/ -q
```

**步骤 4 — 关掉需要主仓库上下文的两条断言**

契约 d（`TEMPLATE_CATALOG` 对账）依赖 `easy_sandbox.agent.infer`，
装好 SDK 就能跑，无需改动。
契约 e 中对 `../../src/...` 相对链接的引用只出现在 README 文本里，
测试不校验链接可达性，因此同样无需改动。

> 结论：**独立仓库跑的是同一份测试文件，只改 `TEMPLATES_DIR` 一行。**

### 5.4 本地快速验证

```bash
# 全量（约 400 个参数化用例，2~3 秒）
python -m pytest tests/test_templates/ -q

# 只看目录契约
python -m pytest tests/test_templates/test_template_catalog.py -q

# 只看 install 端到端
python -m pytest tests/test_templates/test_local_install.py -q

# 只验某一个模板
python -m pytest tests/test_templates/ -q -k node-web

# 手动离线加载一次（不经过 CLI）
python -c "
from pathlib import Path
from easy_sandbox.utils.registry import load_template_from_yaml
t = load_template_from_yaml(Path('examples/templates/node-web/template.yaml'))
print(t.name, t.base, t.capabilities, list(t.custom_commands))
print(t.to_dockerfile())
"
```

---

## 6. 不做的事（明确边界）

| 不做 | 原因 |
|------|------|
| 不引入 `registry.json` / `index.json` / 多层 manifest | 双写必然漂移；索引由 README + 测试保证 |
| 不在测试里真实构建 docker 镜像 | 需要 docker daemon，破坏离线与 CI 可复现性；`Dockerfile` 只校验 `FROM` 与 YAML 一致 |
| 不在测试里真实调用平台 `POST /templates` | 需要凭据与配额；build 边界一律打桩 |
| 不由 Agent 执行 `git push` / 发 Release | 发布是人工决策点，见 §2.2 |
| 不重命名 / 移动任何既有模板文件夹 | `TEMPLATE_CATALOG` 与多份文档按名字引用，改名是破坏性变更 |
| 不把 `TEMPLATE_CATALOG` 的 keywords 与 YAML tags 强行对齐 | 见 §5.2 末尾说明 |
