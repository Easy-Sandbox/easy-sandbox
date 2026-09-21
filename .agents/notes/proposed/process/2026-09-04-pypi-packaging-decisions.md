# Decision: PyPI 打包就绪决策（发行名 + P0 修复清单）

Status: proposed
Task: #95, #97, #105

## Problem
项目即将首次公开发布到 PyPI，需要明确发行名并解决发布前的 blocker 项。审计发现若干硬性阻断（version 为 dev、URLs 为占位符、零 CI）和缺失的类型标记。

## Decision
明确发行名为 `easy-sandbox`，并定义发布前必须解决的 P0 清单。

### 发行名确认

1. **发行名 `easy-sandbox`**：PyPI JSON API 返回 404（可用）。`ebx` 已被第三方占用（HTTP 200），不可用。
2. **PyPI org `ebx` 审批 pending 不阻塞发布**：org 审批只影响组织归属管理，不影响发行名可用性。发行名是全局唯一命名空间，与 org 无关。

### P0 修复清单（发布前必须解决）

3. **缺 `py.typed` 标记**：`src/easy_sandbox/py.typed` 不存在。项目使用 `mypy strict=true`，是完全类型化的 SDK，消费者应能利用其类型信息。hatchling 在 `packages` 设置下会自动包含此文件——只需创建空文件。
4. **缺 CI workflow**：`.github/workflows/` 目录完全不存在。需要：
   - `ci.yml`：lint + mypy + pytest（矩阵 py3.10–3.13），PR/push to main 触发。
   - `release.yml`：build + publish to PyPI on tag push。
   - 初期用 `PYPI_API_TOKEN` 方案（用户已配置 repo secret），中长期迁移到 Trusted Publishing（OIDC）。
5. **`[project.urls]` 为 `anycodes/*` 占位符**：`pyproject.toml` 的 Homepage/Documentation/Repository/Issues 全部指向 `github.com/anycodes/easy-sandbox*`。需替换为最终确认的 org/repo URL。
6. **CODE_OF_CONDUCT.md / SECURITY.md 占位符联系邮箱**：两文件中的 `SECURITY_CONTACT_EMAIL` 占位符必须在任何公开发布前替换为真实邮箱。

### 已确认无问题的项

7. version 来源（dynamic → `_version.py`）、build-backend（hatchling）、readme、license（Apache-2.0 SPDX）、requires-python（>=3.10）、dependencies、extras 均 OK。
8. License classifier 与 SPDX 表达式并存：提示级问题，建议移除 License classifier 保留 SPDX。
9. README 徽章在 CI + PyPI publish 后自动生效，无需文本改动。

### 发布路径

10. **安全发布路径**：`python -m build` → `twine check dist/*` → TestPyPI 演练 → 正式 `twine upload`。
11. **PyPI 不可逆性**：同一版本号一旦上传永久占用，yank 也消耗版本号。务必先 TestPyPI。
12. **`_version.py` 从 `0.1.0-dev` 改为 `0.1.0`**：PEP 440 会规范化为 `0.1.0.dev0`，`pip install` 默认不装 dev 版。

## Alternatives considered
- **发行名用 `ebx`** — PyPI 已被第三方占用。Rejected（硬约束）。
- **先发布再补 CI** — 没有 CI 的首版无法保证质量，且 badge 空转影响可信度。Rejected。
- **跳过 TestPyPI 直接正式发布** — PyPI 版本号不可逆，风险过高。Rejected。

## Dependencies
- `pyproject.toml`（metadata 修正）
- `src/easy_sandbox/_version.py`（版本号）
- `.github/CODE_OF_CONDUCT.md`、`.github/SECURITY.md`（占位符）
- `2026-09-04-single-distribution-cli-extra.md`（命名体系）

## Test Strategy
- `python -m build` 成功产出 wheel + sdist。
- `twine check dist/*` PASSED（无 warning/error）。
- TestPyPI 安装后 `import easy_sandbox` + `ebx --help` 正常。
- `mypy --strict` 在消费者项目中识别到 `py.typed`。

## Acceptance criteria
- `py.typed` 文件存在于 `src/easy_sandbox/`。
- CI workflow（ci.yml + release.yml）在 `.github/workflows/` 下且能跑通。
- `[project.urls]` 指向真实 URL。
- 占位符邮箱全部替换为真实联系方式。
- `_version.py` 为稳定版本号（无 `-dev`）。

## Evidence
- `.agents/evidence/research/2026-09-04-pypi-publish-readiness.md` §1–§7
- `.agents/evidence/research/2026-09-04-ai-native-oss-completeness.md` §2（Gap Table #1–#3, #9–#10）
