# Quickstart Demos

Quickstart demos showing core **Easy Sandbox** SDK capabilities — sandbox lifecycle, file operations, web services, data analysis, and declarative execution.

## Prerequisites

- Python 3.9+
- `pip install easy-sandbox` (or dev install from repo root: `pip install -e ".[dev]"`)
- Environment variables:

```bash
# Load from .env file
export $(grep -v '^#' ../../.env | xargs)

# Or set manually
export E2B_API_KEY=your-api-key
export E2B_API_URL=https://api.cn-hangzhou.e2b.fc.aliyuncs.com
export E2B_DOMAIN=e2b.fc.aliyuncs.com
```

## Demo List

| Demo | Description | Template |
|------|-------------|----------|
| `01_hello.py` | Basic sandbox creation, command execution, env vars, lifecycle | `base` (built-in) |
| `02_file_ops.py` | File read/write, directories, binary files, move/delete | `base` (built-in) |
| `03_web_service.py` | Node.js web service running inside a sandbox | `node-web` (custom, must deploy first) |
| `04_data_analysis.py` | pandas data analysis, CSV processing | `base` (built-in) |
| `05_decorator_usage.py` | `@sandbox` decorator for declarative execution | `code-interpreter-v1` (built-in) |

## Running

```bash
cd examples/quickstart
python 01_hello.py
```

## Test Results (2026-09-28)

Executed against a real FC backend.

### 01_hello.py — PASS

```
✓ Sandbox created  id=sbx-d658520b...  status=running
stdout : Hello from Sandbox!
exit   : 0
System info: Linux-5.10.134-...x86_64-with-glibc2.41
MY_VAR = hello-sandbox
Root dir top 5: bin boot dev etc home
Command failed (exit=2): ls: cannot access '/nonexistent': No such file or directory
Sandbox running: True
✓ Sandbox auto-destroyed
```

### 02_file_ops.py — PASS

```
✓ Sandbox created: sbx-8809102e...
✓ Wrote /app/hello.txt
Content: 你好，Sandbox！Hello, Sandbox!
✓ Created directory /app/data/reports
  Wrote config.json, notes.txt, reports/summary.csv
/app/data contents: config.json (33 bytes), notes.txt (41 bytes), reports (4096 bytes)
✓ Wrote binary file 256 bytes
✓ Move/delete operations succeeded
✓ Sandbox auto-destroyed
```

### 03_web_service.py — FAIL (requires node-web custom template)

```
Requires deploying a template with the `ports` capability.
Install & deploy the node-web template from the source-of-truth repo first:
  ebx template install node-web
  ebx template deploy ~/.ebx/templates/Easy-Sandbox/awesome-templates/default/node-web
Failure reason: template not ready, sandbox creation timed out
```

### 04_data_analysis.py — PASS

```
✓ Sandbox created
pandas installed, CSV analysis correct
Total rows 12, total sales $64,785.65
Product/region aggregation correct
CodeInterpreter 404 → shell fallback (expected behavior)
✓ Sandbox auto-destroyed
```

### 05_decorator_usage.py — PASS

```
π ≈ 3.143256  error 0.001663
Data analysis: rows 4, columns ['name','age','score']
Fibonacci first 15: [0,1,1,2,3,5,8,13,21,34,55,89,144,233,377]
Env var: APP_MODE=sandbox-demo
✓ All examples completed
```

## Notes

- Most demos use built-in templates (`base`, `code-interpreter-v1`) — no extra deployment needed.
- `03_web_service.py` requires deploying the `node-web` custom template first.
- When CodeInterpreter is unavailable, the SDK automatically falls back to shell execution (expected behavior).
- Sandboxes are managed via `async with` for automatic lifecycle cleanup.
