.PHONY: install dev test lint format typecheck clean help

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

clean:  ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
