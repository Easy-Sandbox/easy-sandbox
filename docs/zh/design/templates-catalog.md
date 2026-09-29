# 模板目录（Templates Catalog）设计

> 模板目录采用**单一事实来源（SSOT）**架构：官方与社区模板的内容、机器可读索引
> （`awesome-templates.yaml`）、发布与 CI 全部收敛到独立仓库
> [`Easy-Sandbox/awesome-templates`](https://github.com/Easy-Sandbox/awesome-templates)。
> 主仓库**不再维护可发布模板集合**，仅在 `examples/templates/` 保留一个最小
> `python-hello` **离线测试夹具（fixture）**，并显式标记为 fixture。
>
> 相关文档：[模板体系设计](./template-system.md)（模板分层与分发机制）、
> [CLI 设计](./cli-design.md)（`ebx template search` / `install` / `deploy`）。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│  Easy-Sandbox/awesome-templates（唯一真源）                      │
│  ├── awesome-templates.yaml   ← 机器可读索引（search/install 数据源）│
│  ├── README.md / CONTRIBUTING.md  ← 人类索引 + 贡献规范           │
│  ├── <template>/              ← 模板内容（template.yaml + Dockerfile
│  │                               + README.md[+ commands.py]）    │
│  ├── tests/                   ← 目录/索引一致性离线校验（308 用例） │
│  └── .github/workflows/ci.yml ← Py3.10–3.13 矩阵 CI              │
└─────────────────────────────────────────────────────────────────┘
          ▲ raw.githubusercontent.com（CDN，无 API 限流）
          │ fetch_index()：缓存 ~/.ebx/index/ + ETag 条件请求
┌─────────┴───────────────────────────────────────────────────────┐
│  主仓库 easy-sandbox                                             │
│  ├── src/easy_sandbox/utils/template_index.py  ← 远程索引客户端   │
│  ├── src/easy_sandbox/cli/commands/template.py ← search/install  │
│  ├── examples/templates/python-hello/          ← 最小离线夹具     │
│  └── tests/（test_templates / test_utils / test_cli）← 全离线    │
└─────────────────────────────────────────────────────────────────┘
```

**职责划分**：

| 资产 | 归属 | 说明 |
|------|------|------|
| 官方/社区模板内容 | 真源仓库 | 每个目录 `template.yaml` + `Dockerfile` + `README.md`（需要服务端命令时加 `commands.py`） |
| 机器可读索引 | 真源仓库根 `awesome-templates.yaml` | `search` / `install` 的唯一数据源；主仓库**不存在**同名文件 |
| 发布与版本 | 真源仓库 git tag / 分支 | 条目 `ref` 字段可锁定版本；无需 GitHub Release |
| 目录一致性校验 | 真源仓库 `tests/` + CI | 索引 ↔ 文件夹 ↔ README 表格逐字段对账 |
| 离线开发夹具 | 主仓库 `examples/templates/python-hello/` | 仅供主仓库单测/集成测试离线运行，**禁止**在此新增可发布模板 |
| 索引客户端与降级行为 | 主仓库 `utils/template_index.py` | 缓存、条件请求、限流/断网降级 |

### 1.1 为什么不用「主仓库副本 + 定时同步」

早期方案让主仓库持有完整模板副本、通过 `git subtree push` 发布到独立仓库。
该方案有两个结构性问题：

1. **双写必然漂移**：Qwen 参数契约（`max_turns` → `max_session_turns`）曾在两侧
   出现分歧，就是双副本的直接后果。
2. **用户拿到的是过期副本**：CLI 内置的模板清单只能随 SDK 版本发布更新，
   社区模板必须等新版本才能被发现。

收敛后：内容只有一个写入口（真源仓库 PR），发现只有一条路径
（远程索引），主仓库的 SDK 发布节奏与模板演进完全解耦。

---

## 2. 机器可读索引（`awesome-templates.yaml`）

```yaml
schema_version: 1
templates:
  - name: node-web                       # 必填；唯一；kebab-case
    description: "Node.js Web 服务运行环境"  # 人类可读描述（搜索命中源）
    repo: https://github.com/Easy-Sandbox/awesome-templates  # 必填；仅支持 github.com
    path: node-web                       # 仓库内子目录；省略则整个仓库是一个模板
    ref: v1.0.0                          # 可选；锁定 tag/branch/sha
    tags: [nodejs, web, express, api]    # 搜索标签
    author: Easy-Sandbox
    capabilities: [shell, files, code, ports]
    status: official                     # official | community | experimental
```

约定：

- **`schema_version`**：索引格式版本，当前为 `1`。缺失按 1 处理（向后兼容）；
  比客户端支持版本更新时**明确报错**并提示升级 SDK，绝不静默误读。
- **`repo`**：仅接受 `github.com` 的 `owner/repo` 或完整 URL（解析时归一化）。
- **`path` / `ref` 组合**：条目合成为 Terraform 风格的
  `owner/repo//path@ref` 引用（`TemplateIndexEntry.install_ref`），直接交给
  `RegistryClient.resolve()`；省略 `path` 时退化为 `owner/repo`。
- **`name` 唯一**：重复条目在解析期即报错，避免解析结果依赖顺序。
- 契约校验由真源仓库 `tests/test_index.py` 保证：每个文件夹恰好一条索引、
  字段与 `template.yaml` 逐项一致、`install_ref` 可被 registry 客户端解析。

---

## 3. 远程索引客户端行为（`utils/template_index.py`）

### 3.1 默认位置与覆盖

| 项 | 值 |
|----|-----|
| 默认索引 URL | `https://raw.githubusercontent.com/Easy-Sandbox/awesome-templates/main/awesome-templates.yaml` |
| 环境变量覆盖 | `EBX_TEMPLATE_INDEX_URL`（HTTP(S) URL 或本地文件路径） |
| CLI 覆盖 | `ebx template search/install --index-url <URL或路径>` |
| 认证 | `--token` > `GITHUB_TOKEN` > 持久化 `github_token`（`ebx config set github_token`；私有镜像、提升限流额度） |

选择 `raw.githubusercontent.com` 而非 `api.github.com` 是刻意的：raw 文件由 CDN
提供服务，**不受** API 匿名 60 次/小时的限流约束；本地文件路径则让企业内网镜像
与完全离线的部署成为一等公民。

### 3.2 缓存与条件请求

- 缓存目录 `~/.ebx/index/`（与 `~/.ebx/templates/` 隔离，避免被误认为已安装模板）；
  文件为索引正文 + `awesome-templates.meta.json`（`source_url` / `etag` / `fetched_at`）。
- TTL `INDEX_MAX_AGE_SECONDS = 3600`：新鲜缓存**不发网络请求**（`search`/`install` 的
  常规路径零网络开销）。
- 过期后发送 `If-None-Match` 条件请求；`304` 仅刷新元数据时间戳，索引正文复用缓存。
- `--refresh` / `force=True` 绕过缓存强制拉取。
- 缓存损坏（不可解析）时丢弃并重新拉取，不把坏数据当作降级输入。

### 3.3 降级行为矩阵（明确、可预期）

| 场景 | 有缓存 | 无缓存 |
|------|--------|--------|
| 网络不可达（DNS/超时/拒连） | 过期缓存 + `stale=True` + warning「使用缓存的索引」 | `NetworkError`，建议检查网络 / `GITHUB_TOKEN` / `--index-url` |
| GitHub 限流（403 且 `X-RateLimit-Remaining: 0`，或 429） | 同上 + warning 提示 `GITHUB_TOKEN` / `ebx config set github_token` | `GitHubRateLimitError`（E5000），包含经官方核验的 fine-grained PAT 预填 URL、`ebx config set github_token` / `GITHUB_TOKEN` 修复建议、`--token` 泄漏提醒与镜像提示；交互终端下还会引导一次性脱敏配置并只重试一次 |
| `404` | 落入通用网络错误路径 | `NetworkError`，suggestion 提示校验索引 URL（`--index-url`） |
| 服务端错误（5xx） | 过期缓存 + warning | `NetworkError` |
| 其他非 2xx | 过期缓存 + warning | `NetworkError`，报告具体状态码 |
| `schema_version` 过新 | 不降级 | `TemplateParseError`，提示 `pip install -U easy-sandbox` |
| 索引无 `templates` 列表 / 非法 YAML | 不降级 | `TemplateParseError`（含来源 URL） |

降级呈现统一走 `TemplateIndex.stale` + `notice` 两个字段：CLI 在结果前打印
warning，退出码保持成功——过期的索引仍然可用，只是可见地陈旧。

---

## 4. CLI 行为（`ebx template search` / `install`）

### 4.1 `ebx template search <query>`

- 查询远程索引，按 `name` / `description` / `tags` / `author` 做子串匹配；
  `--tag` / `--status` 精确过滤；`--refresh` 强制刷新；`-j` 输出 JSON。
- 输出表格（Name / Description / Tags / Status）+ 安装提示
  `Install one with: ebx template install <name> (index: <source_url>)`。
- 降级时先打印 `notice` warning 再输出结果。

### 4.2 `ebx template install <name>` 的裸名解析顺序

```
<name> 是本地路径？           → 直接使用（不打桩、不触网）
<name> 是内置模板？           → BUILTIN_TEMPLATES = {base, code-interpreter-v1}
                              （平台镜像，免拉取，不触网络索引）
<name> 形如 owner/repo[//path][@ref]？ → 直接交给 RegistryClient（不查索引）
否则（裸名）                  → 查询远程索引：
                                命中 → 得到 install_ref（可能带 ref 锁定）→ 继续常规安装
                                未命中且缓存非 stale → force 刷新一次给新发布模板机会
                                仍未命中 → TemplateNotFoundError
                                  suggestion: 'ebx template search' / 直接 owner/repo//subdir
```

命中索引时打印 `Resolved '<name>' via the template index: <owner>/<repo>//<path>[@ref]`，
让用户对最终拉取的来源与版本可审计。

### 4.3 版本锁定与缓存分目录

`ref` 锁定（条目声明或用户显式 `@ref`）最终体现在缓存路径
`~/.ebx/templates/<owner>/<repo>/<ref|default>/<path>`，不同 ref 的模板互不串味。
未声明 `ref` 的条目跟随真源仓库默认分支——「跟随最新」与「锁定版本」都是显式选择。

---

## 5. 主仓库 fixture 契约（`examples/templates/`）

`examples/templates/` 是**测试资源目录**，不是模板目录：

- 只允许存在 `python-hello`（`EXPECTED_FIXTURE_TEMPLATES`），任何新增文件夹都会
  让 `tests/test_templates/test_template_catalog.py::TestFixtureBoundary` 直接失败。
- 三层显式标记，防止被误认为可发布模板：
  1. 目录级 `README.md` 声明「本目录不是模板发布真源」+ 真源链接 + 远程安装命令；
  2. `python-hello/template.yaml` 顶部 `FIXTURE` banner 注释；
  3. `python-hello/README.md` fixture 提示块。
- fixture 自身仍须通过全部模板契约校验（真实加载器解析、capabilities 合法、
  Dockerfile 有 `FROM`、custom_commands 占位符与 args 双向覆盖等）——它代表
  「模板规范」的可执行样本。
- `python-hello` 同时被多个集成测试与 golden 文件引用（CLI help、workflow E2E），
  因此**不删除、不改名**。

---

## 6. 测试策略（离线可运行是第一约束）

### 6.1 主仓库（全部离线，无网络）

| 套件 | 覆盖 |
|------|------|
| `tests/test_utils/test_template_index.py` | 索引解析/校验、`install_ref` 构造、缓存生命周期（新鲜短路/强制刷新/304）、降级矩阵（断网/限流/404/5xx/损坏缓存）、token 与 env 覆盖 |
| `tests/test_cli/test_template_index_commands.py` | `search` 输出/过滤/JSON/降级 notice/参数透传；`install` 裸名经索引解析、`@ref` 锁定、内置名不触索引、未命中报错与强制刷新 |
| `tests/test_templates/test_template_catalog.py` | fixture 边界（唯一性/标记/README 契约）+ fixture 的 YAML/Dockerfile/custom_commands 契约 |
| `tests/test_templates/test_local_install.py` | 真实 CLI install 链路（本地 tarball 打桩，`socket` 绊线保证零外网） |

网络拦截全部通过 `pytest-httpx`（`httpx_mock`）或 `fetch_index` 打桩完成；
无网络环境（CI 沙箱、企业内网）下全量单测可运行。

### 6.2 真源仓库（自测试，随模板内容演进）

`tests/test_catalog.py`（32 用例）+ `tests/test_index.py`（11 用例）+
`tests/test_commands_e2e.py`（10 用例）：目录契约、索引对账、README 表格
逐字段比对、qwen-code `max_session_turns` 契约守卫等。CI 在 Python
3.10–3.13 矩阵上运行，依赖 `requirements-dev.txt`（`easy-sandbox[cli]` git main +
pytest + pyyaml）。

> 真源仓库与主仓库测试的分工：**内容正确性**归真源仓库（模板改动必须同 PR 更新
> 索引与 README 表格）；**客户端行为**归主仓库（缓存、降级、解析顺序）。
> 两侧都不依赖对方的仓库布局，只通过「索引文件格式」这一公开契约耦合。

---

## 7. 发布与贡献流程

1. **贡献**：向真源仓库提 PR（`CONTRIBUTING.md` 定义模板解剖、capability 分组规则、
   本地开发流程）；PR 必须同步更新 `awesome-templates.yaml` 与 README 表格，
   CI 离线校验全绿。
2. **发布**：合并到 `main` 即生效（索引随仓库内容原子更新）；需要稳定引用时打
   git tag（`v1.0.0`），用户通过 `@v1.0.0` 锁定。**无需 GitHub Release**——
   `RegistryClient` 走 tarball API，tag/branch/sha 均可解析。
3. **消费**：用户 `ebx template search` 发现 → `ebx template install <name>` 安装；
   新发布模板在缓存未命中时会被一次强制刷新立即发现，无需等待 TTL。
4. **回滚**：索引条目 `ref` 指向已知良好版本；紧急下线移除条目（新用户不可见，
   已安装缓存不受影响）。

---

## 8. 不做的事（明确边界）

| 不做 | 原因 |
|------|------|
| 不把模板内容镜像回主仓库 | 双写是本设计要消除的根本问题 |
| 不在主仓库保留 `awesome-templates.yaml` 副本 | 索引唯一真源在真源仓库；主仓库只有客户端 |
| 不让 SDK 发布成为模板上新的前置条件 | 索引机制已解耦两侧发布节奏 |
| 不在单测里真实访问 GitHub | 离线可运行是第一约束；网络测试属集成/手工验证 |
| 不自动跨仓库同步（subtree/submodule/定时任务） | 真源仓库即唯一入口，无需同步动作，自然无同步漂移 |
| 不由 Agent 执行 `git push` | 发布是人工决策点 |
| 不删除/改名 `python-hello` fixture | 集成测试与 golden 文件按路径引用，删除即断裂 |
| 不回退 `max_session_turns` 契约 | 任务 181 确立的参数名由两侧测试守卫（真源 `test_commands_e2e.py`） |
