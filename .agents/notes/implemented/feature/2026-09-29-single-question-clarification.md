# Decision: Single-question clarification loop for the `ebx create` NL path

Status: implemented
Proposed: 2026-09-29
Implemented: 2026-09-29

## Problem

`ebx create "<description>"` feeds one free-form sentence straight into the
coding agent.  A sentence that never mentions the runtime, its dependencies,
the entry command, exposed ports, resource expectations, or the data the
sandbox works on produces a mediocre template: the agent has to guess, and the
user only discovers the guess after a build + deploy + create cycle has been
paid for.

Asking for everything at once is not acceptable either: a battery of questions
is poor UX and the task explicitly forbids more than one question per round.
Blocking non-interactive callers until the description is "complete" is worse —
CI has nobody to answer, so it must fail fast with actionable guidance instead
of hanging.

## Decision

Assess the description *before* generation and complete it through a
**single-question clarification loop**:

- **The assessment comes from the coding agent itself.**  Every round is one
  headless Qwen Code run with `--json-schema` (`CLARIFY_SCHEMA`): a validated
  structured payload carrying `completeness` (0..1), exactly ONE `question`
  string, the `missing` labels, and a ready-to-use `example`.  Easy Sandbox
  never re-implements the agent loop.
- **The one-question rule is structural, not prompt-level** — the schema has a
  single `question` string, so a chatty model cannot ask a battery of
  questions; the CLI loop shows at most that one question per round.
- **Native session continuity.**  Round 1 creates a Qwen Code session
  (`--session-id <uuid>`); every following round resumes the same session
  (`--resume`) with the user's answer (`answer_prompt`).  The model keeps the
  original description and the whole Q/A history in its own memory; Easy
  Sandbox never replays the transcript by hand.
- **The threshold is our verdict.**  `CLARITY_THRESHOLD = 0.8`
  (`ClarifyAssessment.complete`) gates generation; payload values are clamped
  into 0..1 (a 0-100 scale is tolerated), so the model cannot corrupt the gate.
- **Interactive behaviour (TTY, no `--yes`).**  One question per round, at most
  `MAX_CLARIFY_ROUNDS = 5`; each answer triggers a fresh assessment against the
  same session.  Reaching the threshold prints the final completeness and moves
  to generation; an empty answer cancels with E2008; EOF aborts with E2008;
  running out of questions (or the model returning no question) warns with the
  missing labels and continues to generation rather than looping forever.
- **Non-interactive behaviour (non-TTY / `--json` / CI, no `--yes`).**  Assessed
  exactly once and never blocked: below the threshold raises
  `DescriptionClarificationError` (E2008) carrying the missing labels, a
  ready-to-use example description, and actionable alternatives (`--yes`, or
  `ebx create --template <name>`).
- **`--yes` is the fast path.**  It skips clarification entirely (no assessment
  round) and generates from the current description.
- **Graceful degradation.**  When the assessment is unavailable (timeout,
  crash, unparseable payload) the flow warns and continues straight to
  generation — clarification must never become a new way for `create` to fail.
- **Generation resumes the session.**  Clarification and generation share one
  workspace (`prepare_workdir`) because Qwen sessions are keyed by the working
  directory; `generate_template_files(..., resume_session=...)` then continues
  the very same session, so the model generates with the full clarification
  context in its memory.

## API Design

