# Decision: Full audit and completion of CLI help texts

Status: implemented
Implemented: 2026-09-29

## Problem
CLI help texts were inconsistent and incomplete:

- Many commands lacked usage examples in their help output.
- Parameters did not document their valid value ranges.
- No "Related commands" section to guide users to related functionality.
- The generated CLI reference documentation was out of sync with actual
  command signatures.

## Decision
Perform a comprehensive audit of all 64 CLI commands and command groups:

1. **Examples section:** Every command gets an `Examples:` block in its help
   text showing 1–3 practical usage patterns.
2. **Related commands:** Every command includes a `Related commands:` section
   pointing to logically related commands.
3. **Parameter value ranges:** All parameters with constrained values include
   the valid range in their help string (e.g., `--format [table|json|yaml]`,
   `--timeout INTEGER (30-600)`).
4. **CLI reference docs:** Auto-generate `docs/en/reference/cli-reference.md`
   and `docs/zh/reference/cli-reference.md` from the audited help texts.

## API Design
N/A — this decision does not involve API changes. CLI help text only.

## Alternatives considered
- **Generate help text from a schema file** — adds a build step and
  indirection; Click's built-in help decorators are sufficient. Rejected.
- **Only fix commands with known issues** — incomplete coverage; the audit
  found gaps in nearly every command. Rejected.

## Dependencies
- Click framework's `@click.command(epilog=...)` for examples/related sections

## Test Strategy
- CLI evidence golden files regenerated to capture new help output.
- Manual review of `ebx --help` and `ebx <cmd> --help` for all 64 commands.

## Files changed
- `src/easy_sandbox/cli/commands/*.py` — help text updates across all command modules
- `docs/en/reference/cli-reference.md` — regenerated
- `docs/zh/reference/cli-reference.md` — regenerated

## Acceptance criteria
- ✅ All 64 commands have Examples and Related commands sections
- ✅ All constrained parameters show valid value ranges
- ✅ CLI reference docs match actual command signatures
