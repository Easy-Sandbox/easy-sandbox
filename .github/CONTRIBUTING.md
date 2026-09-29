# Contributing to Easy Sandbox

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.10+
- Git

### Getting Started

```bash
# 1. Fork and clone the repository
git clone https://github.com/<your-username>/easy-sandbox.git
cd easy-sandbox

# 2. Install in development mode (includes all extras + test/lint tooling)
pip install -e ".[dev]"

# 3. Install pre-commit — its checks are invoked automatically by .githooks/pre-commit
pip install pre-commit   # or: make hooks

# 4. Verify your setup
make test
```

> **Note on Git hooks:** This repository ships `.githooks/` and uses it as the
> hook entry point via `core.hooksPath=.githooks` (a local Git config).
> `.githooks/pre-commit` first runs the custom secret scan
> (`.githooks/check-secrets.sh`), then — if the `pre-commit` command is
> installed — invokes the full `.pre-commit-config.yaml` suite (ruff,
> ruff-format, detect-secrets, bandit, …). Installing the package
> (`pip install pre-commit`, or `make hooks`) is all that is needed:
> `pre-commit install` is not used here because it writes to `.git/hooks/`,
> which Git bypasses while `core.hooksPath=.githooks` is set. On a fresh clone
> (where `core.hooksPath` is unset), run `git config core.hooksPath .githooks`
> — or `pre-commit install` — to activate the hooks.

## Development Workflow

1. **Fork** the repository on GitHub
2. **Create a branch** from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
3. **Make your changes** — write code, tests, and docs
4. **Run checks** before committing:
   ```bash
   make lint      # Lint with ruff
   make format    # Format with ruff
   make typecheck # Type-check with mypy
   make test      # Run tests with pytest
   ```

   Or run the full local CI equivalent in one command:
   ```bash
   make ci        # ruff check + ruff format --check + mypy + pytest (not integration) + build + twine check + py.typed check
   ```

   > **Note:** `make ci` runs on your single local Python interpreter. It does **not** replace the Python 3.10 / 3.11 / 3.12 test matrix enforced by GitHub Actions CI — the matrix can only be fully covered by CI itself.
5. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat: add sandbox snapshot support
   fix: resolve timeout issue in pool manager
   docs: update CLI usage examples
   chore: bump ruff to 0.5.0
   ```
6. **Push** and open a **Pull Request** against `main`

## Code Style

We use [**Ruff**](https://docs.astral.sh/ruff/) for **both linting and formatting** (replacing the former black / isort / flake8 setup). The configuration lives in `pyproject.toml` under `[tool.ruff]`.

- **Type Hints**: All public APIs must have type annotations; we enforce this with [mypy](https://mypy-lang.org/).
- **Docstrings**: Use Google-style docstrings for public functions and classes.

```python
async def create_sandbox(template: str, timeout: int = 300) -> Sandbox:
    """Create a new sandbox instance.

    Args:
        template: Name of the sandbox template.
        timeout: Maximum creation time in seconds.

    Returns:
        A configured Sandbox instance.

    Raises:
        SandboxError: If sandbox creation fails.
    """
```

## Secret Scanning

A custom hook (`.githooks/check-secrets.sh`) scans every commit for hardcoded secrets — API keys, tokens, passwords, and cloud credentials. Commit-time checks flow through a single entry point:

| Component | Role |
|-----------|------|
| `.githooks/pre-commit` | **Primary hook entry point.** Git calls it because this repository is configured with `core.hooksPath=.githooks`. |
| `check-secrets.sh` | Runs first: scans staged files for hardcoded secrets and blocks the commit if any are found. |
| pre-commit framework | Runs second (when the `pre-commit` command is installed): executes every hook in `.pre-commit-config.yaml` — ruff, ruff-format, detect-secrets, bandit, plus the `check-secrets` local hook — via `pre-commit run --hook-stage pre-commit`. |

To enable the full suite locally, install the package once:

```bash
pip install pre-commit
# or:
make hooks
```

If `pre-commit` is not installed, `.githooks/pre-commit` still runs the secret
scan and prints an install hint; the framework step is skipped without blocking
the commit.

If the hook detects a secret, the commit is blocked and the offending file + line is printed. False positives can be suppressed by adding `placeholder`, `example`, or `REPLACE_ME` to the line.

## Testing

- We use [pytest](https://docs.pytest.org/) for testing.
- Write tests for all new features and bug fixes.
- Place tests in the `tests/` directory, mirroring the `src/` structure.

```bash
# Run all tests
make test

# Run a specific test file
pytest tests/test_api/test_sandbox.py

# Run with verbose output
pytest -v
```

## Template Contributions

Sandbox templates — content, the machine-readable index (`awesome-templates.yaml`), releases and CI — live in the dedicated repository **[Easy-Sandbox/awesome-templates](https://github.com/Easy-Sandbox/awesome-templates)**. It is the single source of truth for official & community templates; this repository no longer bundles a template collection (it keeps only a minimal `python-hello` offline fixture for tests).

### Contributing a Template

1. **Read** the catalog repository's [CONTRIBUTING.md](https://github.com/Easy-Sandbox/awesome-templates/blob/main/CONTRIBUTING.md) — it defines the template anatomy, capability-group rules, and local dev workflow.
2. **Open a PR** against [Easy-Sandbox/awesome-templates](https://github.com/Easy-Sandbox/awesome-templates) that adds your template folder and updates `awesome-templates.yaml` (plus the README template table) in the same PR.
3. **Required index fields**: `name`, `description`, `repo`, `tags`, `author`, `capabilities`, `status` (optional: `path` for subdirectory templates, `ref` to pin a version).
4. **Status values**:
   - `official` — maintained by the Easy-Sandbox team (do not use for community PRs)
   - `community` — community-contributed and maintained
   - `experimental` — early-stage or proof-of-concept
5. **Ensure** your repo contains a valid `template.yaml` at the specified path. The catalog CI validates every folder and the index offline.

### Template Repository Requirements

Your template repository should include:
- A `template.yaml` defining the sandbox configuration (base image, packages, capabilities, etc.)
- A `Dockerfile` and a `README.md` with usage instructions
- Example code or scripts that demonstrate the template's purpose

### Searching Templates

Use the CLI to search the remote index:
```bash
ebx template search python      # search by tag or keyword
ebx template search ai-agent    # find AI agent templates
ebx template search browser     # find browser automation templates
```

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Purpose |
|--------|---------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `chore:` | Build, CI, or tooling changes |
| `test:` | Adding or updating tests |
| `refactor:` | Code change that neither fixes a bug nor adds a feature |
| `perf:` | Performance improvement |

## Reporting Issues

- Use [GitHub Issues](https://github.com/Easy-Sandbox/easy-sandbox/issues/new/choose) with our templates
- For security vulnerabilities, see our [Security Policy](SECURITY.md)

## Questions?

- Open a [Discussion](https://github.com/Easy-Sandbox/easy-sandbox/discussions) for general questions
- Check existing issues and discussions before creating new ones

## License

By contributing, you agree that your contributions will be licensed under the [Apache-2.0 License](../LICENSE).
