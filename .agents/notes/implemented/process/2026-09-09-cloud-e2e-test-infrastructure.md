# Decision: Cloud end-to-end test infrastructure

Status: implemented

## Problem
The project previously had only local unit tests (a mocked backend) and could not
validate the full functionality of the SDK/CLI/Server against a real Alibaba Cloud
FC Agent Sandbox environment. A cloud E2E test infrastructure was needed, covering:

1. Basic-capability validation of the official prebuilt templates
   (`code-interpreter-v1`, `base`).
2. Full build → deploy → run validation of the custom templates (the 10 templates
   under `examples/templates/`).
3. Parallel execution to shorten total test time.

## Decision
Create a `scripts/cloud_e2e_test.py` script that organizes test cases into two
scenarios (Parts) and supports parallel execution.

### Scenario A: official prebuilt templates (Part 1)

Validate the CLI + SDK envd capabilities (shell/files/code) of existing platform
templates:
- **Templates**: `code-interpreter-v1` (templateID: `8d926meb1xzckz1a83ib`),
  `base` (templateID: `216g37mamkdfhzrauvxk`)
- **Test content**: `ebx create`/`ebx exec` (CLI) + `Sandbox.create()`/
  `sandbox.commands.run()` (SDK)
- **Capabilities covered**: shell command execution, file read/write, code interpreter

### Scenario B: custom templates (Part 2)

Validate the full chain CLI local build → ACR push → template creation → sandbox
startup → Server capabilities:
- **Templates**: the 10 templates under `examples/templates/` (python-hello, codex,
  node-web, browser-automation, claude-code, deepseek-harness, hermes-agent,
  openclaw, qoder, qwen-code)
- **Test content**: `ebx template build-local` (CLI) + `DockerBuilder` (SDK) +
  Sandbox Server capabilities
- **Capabilities covered**: Docker build, ACR push, template registration, sandbox
  creation, Server startup and invocation

### Parallel architecture

- `MAX_CONCURRENCY = 5` — maximum number of concurrent sandboxes
- Uses `asyncio.Semaphore` to control concurrency
- Each test case creates/destroys its own sandbox independently, without interference
- Test results are summarized in the output (pass/fail/skip)

### Credential configuration

Configured via a `.env` file in the project root (already in `.gitignore`):
- `E2B_API_KEY` — the FC Agent Sandbox platform API key
- `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` — the Alibaba
  Cloud AK/SK required for ACR push

## API Design
```bash
# run all E2E tests
cd <project-root>
python3 scripts/cloud_e2e_test.py

# dependencies
pip install "easy-sandbox[cli]" httpx pyyaml python-dotenv
```

```python
# core structure
OFFICIAL_TEMPLATES = {
    "code-interpreter-v1": "8d926meb1xzckz1a83ib",
    "base": "216g37mamkdfhzrauvxk",
}

CUSTOM_TEMPLATES = [
    "python-hello", "codex", "node-web", "browser-automation",
    "claude-code", "deepseek-harness", "hermes-agent",
    "openclaw", "qoder", "qwen-code",
]

MAX_CONCURRENCY = 5
```

## Alternatives considered
- **Integrate into the standard test suite with pytest + pytest-asyncio** — E2E
  tests require real credentials and are slow (minutes-scale); mixing them into the
  unit tests would slow down `make test`. A standalone script is more flexible.
  Rejected as the default approach (but can be bridged via
  `@pytest.mark.integration`).
- **Single-threaded sequential execution** — building the 10 custom templates
  sequentially takes too long. Rejected.
- **Use a service container in GitHub Actions** — the FC sandbox is a remote
  service, not a local container, and cannot be simulated with a service container.
  Rejected.

## Dependencies
- `api/sandbox.py` (`Sandbox.create()` SDK interface)
- `api/template.py` (`TemplateManager` template management)
- `api/docker_builder.py` (`DockerBuilder` local build)
- `transport/auth.py` (`create_auth_provider` authentication)
- `transport/config.py` (`load_config` configuration loading)
- `examples/templates/` (the 10 custom-template directories)

## Test Strategy
- Scenario A, per official template: create sandbox → run shell command → verify
  output → destroy sandbox.
- Scenario B, per custom template: build image → push to ACR → create template →
  create sandbox → start Server → invoke command → destroy.
- Failing cases record a detailed traceback and do not block other cases.
- Final output is a summary table (pass count / fail count / skip count).

## Acceptance criteria
- `python3 scripts/cloud_e2e_test.py` runs end to end after `.env` credentials are configured.
- Both official and custom templates have independent test cases.
- Parallel execution never exceeds `MAX_CONCURRENCY` concurrent sandboxes.
- Test results have a clear summary output.

## Files changed
- `scripts/cloud_e2e_test.py` — new, 922 lines