New module `src/easy_sandbox/agent/clarify.py` (the thin adapter around the
agent's structured rounds):

```python
CLARITY_THRESHOLD: float = 0.8            # our gate, not the model's
MAX_CLARIFY_ROUNDS: int = 5              # one question per round
ASSESS_SESSION_TURNS: int = 3            # assessment = pure reasoning
DEFAULT_CLARIFY_TIMEOUT: float = 180.0

CLARIFY_SCHEMA: dict[str, Any]           # completeness / question / missing / example

@dataclass(frozen=True)
class ClarifyAssessment:
    completeness: float                  # clamped into 0..1
    question: str | None                 # at most ONE question
    missing: tuple[str, ...] = ()
    example: str | None = None
    @property
    def complete(self) -> bool: ...
    def missing_summary(self) -> str: ...

@dataclass
class ClarifyOutcome:
    session_id: str = ""                 # non-empty -> generation resumes it
    assessment: ClarifyAssessment | None = None
    rounds: int = 0
    degraded: bool = False               # assessment unavailable (never blocks)
    skipped: bool = False                # --yes fast path

def new_session_id() -> str
def assessment_prompt(description: str) -> str
def answer_prompt(answer: str) -> str
def parse_assessment(payload: Any) -> ClarifyAssessment | None
def evaluate(prompt, *, binary, env, cwd, session_id=None, resume=None,
             timeout=DEFAULT_CLARIFY_TIMEOUT) -> ClarifyAssessment | None
```

`CodingAgentBackend` (see the pluggable-backend note) grows one method so the
CLI orchestrates through the backend seam and never imports the Qwen dialect:

```python
def assess(self, prompt, *, workdir, binary, env,
           session_id=None, resume=None) -> ClarifyAssessment | None: ...
```

`_generate_and_deploy_template` (`cli/commands/sandbox.py`) runs
`prepare_workdir` → `_clarify_requirements` → `generate(..., resume_session=...)`;
a non-empty `outcome.session_id` is the session the generator resumes.

## Alternatives considered

- **Deterministic facet scoring inside Easy Sandbox** (keyword/regex coverage of
  the six template facets, fixed weights, fixed threshold) — no model needed and
  fully offline, but it cannot judge semantics ("用我的模型跑推理服务" covers
  runtime + entry command and nothing else), needs continuous weight tuning,
  and duplicates knowledge the coding agent already has.  Rejected.
- **Ask all missing facets in one round** — the task forbids it; a wall of
  questions is exactly the UX this feature exists to avoid.  Rejected.
- **Block non-interactive callers until the description is complete** — CI
  hangs; `--yes` becomes the only usable non-interactive path.  Rejected in
  favour of fail-fast E2008 with missing details + example.
- **Trust the model's own "ready" flag without a threshold gate** — the gate is
  a product decision (80%), not the model's; a chatty model must not be able to
  lower it.  Rejected; the payload completeness is clamped and compared against
  `CLARITY_THRESHOLD` by Easy Sandbox.
- **Replay the Q/A transcript by hand into every round** — duplicates session
  state, risks drift, and grows the prompt linearly.  Rejected in favour of the
  agent's native session (`--session-id` / `--resume`).

## Dependencies

- Qwen Code CLI with structured-output + native-session headless support.
  Verified against qwen-code 0.15.11 (2026-09-29): `--json-schema` is
  headless-only, ends the session on the first valid `structured_output` call,
  and its payload arrives as `structured_result` on the terminal `result`
  message; sessions live per working directory.
- Extends the existing NL-create Qwen Code integration (E2005/E2006/E2007);
  adds `DescriptionClarificationError` (E2008) as a `SandboxCreationError`.
- No new third-party Python dependencies.

## Test Strategy

All tests are offline; the `qwen` binary and the network are fully mocked.

- `tests/test_agent/test_clarify.py` — schema shape (single `question` string,
  closed object, JSON-serialisable), `parse_assessment` normalisation (100-scale
  tolerance, clamping, blank/`None` cleanup), the threshold verdict, the
  `evaluate` contract (`--session-id` / `--resume` / `--json-schema` /
  turn budget) and its degrade-to-`None` failure mode.
- `tests/test_cli/test_create_nl.py` — the CLI loop: multi-round one-question
  prompts, the 80% gate stopping the loop, empty-answer cancel, EOF abort,
  non-TTY E2008 (missing details + example), `--json` never prompting,
  `--yes` skipping clarification, and assessment-unavailable degradation.
- `tests/test_agent/test_codegen.py` — generation resumes the clarification
  session (`resume_session` reaching the Qwen invocation).
- Evidence snapshots via `EBX_UPDATE_EVIDENCE=1 pytest tests/test_cli_evidence/`
  — `create-nl-clarify-required` (E2008), `create-nl-confirm-required`
  (complete assessment → confirmation gate), `create-nl-python` /
  `create-nl-nodejs` (`--yes` fast path).

## Acceptance criteria

- [x] The description is assessed for completeness before generation
- [x] Below the threshold, exactly one question is asked per round
- [x] The original description plus all Q/A pairs feed every re-assessment
      (native session continuity)
- [x] Generation runs only after the assessment reaches 80% (unless `--yes`,
      degradation, or questions exhausted — each with an explicit warning)
- [x] Non-TTY / CI never blocks: E2008 with missing details and a ready-to-use
      example
- [x] `--yes` remains the fast non-interactive path (skips clarification)
- [x] Explicit `--template` is untouched (never enters the AI path)
- [x] An unavailable assessment degrades to direct generation instead of failing

## Implementation

- `ClarifyOutcome.session_id` carries the native session from clarification to
  generation; both phases share the workspace created by `prepare_workdir`.
- The interactive loop prints its progress through the diagnostic channel
  (`out.info` / `out.warning`) so `--json` output stays machine-parseable.
- E2008 is documented in `docs/{zh,en}/reference/error-codes.md`; the create
  flow is documented in `docs/{zh,en}/design/cli-design.md`,
  `docs/{zh,en}/reference/cli-reference.md` and `docs/{zh,en}/guide/cli-tutorial.md`.
- CLI evidence regenerated (`scripts/capture_cli_evidence.py`,
  `.agents/evidence/cli/create.md`); goldens refreshed with
  `EBX_UPDATE_EVIDENCE=1 pytest tests/test_cli_evidence/`.

## Evidence

- `tests/test_cli_evidence/golden/create-nl-clarify-required.txt` — the
  non-TTY incomplete-description contract (E2008 + missing + example).
- `tests/test_cli_evidence/golden/create-nl-confirm-required.txt` — a complete
  description proceeds straight to the confirmation gate.
- `tests/test_cli_evidence/golden/create-nl-python.txt` /
  `create-nl-nodejs.txt` — the `--yes` fast path.
- `pytest tests/test_cli/ tests/test_agent/ tests/test_cli_evidence/` — all
  offline, green (84 evidence snapshots; 76 tests across the three
  clarification-related suites).
- `.agents/evidence/cli/create.md` regenerated from the same registry.

## Files changed

- `src/easy_sandbox/agent/clarify.py` (new)
- `src/easy_sandbox/agent/coding_agent.py` (backend seam: `assess`,
  `prepare_workdir`, `generate(resume_session=...)`)
- `src/easy_sandbox/agent/qwen_code.py` (`--session-id` / `--resume` /
  `--json-schema`, `structured_result` parsing)
- `src/easy_sandbox/agent/codegen.py` (`prepare_workdir`,
  `resume_session` pass-through)
- `src/easy_sandbox/cli/commands/sandbox.py` (`_clarify_requirements`)
- `src/easy_sandbox/models/errors.py` (E2008 `DescriptionClarificationError`)
- `tests/test_agent/test_clarify.py`, `tests/test_agent/test_codegen.py`,
  `tests/test_cli/test_create_nl.py`
- `scripts/evidence_cases.py`, `tests/test_cli_evidence/golden/`,
  `.agents/evidence/cli/create.md`
- `docs/{zh,en}/design/cli-design.md`, `docs/{zh,en}/reference/cli-reference.md`,
  `docs/{zh,en}/reference/error-codes.md`, `docs/{zh,en}/guide/cli-tutorial.md`
