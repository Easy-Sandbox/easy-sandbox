# AI-Native Open-Source Completeness Audit

> **Date**: 2026-09-04 | **Auditor**: Zoe (read-only research agent) | **Task**: #97
>
> Scope: Assess whether `serverless-sandbox` is a complete, standard AI-native open-source project ready for public launch. Does NOT re-analyze packaging (covered by #95).

---

## 1. Summary Verdict

**Overall Maturity: Late-Alpha / Pre-Launch — NOT yet a complete AI-native OSS project.**

The project demonstrates strong internal engineering (six-layer architecture, 1035 tests across 64 files, comprehensive design docs, solid community scaffolding), but it is missing the **external-facing infrastructure** that a real contributor or user encounters first: CI/CD, hosted docs, type marker, demo assets, and dependency security automation. Community files are present and high-quality but contain unresolved placeholders.

**Launch-blocking count**: 5 P0 gaps, 5 P1 gaps, 4 P2 gaps.

---

## 2. Gap Table

| # | Item | Present? | Quality | Severity | Recommendation | Effort |
|---|------|----------|---------|----------|----------------|--------|
| 1 | `.github/workflows/` (CI/CD) | **NO** | N/A | **P0** | Add `ci.yml` (lint+mypy+pytest on PR/push to main, matrix py3.10-3.13) and `release.yml` (build+publish to PyPI on tag) | M (2-3h) |
| 2 | `py.typed` marker | **NO** | N/A | **P0** | Create empty `src/serverless_sandbox/py.typed`; hatchling auto-includes it when `packages` is set | XS (2min) |
| 3 | README badges (CI/PyPI) | Placeholder | CI badge links to non-existent workflow; PyPI badge will 404 until published | **P0** | Badges become live once CI workflow + PyPI publish exist; no text change needed | XS (after #1) |
| 4 | Demo asset (GIF/asciinema/SVG) | **NO** | N/A | **P1** | Record a 30s terminal GIF (VHS or asciinema) showing `sbox create → exec → kill`; add architecture SVG from existing Mermaid | S (1h) |
| 5 | `llms.txt` (llmstxt.org) | **NO** | N/A | **P1** | Create root `llms.txt` summarising project, linking to README, design docs, API reference; standard AI-native discoverability touch | S (30min) |
| 6 | Hosted docs / API reference | **NO** | N/A | **P1** | Add `mkdocs.yml` + `mkdocs-material` with `mkdocstrings` for auto API ref; deploy via GitHub Pages in CI | M (3-4h) |
| 7 | Coverage config + badge | Partial | `make test-cov` exists; no `[tool.coverage]` section, no badge, no codecov integration | **P1** | Add `[tool.coverage.run]`/`[tool.coverage.report]` to pyproject.toml; add codecov action to CI; add badge to README | S (30min) |
| 8 | Dependency security scanning | Partial | `bandit` + `detect-secrets` in pre-commit; NO `dependabot.yml`, NO `pip-audit` | **P1** | Add `.github/dependabot.yml` (pip weekly); add `pip-audit` step in CI | XS (15min) |
| 9 | CODE_OF_CONDUCT + SECURITY placeholders | Present | `SECURITY_CONTACT_EMAIL` placeholder in both files (lines 63 and 16 respectively) | **P0** | Replace with real email before any public launch | XS (2min) |
| 10 | `[project.urls]` placeholders | Present | All point to `anycodes/*` (personal account), not org | **P0** | Update to final GitHub org/repo once decided; add `Documentation` URL pointing to hosted site | XS (5min) |
| 11 | CHANGELOG versioning policy | Partial | Follows Keep a Changelog format; NO explicit SemVer policy statement for the project | **P2** | Add a "Versioning" section to CHANGELOG.md or CONTRIBUTING.md stating SemVer adherence | XS (5min) |
| 12 | Architecture diagram in README | **NO** | Mermaid diagrams exist in `docs/design/architecture.md` but README has no visual | **P2** | Export the six-layer Mermaid as SVG/PNG; embed in README "Architecture" section | S (30min) |
| 13 | Reproducible dev environment | Partial | `make dev` + CONTRIBUTING docs; NO devcontainer, NO nix, NO `.python-version` | **P2** | Add `.devcontainer/devcontainer.json` (python:3.12 base) or `.python-version` for pyenv users | S (30min) |
| 14 | `AGENTS.md` | **NO** | In-flight (task #96) | **P2** | Track via #96; no action needed here | N/A |
| 15 | GitHub repo metadata (description/topics) | Unknown | Cannot verify remotely; no local config | **P2** | Set description + topics (`sandbox`, `ai-agents`, `e2b`, `serverless`, `alibaba-cloud`, `mcp`) when repo goes public | XS (5min) |

---

## 3. What's Already Good

| Area | Evidence | Assessment |
|------|----------|------------|
| **Community scaffolding** | `.github/CONTRIBUTING.md` (146 lines), `ISSUE_TEMPLATE/` (4 structured YAML templates + config.yml), `PULL_REQUEST_TEMPLATE.md`, `DISCUSSION_TEMPLATE/welcome.md`, `discussions/welcome-post.md` | Comprehensive, well-structured, covers bug/feature/docs/template workflows. Quality exceeds most alpha projects. |
| **Pre-commit hooks** | `.pre-commit-config.yaml`: trailing-whitespace, end-of-file-fixer, check-yaml/toml/json, large-files, merge-conflict, debug-statements, detect-private-key, detect-secrets, ruff lint+format, bandit, custom check-secrets | Multi-layer security + code quality enforcement. Excellent. |
| **Secret scanning** | `.githooks/check-secrets.sh`, `.secrets.baseline`, `detect-secrets` hook, custom local hook | Defense-in-depth; dual-path (pre-commit + core.hooksPath). |
| **Code style tooling** | Ruff (lint+format), mypy `strict=true`, bandit, `[tool.ruff.lint] select` rules | Production-grade static analysis configuration. |
| **Test suite** | 64 test files, ~1035 test functions, `pytest-asyncio`, `pytest-httpx`, structured `tests/` mirroring `src/` | Substantial coverage; async-first testing properly configured. |
| **CHANGELOG** | Follows Keep a Changelog; documents Added/Changed/Architecture sections | Good practice, just needs versioning policy statement. |
| **LICENSE + NOTICE** | Apache-2.0, consistent copyright "2026 Anycodes" in both | Correct and complete. |
| **Design documentation** | `docs/DESIGN.md` (2351 lines), 8 design docs in `docs/design/`, Mermaid architecture diagrams, `docs/research/` with competitor analysis | Exceptional internal documentation depth. |
| **README structure** | Badges (once live), features list, installation variants, SDK quickstart, CLI quickstart, templates table, docs links, contributing section | Well-organized; just needs visual demo asset + architecture diagram. |
| **Makefile** | `help`, `install`, `dev`, `test`, `test-cov`, `lint`, `format`, `typecheck`, `clean` | Covers standard dev workflow; missing only `setup` alias. |

---

## 4. Prioritized Remediation Plan

### Phase A — Launch Blockers (P0, do before any public announcement)

| Order | Action | Files to Create/Modify | Est. |
|-------|--------|------------------------|------|
| A1 | Create `py.typed` marker | `src/serverless_sandbox/py.typed` (empty file) | 2min |
| A2 | Replace placeholder emails | `.github/CODE_OF_CONDUCT.md` L63, `.github/SECURITY.md` L16 | 5min |
| A3 | Update `[project.urls]` to final org/repo | `pyproject.toml` L73-76 | 5min |
| A4 | Create CI workflow | `.github/workflows/ci.yml` (lint+mypy+test matrix, py3.10-3.13) | 1h |
| A5 | Create release workflow | `.github/workflows/release.yml` (build+publish on tag push) | 1h |

### Phase B — Discoverability & AI-Native (P1, within 1 week of launch)

| Order | Action | Files to Create/Modify | Est. |
|-------|--------|------------------------|------|
| B1 | Add `dependabot.yml` | `.github/dependabot.yml` (pip, weekly) | 10min |
| B2 | Add `pip-audit` CI step | `.github/workflows/ci.yml` (add step) | 10min |
| B3 | Add coverage config + codecov | `pyproject.toml` `[tool.coverage.*]`, CI step, README badge | 30min |
| B4 | Create `llms.txt` | `llms.txt` at project root | 30min |
| B5 | Record demo GIF/asciinema | `docs/assets/demo.gif` or asciinema link; embed in README | 1h |
| B6 | Set up MkDocs + API reference | `mkdocs.yml`, `docs/index.md`, GitHub Pages deploy in CI | 3h |

### Phase C — Polish (P2, within 1 month)

| Order | Action | Files to Create/Modify | Est. |
|-------|--------|------------------------|------|
| C1 | Document SemVer policy | `CONTRIBUTING.md` or `CHANGELOG.md` new section | 10min |
| C2 | Export architecture diagram to README | `docs/assets/architecture.svg` + README section | 30min |
| C3 | Add devcontainer | `.devcontainer/devcontainer.json` + `Dockerfile` | 30min |
| C4 | Set GitHub repo topics/description | GitHub repo settings (manual) | 5min |
| C5 | `AGENTS.md` (tracked in #96) | `AGENTS.md` | N/A |

---

## 5. Detailed Evidence Notes

### 5.1 CI/CD — Confirmed MISSING

```
$ ls .github/workflows/
ls: No such file or directory
```

The README already references `ci.yml` badge (line 4) and the roadmap (`docs/roadmap.md` L30) lists "CI/CD" as a Phase 1 deliverable — confirming intent but not execution.

### 5.2 py.typed — Confirmed MISSING

```
$ ls src/serverless_sandbox/py.typed
ls: No such file or directory
```

No reference to `py.typed` anywhere in `pyproject.toml`. The hatchling build config (`[tool.hatch.build.targets.wheel] packages = ["src/serverless_sandbox"]`) will auto-include `py.typed` if the file exists — no extra config needed.

The project uses `mypy strict = true` (pyproject.toml L105), confirming it IS a fully-typed SDK that consumers should be able to leverage.

### 5.3 llms.txt — Confirmed MISSING

No `llms.txt` at project root. Per llmstxt.org standard (proposed Sep 2024 by Jeremy Howard), this file helps LLMs and AI agents understand project structure. For an AI-native sandbox SDK, this is a differentiating touch.

### 5.4 Hosted Docs — Confirmed MISSING

- No `mkdocs.yml`, no `docs/conf.py` (Sphinx), no GitHub Pages `CNAME`.
- `[project.urls] Documentation` = `https://github.com/anycodes/serverless-sandbox/docs` (raw GitHub, not a hosted site).
- Internal docs are comprehensive (2351-line DESIGN.md, 8 design docs, research analysis) but not published/consumable externally.

### 5.5 Coverage — PARTIAL

- `pytest-cov>=4.0` in `[dev]` dependencies (pyproject.toml L63).
- `make test-cov` target: `pytest tests/ -v --tb=short --cov=serverless_sandbox --cov-report=term-missing`.
- MISSING: No `[tool.coverage.run]` or `[tool.coverage.report]` configuration, no `.coveragerc`, no coverage badge in README, no codecov/coveralls integration, no CI to enforce minimum threshold.

### 5.6 Community Files — Present with Placeholders

| File | Lines | Quality Issue |
|------|-------|---------------|
| `CODE_OF_CONDUCT.md` | 134 | L63: `**SECURITY_CONTACT_EMAIL** (replace before release)` |
| `SECURITY.md` | 57 | L16: `**SECURITY_CONTACT_EMAIL** (replace before release)` |
| All others | — | No quality issues detected |

### 5.7 Dependency Security — PARTIAL

Present:
- `bandit` in pre-commit + `[tool.bandit]` in pyproject.toml
- `detect-secrets` with `.secrets.baseline`
- Custom `.githooks/check-secrets.sh`

Missing:
- No `.github/dependabot.yml` or `renovate.json`
- No `pip-audit` or `safety` anywhere in the toolchain
- No automated dependency update mechanism

### 5.8 Demo Assets — ZERO visual assets in repo

```
$ find . -name "*.gif" -o -name "*.svg" -o -name "*.png" -o -name "*.jpg"
(empty)
```

No images, screenshots, architecture diagrams (as rendered files), or terminal recordings exist anywhere in the repository.

---

## 6. Competitor Benchmark (AI-native SDK projects)

For context, comparable projects typically have:

| Feature | E2B | Modal | Daytona | This Project |
|---------|-----|-------|---------|--------------|
| CI/CD workflows | Yes | Yes | Yes | **NO** |
| Hosted docs site | Yes (docs.e2b.dev) | Yes (modal.com/docs) | Yes | **NO** |
| py.typed | Yes | Yes | Yes | **NO** |
| Demo GIF in README | Yes | Yes | Yes | **NO** |
| llms.txt | No | No | No | **NO** |
| Coverage badge | Yes | Yes | Yes | **NO** |
| Dependabot/Renovate | Yes | Yes | Yes | **NO** |
| Issue templates | Yes | Yes | Yes | Yes |
| CONTRIBUTING.md | Yes | Yes | Yes | Yes |

Note: `llms.txt` is not yet adopted by major competitors — implementing it would be a **differentiating AI-native touch**.

---

*End of report.*
