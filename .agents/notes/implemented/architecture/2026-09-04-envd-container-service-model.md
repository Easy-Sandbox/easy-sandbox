# Decision: envd Two-Layer Container Service Model (Image-Baked envd/Gateway + User Opt-in Server Module)

Status: implemented
Task: #94, #105, #118

## Problem
The responsibility boundary between the SDK and the in-container service processes is unclear. The core question: who provides the in-container files/process/code/PTY/ports services — the user/template, or the platform side? And when a user needs a long-running service (e.g. a self-hosted HTTP server), how should it be exposed — as a replacement for envd, or layered on top of envd?

## Decision
Adopt a two-layer model of **image-baked envd/Gateway + a user opt-in server module**.

### Layer 1: envd and Gateway are baked into the FC official base image and started by the entrypoint

> **⚠ Key fact correction (2026-09-05)**: an earlier version of this ADR incorrectly described envd as "injected by the platform runtime" or "injected at build time". After pulling and inspecting the official image (see `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md`), it is confirmed that envd and Gateway are static Go binaries **baked into the FC official base image**, not dynamically injected by the platform runtime or at build time.

1. **There are two Go servers in the container, both statically linked binaries baked into the FC official base image**:
   - **Gateway** (`/.fce2b/entrypoint`, port 5000): reverse proxy + PID1 process manager. Started as the `ENTRYPOINT`, it manages the lifecycle of all child processes (including starting envd) and routes requests via `proxy.(*Router)` to envd, the Code Interpreter, or dynamic port services.
   - **envd** (`/.fce2b/envd`, port 49983): the E2B standard daemon (v0.1.14), providing the standard protocol surfaces for files (HTTP REST + Connect), process (Connect streaming), code (Connect), and terminal/PTY (WebSocket).
