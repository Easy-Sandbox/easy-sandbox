# Decision: Add CI environment variable suppression fixture in test conftest

Status: implemented
Implemented: 2026-09-29

## Problem
When tests run in CI environments (GitHub Actions, etc.), the environment
variables `CI=true` and `GITHUB_ACTIONS=true` are automatically set. The SDK's
`is_ci_env()` utility detects these and auto-enables JSON output mode. This
caused **108 test failures** because:

- Tests asserting human-readable table/text output received JSON instead.
- Tests checking for interactive prompts were skipped under CI detection.
- The failures were environment-dependent and not reproducible locally.

## Decision
Add an `autouse` session-scoped fixture `_suppress_ci_detection` in
`tests/conftest.py` that clears all CI-related environment variables before
the test session:

```python
@pytest.fixture(autouse=True, scope="session")
def _suppress_ci_detection(monkeypatch_session):
    ci_vars = [
        "CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI",
        "TRAVIS", "JENKINS_URL", "BUILDKITE", "TF_BUILD",
        "CODEBUILD_BUILD_ID",
    ]
    for var in ci_vars:
        monkeypatch_session.delenv(var, raising=False)
```

This ensures tests always run in "local developer" mode regardless of the
actual execution environment.

## API Design
N/A — this decision does not involve API changes. Test infrastructure only.

## Alternatives considered
- **Mock `is_ci_env()` in individual tests** — requires touching 108+ test
  files; fragile and easy to forget in new tests. Rejected.
- **Disable JSON auto-detection entirely** — would break the intended CI
  behavior for actual production use. Rejected.

## Dependencies
- `pytest` monkeypatch fixture

## Test Strategy
- The fixture itself is validated by the fact that the 108 previously-failing
  tests now pass in CI.

## Files changed
- `tests/conftest.py` — added `_suppress_ci_detection` autouse fixture

## Acceptance criteria
- ✅ All 108 previously-failing tests pass in CI
- ✅ `is_ci_env()` returns `False` during test execution
- ✅ No test relies on CI environment variables being set
