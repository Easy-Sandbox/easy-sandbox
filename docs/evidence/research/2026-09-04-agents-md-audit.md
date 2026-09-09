# AGENTS.md 对抗审计报告

**审计日期:** 2026-09-04  
**审计人:** Eric (研究分析 Agent)  
**关联任务:** #110  
**文档版本:** Jimmy (#96) 创建的初始版本

---

## 1. 目录结构

### 1.1 src/serverless_sandbox/ 顶层模块列表

**结论: ✅ 准确**

AGENTS.md 列出: agent, api, cli, compat, declarative, extensions, integrations, models, protocol, session, transport, utils  
实际 `ls` 结果: agent, api, cli, compat, declarative, extensions, integrations, models, protocol, session, transport, utils  

完全一致。

### 1.2 CLI 子命令列表

**结论: ⚠️ 不准确**

文档说: `commands/` 目录包含 "Subcommands: create, exec, list, kill, config, template, mcp, session, deploy, …"

实际文件:
```
auth.py, config_cmd.py, deploy.py, mcp.py, sandbox.py, secret.py, session.py, skill.py, template.py
```

差异:
| 文档列出 | 实际情况 |
|---------|---------|
| create, exec, list, kill | **不存在**为独立文件；这些可能是 `sandbox.py` 的子命令 |
| config | 实际文件名为 `config_cmd.py` |
| — | **遗漏** auth.py, secret.py, skill.py, sandbox.py |

### 1.3 API 模块列表

**结论: ⚠️ 不准确**

文档说: "High-level API: Sandbox, files, code, commands, network, pool, capability, template"

实际 `api/` 目录:
```
capability.py, code.py, commands.py, files.py, image.py, network.py, sandbox.py, session_manager.py, template.py
```

差异:
- **`pool.py` 不存在** — 文档列出但实际文件系统中不存在，`api/__init__.py` 也未导入 `SandboxPool`
- **遗漏 `image.py`** — 实际存在且在 `__init__.py` 中导出
- **遗漏 `session_manager.py`** — 实际存在

### 1.4 models/ 模块列表

**结论: ✅ 准确**

文档说: config, errors, sandbox, template, session, filesystem, process  
实际: config.py, errors.py, filesystem.py, process.py, sandbox.py, session.py, template.py  
完全一致。

### 1.5 ADR `rejected/` 目录结构

**结论: ⚠️ 不准确**

文档说 `rejected/` 下有 architecture/, feature/, process/ 子目录（与 proposed/ 和 implemented/ 结构对称）。

实际: `rejected/` 是扁平目录，仅包含 `.gitkeep` 和一个 .md 文件，**没有子目录**。

---

## 2. 架构分层

**结论: ⚠️ 不准确 — 层级编号与实际依赖方向矛盾**

AGENTS.md 声明:
```
L1  Transport   → L2  Protocol   → L3  Models   → L4  API
"lower layers never import upper layers"
```

实际 import 关系（通过 grep 验证）:

| 源模块 (Layer) | 依赖模块 (Layer) | 是否违反 |
|---------------|-----------------|---------|
| transport/auth.py (L1) | models.errors (L3) | **违反** — L1 导入 L3 |
| transport/http.py (L1) | models.errors (L3) | **违反** — L1 导入 L3 |
| transport/ws.py (L1) | models.errors (L3) | **违反** — L1 导入 L3 |
| protocol/* (L2) | transport/* (L1) | OK |
| protocol/* (L2) | models/* (L3) | 违反 — L2 导入 L3 |
| api/* (L4) | protocol/* (L2) | OK |
| api/* (L4) | models/* (L3) | OK |

**根本问题:** Models 和 Utils 实际上是最底层（零外部依赖），但 AGENTS.md 把 Models 标为 L3（高于 Transport L1）。实际的依赖方向是:

```
实际层级（从底到顶）:
  L0  Utils         utils/           无跨模块依赖
  L0  Models        models/          无跨模块依赖
  L1  Transport     transport/       依赖 Models, Utils
  L2  Protocol      protocol/        依赖 Transport, Models, Utils
  L3  API           api/             依赖 Protocol, Transport, Models, Utils
```

AGENTS.md 的分层图**编号标记错误**，会误导读者认为 Transport 不应该导入 Models。

---

## 3. 开发命令

### 3.1 Makefile targets

**结论: ✅ 准确**

| AGENTS.md | Makefile 实际 | 命令 |
|-----------|-------------|------|
| `make test` | ✅ 存在 | `pytest tests/ -v --tb=short` ✅ |
| `make test-cov` | ✅ 存在 | `pytest tests/ -v --tb=short --cov=serverless_sandbox --cov-report=term-missing` ✅ |
| `make lint` | ✅ 存在 | `ruff check src/ tests/` ✅ |
| `make format` | ✅ 存在 | `ruff format src/ tests/` ✅ |
| `make typecheck` | ✅ 存在 | `mypy src/serverless_sandbox/` ✅ |
| `make clean` | ✅ 存在 | ✅ |

### 3.2 pip install -e ".[dev]"

**结论: ✅ 准确**

pyproject.toml 定义了 `[project.optional-dependencies]` 下的 `dev` extra，包含 pytest, ruff, mypy 等。

### 3.3 pip install -e ".[cli]"

**结论: ✅ 准确**

pyproject.toml 定义了 `cli` extra，包含 click, rich, pyyaml。

---

## 4. 错误码范围

**结论: ✅ 准确**

| AGENTS.md | errors.py 实际 | 一致性 |
|-----------|---------------|--------|
| E1xxx Authentication / `AuthenticationError` | E1000-E1003 ✅ | ✅ |
| E2xxx Creation / `SandboxCreationError` | E2000-E2004 ✅ | ✅ |
| E3xxx Execution / `ExecutionError` | E3000-E3004 ✅ | ✅ |
| E4xxx Filesystem / `FileOperationError` | E4000-E4002 ✅ | ✅ |
| E5xxx Network / `NetworkError` | E5000-E5001 ✅ | ✅ |
| E6xxx Session / `SessionError` | E6000-E6002 ✅ | ✅ |

所有 6 个范围及其基类名称均与代码一致。

**附注:** errors.py 文件自身的 docstring 仅列出 E1xxx-E5xxx，遗漏了 E6xxx。这是源码内部的文档缺陷，不是 AGENTS.md 的问题。

---

## 5. 能力模型

**结论: ✅ 准确**

| 常量 | AGENTS.md | models/template.py 实际 |
|------|-----------|------------------------|
| `STANDARD_CAPABILITIES` | `{shell, files, code, terminal, ports}` | `frozenset({"shell", "files", "code", "terminal", "ports"})` ✅ |
| `DEFAULT_CAPABILITIES` | `{shell, files, code}` | `frozenset({"shell", "files", "code"})` ✅ |

`terminal` 和 `ports` 必须显式声明的描述也与代码注释一致。

Fail-closed 行为: AGENTS.md 声明 "if a matched template's YAML is malformed, the resolver raises `TemplateParseError` (E2004) rather than silently falling back to defaults"。`api/capability.py` 第 110-122 行确认此行为 — matched + malformed 会 raise `TemplateParseError`，而非回退。✅

---

## 6. 命令解析优先级

### 6.1 Capability Resolution Priority

**结论: ✅ 准确**

AGENTS.md:
1. Explicit `local_yaml_path`
2. Local template cache scan (`~/.sbox/templates/`)
3. *(Phase 2, TODO)* Online fallback
4. Fall back to `DEFAULT_CAPABILITIES` + warning

`api/capability.py` `resolve_capabilities()` 函数（第 141-217 行）实现：
1. 第 162 行: `if local_yaml_path:` → 解析本地路径 ✅
2. 第 193 行: `if template is None and template_id:` → `_find_local_template()` 扫描 `~/.sbox/templates/` ✅
3. 第 196 行: `# TODO(Phase2): online fallback` ✅
4. 第 199 行: `if template is None:` → 回退到 `ResolvedCapabilities()` (DEFAULT) + warning ✅

完全一致。

### 6.2 CLI Command Resolution Priority

**结论: ⚠️ 无法验证**

AGENTS.md 描述: "Programmatic specification → local project `sandbox-template.yaml` → installed template cache → *(Phase 2)* online registry → `DEFAULT`"

此为 CLI 层面的解析描述，但 CLI 命令实际通过 `api/capability.py` 间接实现。AGENTS.md 此处将 "local project sandbox-template.yaml" 与 "installed template cache" 作为分离步骤，但 `resolve_capabilities()` 的步骤 1 是 `local_yaml_path`（任意路径），步骤 2 才是 cache 扫描。两者语义大致对应，但 "local project" 的措辞暗示当前目录下的模板文件，而实际代码接受的是显式传入的任意路径。

---

## 7. 测试约定

### 7.1 pytest + pytest-asyncio

**结论: ✅ 准确**

pyproject.toml 确认 `asyncio_mode = "auto"`，`testpaths = ["tests"]`。

### 7.2 Integration test marker

**结论: ✅ 准确**

pyproject.toml `markers = ["integration: ..."]`，与 AGENTS.md 描述一致。

### 7.3 Golden-file CLI Evidence

**结论: ✅ 准确**

`tests/test_cli_evidence/test_evidence_snapshots.py` 第 28 行确认: `UPDATE = os.environ.get("SBOX_UPDATE_EVIDENCE", "") == "1"`。  
`scripts/capture_cli_evidence.py` 存在。  
AGENTS.md 描述的 `SBOX_UPDATE_EVIDENCE=1 pytest tests/` 机制与代码一致。

### 7.4 Type annotations: "mypy --strict"

**结论: ✅ 准确（但表述可更精确）**

AGENTS.md 说 "Type annotations enforced: `mypy --strict`"。Makefile 命令为 `mypy src/serverless_sandbox/`（无 `--strict` 标志），但 `pyproject.toml` 配置了 `strict = true`，效果等价。

---

## 8. AI 助手护栏

**结论: ✅ 基本合理，但有遗漏**

10 条规则核查：

| # | 规则 | 评估 |
|---|------|------|
| 1 | Never auto-commit | ✅ 合理 |
| 2 | Never delete golden files | ✅ 合理 |
| 3 | Regenerate evidence after CLI change | ✅ 合理 |
| 4 | Never bypass capability gates | ✅ 合理，与代码设计意图一致 |
| 5 | Never fabricate FC/envd API endpoints | ✅ 合理 |
| 6 | Run full test suite before claiming done | ✅ 合理 |
| 7 | Secret scanning via .githooks | ✅ .githooks/check-secrets.sh 存在 |
| 8 | Conventional Commits | ✅ 合理 |
| 9 | Minimize changes | ✅ 合理 |
| 10 | Type annotations + Google-style docstrings | ✅ 合理 |

**❌ 缺失的重要规则:**

- **层级依赖规则**: 未提及 "下层模块不得导入上层模块" 的具体约束（虽然在架构分层部分描述了原则，但护栏部分没有作为可执行规则重申）
- **`__all__` 导出规范**: 代码中大量使用 `__all__` 控制公共 API，但未在护栏中提及需要维护
- **Pydantic model 别名约定**: models 使用 `alias` 映射 camelCase API 字段，这是容易出错的约定但未提及

---

## 9. 交叉引用

**结论: ✅ 准确**

| 链接目标 | 是否存在 |
|---------|---------|
| `.github/CONTRIBUTING.md` | ✅ 存在 |
| `.github/PULL_REQUEST_TEMPLATE.md` | ✅ 存在 |
| `.github/SECURITY.md` | ✅ 存在 |
| `.agents/notes/README.md` | ✅ 存在 |
| `docs/design/` | ✅ 存在 |
| `docs/evidence/README.md` | ✅ 存在 |
| `CHANGELOG.md` | ✅ 存在 |

所有引用的文件均存在，路径正确。

---

## 总结

| 检查项 | 结果 | 严重程度 |
|-------|------|---------|
| 1.1 顶层模块列表 | ✅ 准确 | — |
| 1.2 CLI 子命令列表 | ⚠️ 不准确 | **高** — 5个命令不存在/命名错误，4个命令遗漏 |
| 1.3 API 模块列表 | ⚠️ 不准确 | **中** — pool.py 不存在，遗漏 image.py/session_manager.py |
| 1.5 ADR rejected/ 结构 | ⚠️ 不准确 | **低** — 子目录不存在 |
| 2. 架构分层编号 | ⚠️ 不准确 | **高** — L1-L3 编号与实际依赖方向矛盾，Models 应在 Transport 之下 |
| 3. 开发命令 | ✅ 准确 | — |
| 4. 错误码范围 | ✅ 准确 | — |
| 5. 能力模型 | ✅ 准确 | — |
| 6. 解析优先级 | ✅ 基本准确 | — |
| 7. 测试约定 | ✅ 准确 | — |
| 8. AI 护栏 | ✅ 基本合理 | **低** — 有小幅遗漏 |
| 9. 交叉引用 | ✅ 准确 | — |

### 高优先级修复建议

1. **修正架构分层图**: 将 Models/Utils 标为最底层（L0），Transport 为 L1，Protocol 为 L2，API 为 L3。或改用依赖箭头图而非编号层级。
2. **更新 CLI 子命令列表**: 替换为实际文件名 (auth, config_cmd, deploy, mcp, sandbox, secret, session, skill, template)。
3. **更新 API 模块列表**: 移除 pool，补充 image 和 session_manager。

