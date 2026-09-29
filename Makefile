.PHONY: install dev test lint format format-check typecheck build dist-check ci hooks clean help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install package
	pip install -e .

dev:  ## Install with all dev dependencies
	pip install -e ".[dev]"

test:  ## Run tests
	pytest tests/ -v --tb=short

test-cov:  ## Run tests with coverage
	pytest tests/ -v --tb=short --cov=easy_sandbox --cov-report=term-missing

lint:  ## Run linter
	ruff check src/ tests/

format:  ## Format code
	ruff format src/ tests/

typecheck:  ## Run type checker
	mypy src/easy_sandbox/

format-check:  ## Verify code is formatted (CI equivalent)
	ruff format --check src/ tests/

build:  ## Build sdist and wheel
	python -m build

dist-check:  ## Verify distributions (twine check + py.typed in wheel, CI equivalent)
	twine check dist/*
	@python -c "import zipfile, glob, sys; whl = glob.glob('dist/*.whl')[0]; z = zipfile.ZipFile(whl); names = z.namelist(); z.close(); sys.exit(0 if any('py.typed' in n for n in names) else print('py.typed NOT found in ' + whl, file=sys.stderr) or 1)" && echo "py.typed found in wheel: OK"

ci:  ## Run local CI equivalent (single interpreter; NOT a full substitute for the 3.10/3.11/3.12 matrix in GitHub Actions)
	ruff check src/ tests/
	ruff format --check src/ tests/
	mypy src/easy_sandbox/
	pytest tests/ -m "not integration"
	rm -rf build/ dist/
	python -m build
	twine check dist/*
	@python -c "import zipfile, glob, sys; whl = glob.glob('dist/*.whl')[0]; z = zipfile.ZipFile(whl); names = z.namelist(); z.close(); sys.exit(0 if any('py.typed' in n for n in names) else print('py.typed NOT found in ' + whl, file=sys.stderr) or 1)" && echo "py.typed found in wheel: OK"
	@echo "Note: this runs on a single Python interpreter; the Python 3.10/3.11/3.12 matrix can only be fully covered by GitHub Actions CI."

hooks:  ## Install pre-commit (called automatically via .githooks/pre-commit)
	pip install pre-commit
	@echo "pre-commit installed. It will be called automatically via .githooks/pre-commit."

clean:  ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
