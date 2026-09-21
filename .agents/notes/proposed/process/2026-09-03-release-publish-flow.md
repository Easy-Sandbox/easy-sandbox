# Decision: Release / Publish Flow for Templates

Status: proposed

## Problem
A template is only "done" once a real user can install it end-to-end from GitHub. We need a defined gate sequence from local development to a published, installable release, and a clear rule about which steps the Agent performs versus the user.

## Decision
Adopt a staged flow with a hard end-to-end gate:
1. **Local install / E2E test passes** — validate the template locally (`ebx install ./path --registry-type local`, create sandbox, run its custom commands).
2. **User pushes to GitHub + cuts a release** — the user (not the Agent) runs `git push` and creates the GitHub release. The Agent never executes `git push`.
3. **Real GitHub install E2E passes** — `ebx install owner/repo --registry-type github` end-to-end against the published release must succeed.
4. Only after step 3 is the work considered complete.

## Alternatives considered
- **Consider "done" at local test** — Misses real registry resolution, release asset packaging, and auth paths; regressions surface only after users hit them.
- **Agent performs `git push` / release** — Out of scope and unsafe; publishing is an outward-facing action reserved for the user.

## Dependencies
- `ebx install` (github + local registry types) — see `docs/design/cli-design.md`
- `2026-09-03-minimal-template-repo.md` (repo shape being published)
- `2026-09-03-command-source-resolution.md` (installed template feeds local cache)

## Test Strategy
- Local: `ebx install ./template --registry-type local` → create → `ebx run` custom command succeeds.
- Published: `ebx install owner/repo --registry-type github` resolves the release and installs.
- Verify capabilities + custom_commands survive the round-trip (declared → installed → resolved).

## Acceptance criteria
- Local install + E2E green before any push.
- A real `ebx install owner/repo --registry-type github` E2E is green after the user publishes.
- The Agent does not run `git push`; publishing is a user step.
