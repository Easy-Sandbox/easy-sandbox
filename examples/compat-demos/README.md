# Compatibility Demos

These demos showcase **E2B-compatible** (imperative) and **Modal-style** (declarative) API patterns, plus a full E2E capability validation suite. They verify that Easy Sandbox works as a drop-in replacement for E2B while also supporting the more concise `@sandbox` decorator approach.

## Prerequisites

- Python 3.10+
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

| Demo | Description | API Style | Template |
|------|-------------|-----------|----------|
| `comparison.py` | E2B vs Modal style side-by-side comparison | Both | `base` / `code-interpreter-v1` |
| `e2b_data_analysis.py` | CSV data analysis with pandas (E2B imperative) | E2B | `base` |
| `e2b_web_scraper.py` | Web scraping with requests + BeautifulSoup | E2B | `base` |
| `e2e_capability_validation.py` | Full E2E validation (GitHub install, E2B-compat, Modal, custom template) | Both | `base` / `code-interpreter-v1` |
| `modal_compute.py` | Monte Carlo / Fibonacci / matrix computation | Modal | `code-interpreter-v1` |
| `modal_data_analysis.py` | Same data analysis as E2B demo but declarative | Modal | `code-interpreter-v1` |

## Running

```bash
cd examples/compat-demos
python comparison.py
python e2b_data_analysis.py
# ... etc.
```

## Test Results (2026-09-28)

Executed against a real FC backend (`cn-hangzhou`). All 6 demos passed.

### comparison.py — PASS

```
Task 1: Fibonacci (n=20)
  E2B style:  [0, 1, 1, 2, ..., 4181]  耗时 2.04s
  Modal style: [0, 1, 1, 2, ..., 4181]  耗时 1.97s
  ✓ Results match: True
Task 2: Sort & Statistics
  E2B style:  sorted=[3.7..94.0] mean=47.15 median=49.70 std=30.97  耗时 29.85s
  Modal style: sorted=[3.7..94.0] mean=47.15 median=49.70 std=30.97  耗时 3.97s
✓ Comparison demo completed
```

### e2b_data_analysis.py — PASS

```
✓ Sandbox created id=sbx-40c847fb...
✓ pandas installed
✓ Wrote /app/data.csv, uploaded analyze.py
Sales Analysis Report:
  Total records: 15, Total revenue: ¥46,350.00
  Daily avg: ¥3,090.00, Avg order: ¥3,090.00
  Product breakdown:
    Widget A  qty=111  rev=¥16,650.00
    Widget B  qty=128  rev=¥19,200.00
    Widget C  qty=35   rev=¥10,500.00
  🏆 Top product: Widget B (¥19,200.00)
✓ Report saved, JSON summary saved
✓ Sandbox auto-destroyed
```

### e2b_web_scraper.py — PASS

```
✓ Sandbox created id=sbx-40f09b94...
✓ requests + beautifulsoup4 installed (requests=2.34.2, bs4=4.15.0)
✓ Uploaded scraper.py, executed
Fetching: https://example.com
  Title: Example Domain, Status: 200
  Headings: 1, Paragraphs: 2, Links: 1
  [h1] Example Domain
  [Learn more] → https://iana.org/domains/example
✓ JSON result saved (502 chars)
✓ Sandbox auto-destroyed
```

### e2e_capability_validation.py — PASS (15 pass / 0 fail / 3 blocked)

```
Part A — GitHub install pipeline
  [PASS   ] A-00 rate_limit: anonymous core remaining=0/60
  [BLOCKED] A-01 github install: anon rate limit exhausted, no GITHUB_TOKEN
  [PASS   ] A-02 local install: local pipeline OK, TemplateID=9k0lq3mhdamdm7hy3cgb
  [BLOCKED] A-03 cache landing: no real GitHub install this run (A-01 BLOCKED)
Part B — E2B-compat (real FC, template="base")
  [PASS   ] E2B-01 shell: stdout='hello' exit_code=0
  [PASS   ] E2B-02 files: read='world' exists=True
  [PASS   ] E2B-03 code: text='5' (CodeInterpreter 404 → shell fallback)
  [PASS   ] E2B-04 workflow: fib(10)=55
  [PASS   ] E2B-05 ports-access: get_host(9000) OK
  [PASS   ] E2B-08 files dir ops: list/create/remove OK
  [PASS   ] E2B-09 stream: joined_stdout='chunk-a\nchunk-b'
  [BLOCKED] E2B-06 ports-pos: no READY ports-capable template available
  [PASS   ] E2B-07 lifecycle: is_running=True, destroyed_after_kill=True
  [PASS   ] E2B-03b code@ci-v1: run_code on code-interpreter-v1 OK
Part C — Modal declarative (real FC, template="code-interpreter-v1")
  [PASS   ] MOD-01 add: add(1,2)=3
  [PASS   ] MOD-02 numpy: numpy.pi=3.141592653589793
  [PASS   ] MOD-04 cross-check: modal=42 e2b=42
Part D — Custom template
  [PASS   ] D-01 custom template: sandbox created from stub template
Totals: PASS=15, FAIL=0, BLOCKED=3, SKIP=0
```

### modal_compute.py — PASS

```
Monte Carlo Pi: π ≈ 3.1416748 (10M samples, error 0.0026%, 3.36s)
Matrix Multiply:
  [500×500]   0.0087s, 28.59 GFLOPS
  [1000×1000] 0.0288s, 69.52 GFLOPS
Distribution Fitting:
  normal:      μ=49.99, σ=9.94, KS=0.0027 ✓
  exponential: μ=4.99,  σ=4.98, KS=0.1579 ✓
  uniform:     μ=49.99, σ=28.74, KS=0.0576 ✓
✓ All compute demos completed
```

### modal_data_analysis.py — PASS

```
Full Sales Analysis:
  Total records: 15, Revenue: ¥46,350.00, Avg order: ¥3,090.00
  🏆 Top product: Widget B (¥19,200.00)
  📈 Peak day: 2024-01-11 (¥5,250.00)
Data Quality Check:
  Rows: 15, Columns: 4, Nulls: No, Duplicates: 0
  Products: 3, Date range: 2024-01-01 ~ 2024-01-15
Product Ranking (by revenue):
  #1 Widget B  ¥19,200.00
  #2 Widget A  ¥16,650.00
  #3 Widget C  ¥10,500.00
✓ All analysis demos completed
```

## Notes

- All demos use built-in templates (`base`, `code-interpreter-v1`) — no extra deployment needed.
- When CodeInterpreter service is unavailable (HTTP 404), the SDK automatically falls back to shell execution. This is expected behavior.
- E2B-style demos manage sandboxes via `async with` for automatic lifecycle cleanup.
- Modal-style demos use the `@sandbox` decorator — sandbox creation, serialization, and cleanup are all handled transparently.
- The `e2e_capability_validation.py` "BLOCKED" results are due to GitHub anonymous rate limits and missing ports-capable templates — not SDK bugs.
- The E2B-style `comparison.py` Task 2 takes ~30s because it includes `pip install numpy` inside the sandbox, while Modal style pre-declares `packages=["numpy"]` for faster execution.
