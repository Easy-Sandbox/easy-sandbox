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

# 3. Install pre-commit hooks
pre-commit install

# 4. Verify your setup
make test
```

> **Note:** The project also ships a `.githooks/` directory. If your Git config
> uses `core.hooksPath=.githooks`, the same secret-scanning check runs
> automatically via `.githooks/pre-commit` — no extra setup needed. The
> `pre-commit install` approach and `core.hooksPath` approach are complementary;
> both ultimately call `.githooks/check-secrets.sh`.

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

A custom hook (`.githooks/check-secrets.sh`) scans every commit for hardcoded secrets — API keys, tokens, passwords, and cloud credentials. It runs in **two** complementary ways:

| Path | How it runs |
|------|-------------|
| `pre-commit install` | The hook is registered as a **local** repo entry (`id: check-secrets`) in `.pre-commit-config.yaml`. |
| `core.hooksPath=.githooks` | `.githooks/pre-commit` calls the same script directly. |

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

Community sandbox templates are indexed in [`awesome-templates.yaml`](../awesome-templates.yaml) at the repository root. This file serves as a curated, searchable registry of both official and community templates — similar to an awesome-list.

### Adding Your Template to the Index

1. **Fork** this repository
2. **Open** `awesome-templates.yaml` and add your entry under the `# === Community Templates ===` section:
   ```yaml
   - name: my-template
     description: "One-line description of what your template does"
     repo: https://github.com/your-username/your-repo
     path: optional/subdir        # omit if template is at repo root
     tags: [python, your-tag]
     author: your-github-handle
     capabilities: [shell, files, code]  # sandbox capabilities your template requires
     status: community
   ```
3. **Required fields**: `name`, `description`, `repo`, `tags`, `author`, `capabilities`, `status`
4. **Status values**:
   - `official` — maintained by the Easy-Sandbox team (do not use for community PRs)
   - `community` — community-contributed and maintained
   - `experimental` — early-stage or proof-of-concept
5. **Ensure** your repo contains a valid `template.yaml` at the specified path
6. **Open a PR** against `main` with the commit message: `feat: add <template-name> community template`

### Template Repository Requirements

Your template repository should include:
- A `template.yaml` defining the sandbox configuration (base image, packages, capabilities, etc.)
- A `README.md` with usage instructions
- Example code or scripts that demonstrate the template's purpose

### Searching Templates

Use the CLI to search the community index:
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
