# Decision: Research-first two-phase clarification (plain research round → structured assessment) on one native session

Status: implemented
Implemented: 2026-09-29
Related: [2026-09-29-single-question-clarification.md](../feature/2026-09-29-single-question-clarification.md) (extends), [2026-09-29-qwen-session-turns-param-unification.md](../feature/2026-09-29-qwen-session-turns-param-unification.md), [2026-09-29-pluggable-coding-agent-backend.md](2026-09-29-pluggable-coding-agent-backend.md), [2026-09-29-byo-agent-integration-contract.md](2026-09-29-byo-agent-integration-contract.md)

## Problem

The single-question clarification loop asked the user first and asked too
much.  For a description like "一个 sandbox 里面运行 Serverless Devs CLI" the
old flow could ask whether the tool is Node.js-based, what its official
install method is, or which common dependencies it needs — all *publicly
verifiable facts* the agent could have researched itself.  The user was being
used as a search engine for information the tool stack already knows.

Two structural constraints made "just let the agent research" non-trivial:

1. **`--json-schema` ends the session early.**  Verified against the local
   qwen-code 0.15.11 `--help` (not from memory): `--json-schema` is
   headless-only and "Registers a synthetic `structured_output` tool; the
   session ends on the first valid call".  Running research *inside* the
   structured round would cut the tool loop before any research happened.
2. **The research must use the agent's own tools, not a hand-rolled
   searcher.**  Easy Sandbox must not re-implement a web-search client or an
   agent loop; the task forbids growing one.

Separately, the interaction contract had three UX gaps: the prompt showed an
internal cap (`Q1/5`) that meant nothing to users; a model could repeat an
already-answered question; and answers like "你自己决定" / "you decide"
(delegating the choice back to the agent) were treated as opaque strings
instead of the instruction they are.

## Verified facts (qwen-code 0.15.11, 2026-09-29)

Re-verified on this machine via `~/.ebx/bin/qwen --help` plus a source-level
read of the shipped `cli.js` (no credentials were read; live model calls were
not available):

- The prompt is a **positional argument**; `-p, --prompt` is marked
  **deprecated** ("Use the positional prompt instead").  The external BYO
  template targets 0.23.0, whose `--help` agrees — no version branching
  needed.
- `--json-schema` is headless-only; the first valid `structured_output` call
  ends the session (the payload arrives as `structured_result` on the
  terminal `result` message).
- `--session-id <uuid>` / `--resume <uuid>` are native (mutually exclusive;
  sessions are stored per working directory — clarification and generation
  therefore share one `cwd`).
- The built-in tool enum in 0.15.11 contains `web_fetch` (there is **no**
  `web_search` tool name) and `run_shell_command`; the research prompt names
  the agent's available tools generically ("如 web_fetch、shell").
- `--max-session-turns` exists (exit 53 when exceeded) and bounds a runaway
  model; research needs a far larger budget than pure reasoning.

## Decision

### Two phases on ONE native session

- **Phase R (research)** — `clarify.run_research(prompt, *, binary, env, cwd,
  session_id)`: one *plain* headless run (`--session-id`, **no**
  `--json-schema`, `RESEARCH_SESSION_TURNS = 40`, `DEFAULT_RESEARCH_TIMEOUT =
  240s`) whose prompt instructs the agent to settle every publicly
  verifiable fact with its own tools — tool stack, official install method,
  common runtimes and dependencies — and to record safe defaults for anything
  unreachable.  Never raises; a timeout/crash/error result returns `False`.
- **Phase A (assessment)** — the *same* session continues (`--resume`) with
  `--json-schema` (`CLARIFY_SCHEMA`, `ASSESS_SESSION_TURNS = 3`,
  `DEFAULT_CLARIFY_TIMEOUT = 180s`).  Because the schema would have ended
  the session on the first valid call, it is deliberately absent from Phase R
  so the tool loop stays free.

Generation later resumes the same session, so the model keeps the
description, the research summary, and every Q/A pair in its own memory —
Easy Sandbox never replays the transcript by hand.

### What counts as a question