2. **Key capabilities of the Gateway reverse-proxy layer**:
   - `routeEnvd`: proxies envd requests (/health, /metrics, /envs, /files/*, etc.) to 127.0.0.1:49983
   - `routeCI`: proxies Code Interpreter requests to 127.0.0.1:49999 (when enabled)
   - **`routeDynamic`: dynamic port routing** — proxies a request to the matching port based on the `X-Sandbox-Port` header. This is the underlying mechanism that lets a user's self-hosted server be reached from outside.
   - Process management (`process.(*Manager).StartAll`), zombie-process reaping (`process.(*Reaper)`), startup-readiness guard (`proxy.(*StartupGuard).WaitForBackend`)
3. **Startup chain**: `docker run → /.fce2b/entrypoint (PID 1)` → start envd (49983) → start the reverse-proxy Router (5000) → wait for `/init` initialization.
4. **The envd binary is not replaceable**. Its version is determined by the image (the `envd_version` field in `models/sandbox.py` merely consumes the value returned by the platform). This repository contains no envd implementation.
5. **builder mode**: the platform performs "pull → add cloud-sandbox runtime dependencies (including the envd/Gateway binaries) → push as the target image" on the user's source image. Essentially it merges the official base image's `/.fce2b/` directory into the user's image.
6. **direct mode contains no envd**: the source image must already ship the E2B runtime dependencies, otherwise all envd-backed capabilities (files/process/code/PTY) are unavailable.

### Layer 2: the user opt-in easy_sandbox.server module

> **⚠ Key fact correction (2026-09-05)**: an earlier version of this ADR claimed "the SDK does not ship an in-container server". That decision has been reversed. A user opt-in `easy_sandbox.server` module is added; see `2026-09-05-sandbox-server-module.md`.

7. **The SDK adds an `easy_sandbox.server` module**: a stdlib-only, zero-dependency in-container HTTP server that the user starts proactively via `sandbox.server.start()` (not a fallback agent, not auto-deployed). It ships built-in `upload`/`download`/`runshell` commands that operate directly on the local filesystem (not bound to the envd API).
8. **This is not a fallback agent**: envd remains the base carrier for standard capabilities. The server module's role is to provide HTTP endpoint registration for **user-defined commands**, invoked via `POST /commands/{name}` and reached by the client through `https://{port}-{sandbox_id}.{domain}`.
9. **ports capability gating**: the server module requires the template to explicitly declare `capabilities: [..., ports]`. `ports` is not in `DEFAULT_CAPABILITIES = {shell, files, code}`.
10. **The former "circular dependency" argument no longer applies**: the server module is user-deployed business logic (delivered and started via `files.write` + `commands.start`); its role is entirely different from a "fallback that replaces envd". Its dependency on envd is a normal upper→lower layer dependency and does not form a cycle.

## API Design
```python
# envd standard path (unchanged)
# envd:   https://49983-{sandbox_id}.{domain}

# User opt-in server module (new)
await sandbox.server.start()  # start the in-container HTTP server
result = await sandbox.server.call("runshell", cmd="ls -la")
# via POST https://{port}-{sandbox_id}.{domain}/commands/runshell

# User's own standalone server (still supported)
reader = await sandbox.commands.start("node server.js", cwd="/app", timeout=300)
url = sandbox.network.get_url(3000)           # https://{3000}-{sandbox_id}.{domain}
headers = sandbox.network.get_access_headers() # X-Access-Token in secure mode
```

## Alternatives considered
- **SDK ships a fallback in-container agent (replacing envd)** — Circular dependency (the delivery mechanism depends on envd) + nowhere to place it (with no envd, the SDK cannot connect in). Rejected.
- **User replaces the envd binary** — envd's version is controlled by the image; this repository provides no replacement channel. Rejected.
- **User ships a full runtime in direct mode** — Technically feasible, but the cost is losing the out-of-the-box guarantee of all standard capabilities. Advanced users only.
- **FastAPI/Flask as the server module** — Introduces third-party dependencies, violating the zero-dependency principle. Rejected.
- **Keep source-delivery execution (no server)** — Every call requires the full files.write + commands.run chain, with high latency and no persistence. Rejected in favor of a persistent HTTP server.

## Dependencies
- `transport/config.py` (`ENVD_PORT = 49983`, `build_envd_url`)
- `transport/auth.py` (`EnvdTokenManager`, the four envd headers)
- The entire `protocol/` layer's Connect/HTTP/WS protocol implementations
- `2026-09-03-capability-model.md` (`DEFAULT_CAPABILITIES` does not include `ports`)
- `2026-09-03-command-source-resolution.md` (built-in templates have no YAML → `ports` unavailable)
- `2026-09-05-sandbox-server-module.md` (server module architecture decision)
- Alibaba Cloud official docs: "Building Custom Image Templates", "E2B Compatibility Notes"
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md` (on-site image inspection evidence)

## Test Strategy
- Real closed-loop validation (O1): a minimal `FROM ubuntu:22.04` image → `ebx template build` → `ebx create` → `ebx exec "echo ok"` + `files.write`. Success confirms the builder-mode merge.
- `commands.start(background=True)` + `network.get_url(port)` end-to-end reachability.
- When a template does not declare `ports`, calling `network.get_url()` should raise `CapabilityNotSupportedError(E3004)`.
- Server module functional validation: see `2026-09-05-sandbox-server-module.md`.

## Acceptance criteria
- Clear documentation: envd/Gateway are baked into the FC official base image (not runtime-injected), started by the entrypoint process manager.
- The SDK adds the opt-in `easy_sandbox.server` module, started proactively by the user via `sandbox.server.start()`.
- A user's own server can still use the `commands.start` + `network.get_url` pattern.
- No documentation still describes "envd is runtime-injected / platform-injected".

## Evidence
- `.agents/evidence/research/2026-09-04-container-serve-boundary.md` §0–§4, §6.7
- `.agents/evidence/research/2026-09-04-fc-claude-code-image-inspection.md` (on-site image inspection, confirming envd/Gateway are image-baked)
