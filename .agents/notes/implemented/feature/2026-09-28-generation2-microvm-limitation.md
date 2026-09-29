# Decision: Use generation=1 (rund) for production; generation=2 has stdout bug

Status: implemented
Implemented: 2026-09-28

## Problem
FC sandbox supports two runtime generations:
- **generation=1** — rund-based containers, mature and stable.
- **generation=2** — MicroVM-based, faster cold starts (~1.6s vs ~3s).

Testing revealed that generation=2 sandboxes start successfully but
`process.Start` RPC calls **do not return output streams** (stdout/stderr are
empty). Commands execute but their output is silently lost, making generation=2
unusable for any workflow that depends on command output (which is virtually
all use cases).

## Decision
Default to `generation=1` for all production sandbox creation. Generation=2
support is retained in the codebase as a configurable option for future use.

### Performance observations
| Metric          | gen=1 (rund) | gen=2 (MicroVM) |
|-----------------|-------------|-----------------|
| Cold start      | ~3s         | ~1.6s           |
| Process stdout  | ✅ works    | ❌ empty        |
| Process stderr  | ✅ works    | ❌ empty        |
| File operations | ✅ works    | ✅ works        |

### When to revisit
Re-test generation=2 when the FC platform announces a fix for the
`process.Start` output stream issue. The switch is a single parameter change
in sandbox creation.

## Alternatives considered
- **Default to gen=2 with a fallback** — output loss is silent and hard to
  detect programmatically; a fallback would add unreliable complexity. Rejected.
- **Remove gen=2 code entirely** — premature; the performance gains are
  significant and the fix is expected. Rejected.

## Files changed
- `src/easy_sandbox/api/sandbox.py` — default `generation=1`
- `src/easy_sandbox/models/sandbox.py` — generation field documentation

## Acceptance criteria
- ✅ `sandbox.create()` defaults to generation=1
- ✅ `sandbox.create(generation=2)` still works for testing
- ✅ Command output is correctly captured with generation=1
