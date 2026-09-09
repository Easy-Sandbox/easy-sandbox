# Decision: Custom Commands Schema for Templates

Status: implemented

## Problem
Templates need a way to expose named, parameterized commands (e.g. `serve`, `migrate`, `test`) so users and Agents can invoke high-level operations without knowing the underlying shell invocation. The mechanism must accept user-supplied arguments safely (no shell injection).

## Decision
Add an optional `custom_commands:` map to `template.yaml`. Each entry is keyed by `name` and describes how to build a shell command from user arguments:

```yaml
custom_commands:
  serve:
    cmd: "python -m http.server {port}"   # {placeholder} filled from args
    description: "Start a static file server"
    cwd: "/app"                            # default: /app
    env: {}                                # default: {} (empty)
    timeout: 60                            # default: 60 (seconds)
    args:
      - name: port
        default: "8000"
        required: false
        description: "Port to listen on"
```

Field semantics:
- `cmd` (required): command template with `{placeholder}` tokens matching `args[].name`.
- `description`: human/Agent-facing summary.
- `cwd`: working directory (default `/app`).
- `env`: extra environment variables (default empty).
- `timeout`: seconds (default `60`).
- `args`: list of `{name, default, required, description}`. `required` args without a value raise an error before execution.

**Injection safety**: each user-supplied argument value is escaped with `shlex.quote()` before being substituted into the `{placeholder}`. Placeholders are only filled from declared `args`; unknown placeholders or undeclared user args are rejected.

## API Design
```python
# models/template.py
class CommandArg(BaseModel):
    name: str
    default: str | None = None
    required: bool = False
    description: str = ""

class CustomCommand(BaseModel):
    cmd: str
    description: str = ""
    cwd: str = "/app"
    env: dict[str, str] = {}
    timeout: int = 60
    args: list[CommandArg] = []

# Template model gains:
custom_commands: dict[str, CustomCommand] = {}

# Resolution (pseudocode):
#   values = {a.name: provided.get(a.name, a.default) for a in cmd.args}
#   missing_required -> raise
#   final = cmd.cmd.format(**{k: shlex.quote(v) for k, v in values.items()})
```

## Alternatives considered
- **Free-form shell strings passed by the user** — Reintroduces injection risk and gives no discoverability.
- **String interpolation without `shlex.quote()`** — Vulnerable to argument injection.
- **JSON-schema per command** — Over-engineered for the small, fixed arg shape.

## Dependencies
- `models/template.py` (Pydantic models)
- `2026-09-03-cli-run-vs-exec.md` (`sbox run` dispatches these)
- `2026-09-03-sdk-capability-surface.md` (`sandbox.run("name", **args)`)

## Test Strategy
- Placeholder substitution with defaults, required-missing error, and unknown-arg rejection.
- `shlex.quote()` escaping test with adversarial values (spaces, `;`, `$()`, quotes).
- Model roundtrip: parse `custom_commands` from YAML and re-serialize.

## Acceptance criteria
- A template declaring `custom_commands.serve` can be invoked with `--arg port=9000` and produces the correctly quoted command.
- Missing a `required` arg fails before any command runs.
- Malicious arg values cannot break out of the intended command.
