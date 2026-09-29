# Decision: Remove all Serverless Sandbox → Easy Sandbox rename notices

Status: implemented
Implemented: 2026-09-29

## Problem
After the project was renamed from "Serverless Sandbox" to "Easy Sandbox",
rename notices (blockquotes explaining the name change) were added to 41
documentation files. However, the project has **not been publicly released**
yet — there are no external users who need to be informed of a name change.
These notices:

- Add visual clutter to every documentation page.
- Imply a migration history that does not exist for end users.
- Will be confusing to new users who never knew the old name.

## Decision
Delete all rename-related blockquote notices across the documentation tree.
Since the project is pre-release, no migration notice is needed.

## API Design
N/A — this decision does not involve API changes.

## Alternatives considered
- **Keep notices until v1.0 release** — adds noise for the entire pre-release
  period with no audience to serve. Rejected.
- **Move notices to a single changelog entry** — acceptable but unnecessary
  for a pre-release project. The rename is already in git history. Rejected.

## Dependencies
None.

## Test Strategy
- Grep for "Serverless Sandbox" across docs/ to confirm removal.
- Verify no broken links or references after cleanup.

## Files changed
- 41 files across `docs/en/` and `docs/zh/` — removed rename blockquotes

## Acceptance criteria
- ✅ No "Serverless Sandbox" rename notices remain in documentation
- ✅ No broken references introduced by the removal
