# Decision: PyPI packaging decisions and pre-release P0 checklist

Status: proposed
Task: #95, #97, #105

## Problem
The project is about to make its first public release to PyPI and needs to
finalise the distribution name and resolve pre-release blockers. The audit
surfaced several hard blockers (version stuck at `dev`, placeholder URLs, zero
CI) and a missing typing marker.

## Decision
Confirm the distribution name as `easy-sandbox` and define the P0 checklist that
must be resolved before publishing.

### Distribution name confirmation

1. **Distribution name `easy-sandbox`**: the PyPI JSON API returns 404
   (available). `ebx` is already taken by a third party (HTTP 200) and is not
   available.
2. **PyPI org `ebx` approval pending does not block release**: org approval only
   affects organisational ownership management, not distribution-name
   availability. The distribution name is a global namespace and is independent
   of the org.

### P0 fix list (must be resolved before release)

3. **Missing `py.typed` marker**: `src/easy_sandbox/py.typed` does not exist.
   The project uses `mypy strict=true` and is a fully-typed SDK — consumers
   should be able to leverage its type information. hatchling automatically
   includes this file under the `packages` setting — simply create an empty
   file.
4. **Missing CI workflow**: `.github/workflows/` does not exist at all. Need:
   - `ci.yml`: lint + mypy + pytest (matrix py3.10–3.13), triggered on PR /
     push to main.
   - `release.yml`: build + publish to PyPI on tag push.
   - Initially use the `PYPI_API_TOKEN` approach (the user has already
     configured the repo secret); mid-to-long term migrate to Trusted
     Publishing (OIDC).
5. **`[project.urls]` are `anycodes/*` placeholders**: Homepage / Documentation
   / Repository / Issues in `pyproject.toml` all point at
   `github.com/anycodes/easy-sandbox*`. Replace with the final confirmed
   org/repo URLs.
6. **Placeholder contact email in CODE_OF_CONDUCT.md / SECURITY.md**: the
   `SECURITY_CONTACT_EMAIL` placeholder in both files must be replaced with a
   real email before any public release.

### Items already confirmed OK

7. Version source (dynamic → `_version.py`), build-backend (hatchling), readme,
   license (Apache-2.0 SPDX), requires-python (>=3.10), dependencies, and
   extras are all fine.
8. License classifier and SPDX expression coexisting: notice-level issue;
   recommend removing the License classifier and keeping SPDX.
9. README badges will activate automatically once CI + PyPI publishing land;
   no textual change needed.

### Release path

10. **Safe release path**: `python -m build` → `twine check dist/*` →
    TestPyPI dry run → official `twine upload`.
11. **PyPI immutability**: once a version number is uploaded it is permanently
    consumed; `yank` also consumes the version number. Always test on TestPyPI
    first.
12. **Change `_version.py` from `0.1.0-dev` to `0.1.0`**: PEP 440 normalises
    that to `0.1.0.dev0`, and `pip install` does not install dev versions by
    default.

## API Design
N/A — this decision does not involve API changes. It only concerns packaging
metadata (`pyproject.toml`, `_version.py`), CI workflows, and documentation
placeholders; no Python-level SDK APIs are added, removed, or modified.

## Alternatives considered
- **Use `ebx` as the distribution name** — already taken by a third party on
  PyPI. Rejected (hard constraint).
- **Publish first, add CI later** — a first release without CI cannot vouch for
  quality, and empty badges hurt trustworthiness. Rejected.
- **Skip TestPyPI and go straight to production release** — PyPI version
  numbers are irreversible; too risky. Rejected.

## Dependencies
- `pyproject.toml` (metadata fixes)
- `src/easy_sandbox/_version.py` (version number)
- `.github/CODE_OF_CONDUCT.md`, `.github/SECURITY.md` (placeholders)
- `2026-09-04-single-distribution-cli-extra.md` (naming scheme)

## Test Strategy
- `python -m build` produces wheel + sdist successfully.
- `twine check dist/*` PASSED (no warnings / errors).
- After TestPyPI install, `import easy_sandbox` + `ebx --help` work correctly.
- `mypy --strict` recognises `py.typed` in a consumer project.

## Acceptance criteria
- `py.typed` exists under `src/easy_sandbox/`.
- CI workflows (`ci.yml` + `release.yml`) exist under `.github/workflows/` and
  execute successfully.
- `[project.urls]` point at real URLs.
- Every placeholder email is replaced with a real contact address.
- `_version.py` holds a stable version number (no `-dev` suffix).

## Evidence
- `.agents/evidence/research/2026-09-04-pypi-publish-readiness.md` §1–§7
- `.agents/evidence/research/2026-09-04-ai-native-oss-completeness.md` §2
  (Gap Table #1–#3, #9–#10)
