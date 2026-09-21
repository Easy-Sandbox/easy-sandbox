# Decision: E2B Compatibility Layer

Status: proposed

## Problem
E2B users need a migration path to switch from the official E2B SDK to Easy Sandbox with minimal code changes.

## Decision
`compat/sandbox.py` provides E2B-compatible `Sandbox` wrapper:
- Same method names and signatures as `e2b` Python SDK
- `from easy_sandbox.compat import Sandbox` as drop-in replacement
- Translates E2B-style calls to native Easy Sandbox API calls
- Supports E2B environment variables (`E2B_API_KEY` → `SANDBOX_API_KEY`)

Compatibility scope: core sandbox lifecycle, process execution, file operations. E2B-specific features not available on Alibaba Cloud raise `NotImplementedError` with migration guidance.

## Alternatives considered
- **Full E2B SDK wrapper** — Adds e2b as dependency, defeats the purpose
- **No compatibility** — Forces users to rewrite all code
- **Adapter pattern** — Same result, more abstract naming

## Dependencies
- `api/sandbox.py` for native Sandbox operations

## Test Strategy
- E2B code samples work unchanged with compat import
- E2B environment variables mapped correctly
- NotImplementedError for unsupported E2B features

## Acceptance criteria
- `from easy_sandbox.compat import Sandbox` is a drop-in replacement for `from e2b import Sandbox`
- Core E2B workflows work without code changes
- Unsupported features fail with clear error messages
