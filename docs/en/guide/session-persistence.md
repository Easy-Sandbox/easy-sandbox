# Session Persistence

> **Rename notice**: This project has been renamed from Serverless Sandbox to **Easy Sandbox**. PyPI package: `easy-sandbox` (`pip install easy-sandbox`), CLI command: `ebx`, Python import: `easy_sandbox`.

A session associates a sandbox with a human-readable name, making it easy to reconnect to the same sandbox from different terminals or at different times.

---

## Session Concept

A session is a mapping between a sandbox ID and a name. With sessions, you can:

- Use a name instead of a sandbox ID to operate on a sandbox
- Connect to the same sandbox from different terminal windows
- Reconnect after a temporary disconnection

### Session Data Model

Each session contains the following information (`SessionInfo`):

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Session name |
| `sandbox_id` | `str` | Associated sandbox ID |
| `template` | `str` | Template used |
| `created_at` | `datetime` | Creation time |
| `metadata` | `dict` | Metadata |

---

## Local Storage

Sessions use local filesystem storage by default, implemented by `LocalSessionStore`.

### Storage Location

```text
~/.ebx/sessions/
├── my-project.json       # Session "my-project"
├── my-project.json.lock  # Concurrency lock file
├── dev-env.json          # Session "dev-env"
└── ...
```

Each session is saved as a JSON file, with the filename derived from the session name (non-alphanumeric/hyphen/underscore characters are replaced with `_`).

### Concurrency Protection

File reads and writes are protected by file locks:
- Prefers the `filelock` library (if installed)
- Falls back to POSIX `fcntl` locks (macOS/Linux)

---

## CLI Usage

### Start a Session

```bash
ebx session start my-project --template base --timeout 600
ebx session start dev-env --template base --env MY_KEY=value
```

Starting a session creates a new sandbox and records the mapping.

### Connect to a Session

```bash
ebx session connect my-project
# Enters an interactive shell
```

### List Sessions

```bash
ebx session list
# Shows all local sessions and their statuses
```

### View Session Info

```bash
ebx session info my-project
```

### Stop a Session

```bash
# Stop and destroy the sandbox
ebx session stop my-project

# Only untrack, do not destroy the sandbox
ebx session stop my-project --keep-alive
```

---

## SDK Usage

```python
from easy_sandbox.session.local import LocalSessionStore
from easy_sandbox.models.session import SessionInfo

# Create a store instance
store = LocalSessionStore()  # Default ~/.ebx/sessions/

# Save a session
session = SessionInfo(
    name="my-project",
    sandbox_id="sbx-xxxx",
    template="base",
)
await store.save("my-project", session)

# Load a session
session = await store.load("my-project")
if session:
    print(f"Sandbox: {session.sandbox_id}")

# List all sessions
sessions = await store.list_all()

# Delete a session
await store.delete("my-project")
```

---

## Custom Storage Location

```python
store = LocalSessionStore(base_dir="/path/to/custom/sessions")
```

---

## Next Steps

- [CLI Tutorial](cli-tutorial.md) — Complete CLI tutorial
- [Configuration Reference](../reference/configuration.md) — Config file locations
