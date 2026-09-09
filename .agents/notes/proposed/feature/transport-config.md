# Decision: Layered Configuration Loading

Status: proposed

## Problem
Configuration comes from multiple sources with different priorities. Need a clean, lazy-loaded config system.

## Decision
Pydantic BaseSettings in `transport/config.py`. Priority (highest to lowest):
1. Code parameters (passed directly to constructors)
2. Environment variables (`SANDBOX_*` prefix)
3. `.env` file in project root
4. `~/.sbox/config.toml` user config file
5. Built-in defaults

Lazy loading: file I/O (`.env`, `config.toml`) only performed on first access, not at import time.

## Alternatives considered
- **Plain dict config** — No validation, no type safety
- **dynaconf** — Additional heavy dependency
- **Eager loading** — Slows down import time, bad for CLI startup

## Dependencies
- `pydantic>=2.0` (BaseSettings)
- `python-dotenv>=1.0`
- `tomli` (stdlib in 3.11+, fallback for 3.10)

## Test Strategy
- Priority override verification (each level overrides the next)
- Lazy loading verification (no file I/O on import)
- Missing config graceful handling

## Acceptance criteria
- Config loads correctly from all sources with correct priority
- First import has zero file I/O
- Invalid config values produce clear error messages
