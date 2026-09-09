# Decision: Snapshot/Hibernate/Persistent Sandbox Deferred to Future

Status: implemented

## Problem
Snapshot, hibernate, and persistent sandbox features are valuable but the underlying Alibaba Cloud FC sandbox service does not currently support them.

## Decision
Mark snapshot, hibernate, and persistent sandbox as 🔮 远期规划 (future roadmap). The API surface reserves parameters (`persistent`, `name`, `hibernate_after`, `on_exit`) but they are documented as not-yet-available. Implementation will proceed when the cloud service adds support.

## Alternatives considered
- **Implement client-side simulation** — Complex, unreliable, confuses users
- **Remove from API design** — Loses forward compatibility

## Dependencies
- Alibaba Cloud FC sandbox service roadmap

## Test Strategy
- N/A (deferred)

## Consequences
- API is forward-compatible — parameters exist but raise NotImplementedError
- No wasted effort on features without backend support
- Clear documentation prevents user confusion
