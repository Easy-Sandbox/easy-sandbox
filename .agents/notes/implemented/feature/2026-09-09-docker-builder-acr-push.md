# Decision: Local Docker build and ACR push capability

Status: implemented

## Problem
The custom-template build flow previously supported only platform-side build
(uploading the Dockerfile to the backend API), which had the following limits:

1. **Hard to debug**: the build runs remotely, error messages are opaque, and it
   cannot be debugged with a local `docker build`.
2. **No ACR push capability**: platform-side build requires the image to already
   exist in ACR (the v2 API `from_image` parameter), but the SDK provided no
   full chain from local build to ACR push.
3. **CLI lacks a local-build command**: users could not perform "build → push →
   register template" in one shot through the `ebx` CLI.

## Decision
Add the `api/docker_builder.py` module, which provides a `DockerBuilder` class
that encapsulates the full local build → ACR push → template registration flow.

### Core flow

1. **Local Docker build**: invoke a `docker build` subprocess, supporting
   `--platform`, `--build-arg`, `--no-cache`, and other arguments.
2. **ACR login**: use the Alibaba Cloud AK/SK to generate a temporary credential
   and run `docker login` against the ACR instance.
3. **Image push**: `docker tag` + `docker push` push the local image to ACR.
4. **Template registration**: call the v3 API in `protocol/template.py` to create
   template metadata, then call the v2 API to trigger the build (with
   `from_image` pointing at the ACR image).

### New error classes

Three new error classes (E7020–E7022) are added in `models/errors.py`:
- `DockerBuildError(E7020)` — local Docker build failed
- `ACRPushError(E7021)` — ACR push failed
- `ACRLoginError(E7022)` — ACR login failed

### CLI command

Add the `ebx template build-local` subcommand:
```bash
ebx template build-local ./examples/templates/python-hello \
    --acr-namespace my-ns --acr-repo python-hello

ebx template build-local ./my-template \
    --acr-namespace prod --acree-instance-id cri-xxx
```

### v3/v2 API methods

Two new methods are added in `protocol/template.py` (aligned with E2B SDK 2.31.0):
- `create_v3(name, ...)` → `POST /v3/templates` — create template metadata,
  returns templateID + buildID.
- `trigger_build_v2(template_id, build_id, from_image, ...)` →
  `POST /v2/templates/{tpl}/builds/{build}` — trigger the build from an ACR image.

## API Design
```python
# api/docker_builder.py
@dataclass
class ACRConfig:
    registry: str          # e.g. "registry.cn-hangzhou.aliyuncs.com"
    namespace: str
    repo: str
    username: str          # AK ID
    password: str          # AK Secret
    acree_instance_id: str | None = None  # ACR EE instance ID

class DockerBuilder:
    async def build_and_push(
        self,
        template_dir: str | Path,
        acr_registry: str,
        acr_namespace: str,
        acr_repo: str,
        acr_username: str,
        acr_password: str,
        *,
        acree_instance_id: str | None = None,
        platform: str = "linux/amd64",
        tag: str | None = None,
        no_cache: bool = False,
    ) -> dict[str, Any]: ...
```

```python
# protocol/template.py — new methods
class TemplateProtocol:
    async def create_v3(self, name, *, dockerfile=None, ...) -> dict[str, Any]: ...
    async def trigger_build_v2(
        self, template_id, build_id, from_image, *, acr_headers=None, ...
    ) -> dict[str, Any]: ...
```

```python
# models/errors.py — new error codes
class DockerBuildError(SandboxError):
    code = "E7020"

class ACRPushError(SandboxError):
    code = "E7021"

class ACRLoginError(SandboxError):
    code = "E7022"
```

## Alternatives considered
- **Support platform-side build only (upload the Dockerfile)** — hard to debug,
  slow builds, cannot leverage the local Docker cache. Rejected as the sole option.
- **Use the Docker SDK for Python (docker-py)** — introduces an extra dependency;
  invoking the `docker` CLI via `subprocess` is lighter and more transparent to
  the user. Rejected.
- **Use the Registry HTTP API v2 for ACR push (bypassing the docker CLI)** —
  requires implementing the full manifest/blob upload protocol; high complexity.
  Rejected.
- **Hardcode AK/SK in the script** — security risk; must use environment
  variables or a `.env` file. Rejected.

## Dependencies
- `models/errors.py` (`DockerBuildError`/`ACRPushError`/`ACRLoginError` error classes)
- `protocol/template.py` (`create_v3`/`trigger_build_v2` platform-API methods)
- `transport/http.py` (`HttpClient.platform_request` HTTP request)
- `utils/logging.py` (structured logging)
- External: `docker` CLI installed locally

## Test Strategy
- Unit: `DockerBuilder` argument validation, `ACRConfig` dataclass construction.
- Mock: mock `subprocess.run` and verify that `docker build`/`docker login`/
  `docker push` commands are assembled correctly.
- Error scenarios: Docker not installed → `DockerBuildError`; wrong ACR credentials
  → `ACRLoginError`; push failure → `ACRPushError`.
- CLI: `ebx template build-local --help` argument completeness.
- E2E: cover the real build → push → register chain in Scenario B of
  `scripts/cloud_e2e_test.py`.

## Acceptance criteria
- `DockerBuilder.build_and_push()` completes the full "build → login → push →
  register" chain.
- The three new error classes (E7020/E7021/E7022) are raised correctly in their
  respective failure scenarios.
- The `ebx template build-local` CLI command runs the complete flow.
- The v3/v2 API methods in `protocol/template.py` align with E2B SDK 2.31.0.

## Files changed
- `api/docker_builder.py` — new, 851 lines
- `models/errors.py` — added `DockerBuildError(E7020)`, `ACRPushError(E7021)`, `ACRLoginError(E7022)`
- `protocol/template.py` — added `create_v3()`, `trigger_build_v2()` methods
- `cli/commands/template.py` — added `build-local` subcommand