Publicly verifiable facts are *complete by definition*.  The rule lives in
three reinforcing places: the schema field descriptions (`question` "never
about public facts such as the tool stack, the official install method, or
common dependencies"; `missing` "Public facts must not appear here"), the
assessment prompt's four judgement rules, and the research prompt's "don't
ask the user" clause.  Only user preferences, private constraints, and
business decisions the agent cannot infer may count as missing.

### UX contract

- Questions are numbered `Question 1`, `Question 2`, … with **no total
  shown**; `MAX_CLARIFY_ROUNDS = 5` stays an internal safety bound, mentioned
  only when actually reached ("Reached the 5-question safety limit").
- **Anti-repetition**, two layers: every follow-up prompt embeds the
  already-asked questions (`answer_prompt(answer, asked=...)`), and the CLI
  breaks the loop defensively when a question repeats exactly ("The agent
  repeated an already-answered question").
- **Delegation answers** — `clarify.is_delegation_answer` matches curated
  Chinese/English fragments ("你自己决定", "采用默认", "you decide", "use the
  default", …); a match adds an explicit clause instructing the agent to
  settle the delegated choice itself with safe defaults and never re-ask the
  topic.  The answer text is always forwarded verbatim, so a false positive
  can only add "don't re-ask" pressure, never lose the user's words.
- **Phase status is stderr-only**: `_phase_status(out, message)` in
  `sandbox.py` shows a Rich spinner on stderr in interactive TTY mode and one
  machine-readable progress line (`... Assessing description` /
  `... Re-assessing description` / `... Generating template`) otherwise;
  quiet/CI stay silent.  stdout is never touched and the model's research
  output or chain of thought is never echoed.
- **Failure never gates**: a failed research round only warns ("could not
  research the public facts … safe defaults apply") and the assessment pins
  the session itself (`session_id=` instead of `resume=`); an unavailable
  assessment still degrades to direct generation.  Non-interactive callers
  below the threshold keep failing fast with E2008 (missing details +
  example), never blocking.

### Protocol change

`CodingAgentBackend` gains `research(prompt, *, workdir, binary, env,
session_id) -> bool` (delegating to `clarify.run_research`); the orchestration
in `_clarify_requirements` runs research → assess on round 1 and assess-only
(`--resume`) afterwards.  The threshold gate (`CLARITY_THRESHOLD = 0.8`)
remains Easy Sandbox's verdict, not the model's.

### Positional prompt convergence

Both runtime call sites now use the positional prompt, per the 0.15.11 /
0.23.0 `--help` agreement:

- host side: `qwen_code._build_headless_command` → `[binary, prompt,
  "--output-format", "json", "--yolo", ...]` (no `-p`);
- sandbox side: `deploy._build_qwen_command` → `qwen "<prompt>" --yolo
  --output-format json --max-session-turns <n>`.

The external qwen-code BYO template (`qwen {prompt}`) already matches; no
version branching is required.

## Test Strategy

- `tests/test_agent/test_clarify.py` (rewritten): schema forbids public-fact
  questions; research/assessment prompts carry the public-fact, delegation,
  and anti-repetition rules; `is_delegation_answer` positive/negative
  matrices (Chinese + English); `run_research` runs a plain session (no
  `json_schema`, `RESEARCH_SESSION_TURNS`, research timeout) and degrades to
  `False` on failure.
- `tests/test_agent/test_qwen_code.py` /
  `tests/test_api/test_deploy.py`: the prompt travels positionally and the
  deprecated `-p`/`--prompt` never reappears.
- `tests/test_cli/test_create_nl.py` (updated + new classes):
  `TestResearchFirstFlow` (research→assess wiring on one session, research
  failure falls back to `session_id=`, Serverless Devs acceptance case —
  public facts researched, no question, no "Node.js" in output),
  `TestDelegationAnswers`, `TestAntiRepetition`, `TestPhaseStatusChannels`
  (spinner-mode vs progress-line vs quiet unit checks; end-to-end stderr-only
  phase lines with clean stdout; JSON mode keeps stdout machine-readable).
- Evidence golden regenerated: `create-nl-*` cases now show the stderr phase
  lines with a clean stdout channel (capture uses `result.stdout`, not the
  interleaved `result.output`, on Click ≥ 8.2).

## Acceptance criteria

- [x] research phase runs on the agent's own native session before any
      question, with no `--json-schema` (0.15.11-verified constraint)
- [x] public facts are settled by research and never asked (Serverless Devs
      acceptance case pinned by a CLI test)
- [x] `Question N` numbering with no total shown; the 5-round cap surfaces
      only when reached
- [x] delegation answers instruct the agent instead of re-asking; asked
      topics never repeat (prompt rule + defensive loop break)
- [x] assessing / re-assessing / generating status renders on stderr only
      (spinner or one progress line); stdout stays machine-readable in every
      mode; JSON / quiet / CI never block
- [x] research failure warns without gating; assessment unavailability still
      degrades to direct generation
- [x] positional prompt at both runtime call sites; `-p` gone from host and
      sandbox commands (0.15.11 and 0.23.0 agree)
- [x] tutorials, references, error codes, and design docs updated in both
      languages; evidence golden regenerated

## Files changed

- `src/easy_sandbox/agent/clarify.py` — two-phase rewrite: `run_research`,
  `research_prompt`, delegation detection, anti-repetition prompts, new
  turn/timeout budgets, schema descriptions
- `src/easy_sandbox/agent/coding_agent.py` — `research()` on the protocol and
  `QwenCodeBackend`
- `src/easy_sandbox/cli/commands/sandbox.py` — research-first
  `_clarify_requirements`, `Question N` prompts, asked-tracking, repeated /
  safety-limit wording, `_phase_status` spinner/progress helper, generation
  spinner, `create --help` text
- `src/easy_sandbox/agent/qwen_code.py` / `src/easy_sandbox/api/deploy.py` —
  positional prompt
- `scripts/evidence_cases.py` / `scripts/capture_cli_evidence.py` /
  `tests/test_cli_evidence/test_evidence_snapshots.py` — research mock,
  stdout/stderr channel split for golden capture
- `tests/test_agent/test_clarify.py`, `tests/test_agent/test_qwen_code.py`,
  `tests/test_api/test_deploy.py`, `tests/test_cli/test_create_nl.py`
- `docs/{en,zh}/guide/cli-tutorial.md`, `docs/{en,zh}/reference/cli-reference.md`,
  `docs/{en,zh}/reference/error-codes.md`, `docs/{en,zh}/design/cli-design.md`
- `.agents/evidence/cli/*.md` + `tests/test_cli_evidence/golden/*.txt`
  (regenerated)

## Consequences

- The user is only ever asked about things only they can answer; everything
  publicly verifiable is the agent's job (offline → recorded safe defaults).
- One extra plain headless run per interactive create (bounded: 40 turns /
  240s) buys the structured round real facts to assess against.
- `--json-schema` stays confined to rounds where an immediate verdict is the
  point; anything that needs the tool loop must run schema-free first — this
  is now a project-wide rule for the Qwen headless dialect.
- Backends that cannot research return `False` / leave `assess` returning
  `None`; the flow degrades exactly as before, so the protocol stays
  optional-friendly for future backends.
