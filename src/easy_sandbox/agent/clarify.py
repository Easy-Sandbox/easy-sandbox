"""Research-first requirement clarification for ``ebx create "<description>"``.

The natural-language create path starts from one free-form sentence.  The
clarification phase is **two phases on one native Qwen Code session**, and
both the research and the questions come from Qwen Code itself:

* **Phase R (research)** — one plain headless run (``--session-id``, no
  ``--json-schema``).  The agent is instructed to settle every *publicly
  verifiable* fact with its own native tools (``web_fetch``, shell) before
  anything is asked: whether a tool is Node.js-based, its official install
  command, common runtimes and dependencies.  ``--json-schema`` is
  deliberately absent here — verified against qwen-code 0.15.11, the
  structured-output contract ends the session on the first valid
  ``structured_output`` call, which would cut the tool loop short before
  any research happened.
* **Phase A (assessment)** — the *same* session continues (``--resume``)
  with ``--json-schema`` and returns the structured completeness verdict.
  Only user preferences, private constraints, and business decisions that
  the agent cannot infer may be marked missing; publicly verifiable facts
  may not.  Every follow-up round hands one user answer back through the
  same session, so the model keeps the original description, the research
  summary, and every Q/A pair in its own conversation memory.

Easy Sandbox never re-implements the agent loop and never replays the
transcript by hand.  It keeps only its own surface:

* the input contract — a free-form DESCRIPTION plus interactive answers;
* the one-question-per-round experience — the schema carries exactly one
  ``question`` string and the loop shows at most that one question,
  numbered ``Question 1``, ``Question 2``, … with **no total shown** (the
  internal :data:`MAX_CLARIFY_ROUNDS` cap is a safety bound, mentioned
  only when it is reached);
* the threshold gate — :data:`CLARITY_THRESHOLD` is *our* verdict
  (:attr:`ClarifyAssessment.complete`), not the model's;
* delegation answers — answers like “你自己决定” / "you decide" are detected
  by :func:`is_delegation_answer` and instruct the agent to settle the
  remaining choice itself with safe defaults instead of re-asking;
* anti-repetition — previously asked questions are embedded into every
  follow-up prompt, and an exactly-repeated question breaks the loop
  defensively (the client-side net behind the prompt-level rule);
* non-interactive behaviour — never block; fail with the missing details
  and a ready-to-use example instead;
* the thin adapter to the host CLI (prompt text, structured payload
  parsing, round budget, timeouts, graceful degradation).

Verified against qwen-code 0.15.11 (2026-09-29): ``--json-schema`` is
headless-only and its payload arrives as ``structured_result`` on the
terminal ``result`` message; sessions live per working directory; the
prompt is a positional argument (the legacy ``-p`` flag is deprecated);
built-in tools include ``web_fetch`` (there is no ``web_search`` tool
name in 0.15.11 — the agent fetches URLs, optionally via shell helpers).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from easy_sandbox.agent.qwen_code import run_qwen_code_headless
from easy_sandbox.models.errors import AICodegenError
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("agent.clarify")

__all__ = [
    "ASSESS_SESSION_TURNS",
    "CLARIFY_SCHEMA",
    "CLARITY_THRESHOLD",
    "DEFAULT_CLARIFY_TIMEOUT",
    "DEFAULT_RESEARCH_TIMEOUT",
    "MAX_CLARIFY_ROUNDS",
    "RESEARCH_SESSION_TURNS",
    "ClarifyAssessment",
    "ClarifyOutcome",
    "answer_prompt",
    "assessment_prompt",
    "evaluate",
    "is_delegation_answer",
    "new_session_id",
    "parse_assessment",
    "research_prompt",
    "run_research",
]

#: Completeness (0-1) an assessment must reach before AI generation runs.
CLARITY_THRESHOLD: float = 0.8

#: Hard cap on interactive question rounds (one question per round).  This
#: is an internal safety bound only — the UX never shows ``N/5``; the cap
#: is mentioned to the user only when it is actually reached.
MAX_CLARIFY_ROUNDS: int = 5

#: Turn budget for the research round.  Research performs real tool calls
#: (``web_fetch`` / shell), so it needs a far larger budget than the pure
#: reasoning assessment — but still bounded so a misbehaving model cannot
#: burn the whole timeout.
RESEARCH_SESSION_TURNS: int = 40

#: Turn budget for one assessment round.  An assessment is pure reasoning
#: (the structured-output session runs no further research), so a small
#: budget is enough and keeps a misbehaving model from burning the whole
#: timeout.
ASSESS_SESSION_TURNS: int = 3

#: Wall-clock budget for the research round (seconds).  Larger than the
#: assessment budget: web fetches and shell probes take real time.
DEFAULT_RESEARCH_TIMEOUT: float = 240.0

#: Wall-clock budget for one assessment round (seconds).  Much smaller
#: than code generation: nothing is built, nothing is written.
DEFAULT_CLARIFY_TIMEOUT: float = 180.0

#: Answer fragments that mean the user delegated the decision back to the
#: agent (“你自己决定” / “采用默认” / "you decide" / "use the default").
#: Matching is substring-based on the normalised answer; the answer text
#: is *always* forwarded to the session verbatim, so a false positive can
#: only ever add “don't re-ask this topic” pressure — never lose the
#: user's own words.
_DELEGATION_MARKERS: tuple[str, ...] = (
    # Chinese delegation / default-acceptance phrasing.
    "你自己",
    "你决定",
    "你定",
    "你选",
    "你挑",
    "你看着办",
    "你来定",
    "你来选",
    "由你决定",
    "由你来",
    "自行决定",
    "自己决定",
    "自己检索",
    "自己查",
    "自己选",
    "随便你",
    "随便",
    "都可以",
    "无所谓",
    "没要求",
    "没有要求",
    "没偏好",
    "不确定",
    "不知道",
    "采用默认",
    "用默认",
    "合理默认",
    "默认即可",
    "默认就行",
    "默认就好",
    # English equivalents.
    "you decide",
    "you choose",
    "you pick",
    "up to you",
    "your choice",
    "your call",
    "as you see fit",
    "whatever you",
    "anything is fine",
    "anything works",
    "any is fine",
    "any works",
    "no preference",
    "don't care",
    "do not care",
    "no requirement",
    "no requirements",
    "not sure",
    "don't know",
    "do not know",
    "use default",
    "use the default",
    "defaults are fine",
    "sensible default",
    "reasonable default",
    "default is fine",
    "decide yourself",
    "figure it out",
    "search yourself",
    "research yourself",
)

#: JSON Schema handed to ``qwen --json-schema``.  ``question`` is a single
#: string (never a list) which is what makes the one-question-per-round
#: experience structural rather than a prompt request.  The field
#: descriptions carry the research-first contract: public facts must never
#: become a question, and answered topics must never repeat.
CLARIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["completeness", "question", "missing", "example"],
    "properties": {
        "completeness": {
            "type": "number",
            "description": (
                "How complete the information is for generating a runnable "
                "template, from 0 (nothing useful) to 1 (everything needed). "
                "Publicly verifiable facts that you can research or infer "
                "yourself count as complete; only user preferences, private "
                "constraints, and business decisions you cannot infer may "
                "count as missing. 0.8 or above means generation can proceed."
            ),
        },
        "question": {
            "type": "string",
            "description": (
                "Exactly ONE most important follow-up question, in the same "
                "language as the user's description. Only about information "
                "you cannot publicly verify or infer yourself (required "
                "versions, region, resource size, private dependencies, "
                "entry/port choices) — never about public facts such as the "
                "tool stack, the official install method, or common "
                "dependencies, and never repeating an already-asked or "
                "already-answered topic. Empty string when no question is "
                "needed."
            ),
        },
        "missing": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Short labels of the information still missing — only user "
                "preferences, private constraints, or business decisions "
                '(e.g. ["entry command choice", "resource size"]). Public '
                "facts must not appear here."
            ),
        },
        "example": {
            "type": "string",
            "description": (
                "A ready-to-use example description, in the same language as "
                "the user's input, that fills in the missing details."
            ),
        },
    },
}

_RESEARCH_PROMPT_TEMPLATE = """\
你是 Easy Sandbox 的模板需求分析器。用户会用一句自然语言描述想创建的沙箱，
随后将据此生成 Dockerfile 和 template.yaml。

用户描述：
{description}

请先用你可用的工具（如 web_fetch、shell）检索这个描述涉及的**可公开查证的
事实**，至少覆盖：
- 描述中提到的工具/框架属于什么技术栈（例如是否 Node.js / Python 工具）
- 官方推荐的安装方式与常用版本
- 常见运行时与依赖

这些是公共事实，后续一律不得向用户提问；检索不到时直接采用安全合理的默认值，
并在总结中逐条明确记录这些假设。

检索完成后，输出两部分内容（使用与用户描述相同的语言，不要输出推理过程）：
1. 已确认的公开事实清单（含采用的默认值与假设）。
2. 仅剩的、无法自行查证或推断的信息清单——只允许是用户偏好、私有约束或
   业务决策（例如必须使用的版本、区域、资源规格、私有依赖、入口和端口选择）。

不要向用户提问，不要生成任何文件。"""

_ASSESSMENT_PROMPT_TEMPLATE = """\
你是 Easy Sandbox 的模板需求分析器。以下是用户想创建的沙箱描述；若本会话
此前已完成事实检索，请直接采用其结论（包括其中记录的默认值与假设）。

用户描述：
{description}

请评估生成一个可运行模板（Dockerfile + template.yaml）所需信息的完整度。
评估维度：runtime（运行时/基础镜像）、dependencies（预装依赖）、
entry command（入口命令）、ports（端口）、resources（CPU/内存）、data（数据）。

判定规则：
1. 可公开查证的事实（工具链类型、官方安装方式、常见运行时与依赖）不得视为
   缺失，也不得作为问题提出——这些应由你自己检索确认并采用安全合理默认。
2. 只把无法自行查证或推断的用户偏好、私有约束、业务决策视为缺失（如必须
   使用的版本、区域、资源规格、私有依赖、入口和端口选择）。
3. 用户以“你自己决定/采用默认”等授权语义回答过的维度视为已解决（采用安全
   合理默认），不得就同一主题再次提问。
4. 不得重复已问过的问题或已回答的主题。

输出要求：
1. completeness：0 到 1 的完整度（按上述规则覆盖越多越高；0.8 及以上视为足够）。
2. question：若 completeness < 0.8，给出唯一一个最关键的问题（只问一个，
   聚焦能显著提升完整度的缺失信息，使用与用户描述相同的语言）；若已足够，
   输出空字符串。
3. missing：缺失维度的简短标签列表（只含规则 2 允许的项）。
4. example：一句补全缺失信息后的示例描述（与用户描述相同语言）。
不要生成文件，不要提出多个问题。"""

_FOLLOWUP_PROMPT_TEMPLATE = """\
用户对澄清问题的回答：
{answer}
{delegation_clause}
{asked_clause}
请结合原始描述、此前检索确认的事实与全部问答记录重新评估完整度，并按同样
的结构化格式输出（仅一个最关键的问题；若已足够，question 为空字符串）。"""

_DELEGATION_CLAUSE = """\
该回答包含授权语义（用户委托你自行决定）：请对被授权的部分自行检索确认或
采用安全合理默认，视为相应维度已解决，不得就同一主题再次提问。"""

_ASKED_CLAUSE_TEMPLATE = """\
已问过的问题（不得重复这些主题）：
{asked}"""


@dataclass(frozen=True)
class ClarifyAssessment:
    """One structured completeness assessment returned by Qwen Code."""

    completeness: float
    """Model-estimated completeness in 0..1 (clamped by :func:`parse_assessment`)."""

    question: str | None
    """The single most important follow-up question, or ``None``."""

    missing: tuple[str, ...] = ()
    """Short labels of the template-relevant details still missing."""

    example: str | None = None
    """Ready-to-use example description suggested by the model."""

    @property
    def complete(self) -> bool:
        """Whether the assessment clears the Easy Sandbox threshold gate."""
        return self.completeness >= CLARITY_THRESHOLD

    def missing_summary(self) -> str:
        """Comma-separated missing labels (``"unknown"`` when empty)."""
        return ", ".join(self.missing) if self.missing else "unknown"


@dataclass
class ClarifyOutcome:
    """Result of the clarification phase, consumed by the create command.

    ``session_id`` is non-empty only once the first assessment round has
    succeeded; the generation step then resumes that very session so the
    model keeps the full clarification context in its own memory.
    """

    session_id: str = ""
    assessment: ClarifyAssessment | None = None
    rounds: int = 0
    """Number of interactive question rounds actually asked."""

    degraded: bool = False
    """``True`` when the assessment was unavailable (never blocks)."""

    skipped: bool = False
    """``True`` when ``--yes`` skipped clarification entirely."""


def new_session_id() -> str:
    """Fresh UUID for the native Qwen Code session all rounds share."""
    return str(uuid.uuid4())


def is_delegation_answer(answer: str) -> bool:
    """Whether *answer* delegates the decision back to the agent.

    Matches curated Chinese/English fragments such as “你自己决定”, “采用
    默认”, "you decide", "up to you", "use the default".  The answer text
    is always forwarded to the session verbatim regardless — a positive
    match only strengthens the “settle it yourself, don't re-ask”
    instruction in the follow-up prompt.
    """
    normalized = answer.strip().lower()
    return any(marker in normalized for marker in _DELEGATION_MARKERS)


def research_prompt(description: str) -> str:
    """Phase-R prompt: settle the public facts before anything is asked."""
    return _RESEARCH_PROMPT_TEMPLATE.format(description=description.strip())


def assessment_prompt(description: str) -> str:
    """Phase-A prompt: structured completeness verdict (first round)."""
    return _ASSESSMENT_PROMPT_TEMPLATE.format(description=description.strip())


def answer_prompt(answer: str, asked: Sequence[str] = ()) -> str:
    """Follow-up prompt: hand one user answer back to the same session.

    *asked* is the list of questions already shown to the user; it is
    embedded verbatim so the model cannot repeat a topic.  When the answer
    carries delegation semantics (:func:`is_delegation_answer`), an
    explicit clause instructs the agent to settle the delegated choice
    itself with safe defaults instead of re-asking.
    """
    delegation_clause = _DELEGATION_CLAUSE if is_delegation_answer(answer) else ""
    asked_clause = (
        _ASKED_CLAUSE_TEMPLATE.format(asked="\n".join(f"- {q}" for q in asked)) if asked else ""
    )
    return _FOLLOWUP_PROMPT_TEMPLATE.format(
        answer=answer.strip(),
        delegation_clause=delegation_clause,
        asked_clause=asked_clause,
    )


def parse_assessment(payload: Any) -> ClarifyAssessment | None:
    """Normalise a ``structured_result`` payload; ``None`` when unusable.

    Tolerates a 0-100 completeness scale (divided by 100) and clamps the
    value into 0..1, so a chatty model can never corrupt the threshold
    gate.  A payload without a numeric ``completeness`` is unusable.
    """
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("completeness")
    try:
        completeness = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if completeness > 1.0:
        completeness /= 100.0
    completeness = min(max(completeness, 0.0), 1.0)

    question = payload.get("question")
    question_text = question.strip() if isinstance(question, str) else ""
    example = payload.get("example")
    example_text = example.strip() if isinstance(example, str) else ""

    missing_raw = payload.get("missing")
    missing: tuple[str, ...] = ()
    if isinstance(missing_raw, list):
        missing = tuple(
            text for item in missing_raw if isinstance(item, str) and (text := item.strip())
        )

    return ClarifyAssessment(
        completeness=completeness,
        question=question_text or None,
        missing=missing,
        example=example_text or None,
    )


def run_research(
    prompt: str,
    *,
    binary: Path | str,
    env: Mapping[str, str] | None,
    cwd: Path | str,
    session_id: str,
    timeout: float = DEFAULT_RESEARCH_TIMEOUT,
) -> bool:
    """Run the phase-R research round through Qwen Code.

    A plain headless run (no ``--json-schema``) on the native session
    *session_id* so the agent can use its own tools to settle public
    facts.  Never raises: a timeout, a crash, or an error result returns
    ``False`` and the caller continues straight to the structured
    assessment (the session — if it was created at all — simply carries
    whatever partial context exists, and the assessment prompt's
    safe-default rule covers the rest).
    """
    try:
        result = run_qwen_code_headless(
            prompt,
            binary=binary,
            env=env,
            cwd=cwd,
            timeout=timeout,
            max_session_turns=RESEARCH_SESSION_TURNS,
            session_id=session_id,
        )
    except AICodegenError as exc:
        logger.debug("Clarification research unavailable: %s", exc)
        return False
    if result.is_error:
        logger.debug(
            "Clarification research failed: exit_code=%s stderr=%s",
            result.exit_code,
            (result.raw_stderr or "").strip()[:200],
        )
        return False
    return True


def evaluate(
    prompt: str,
    *,
    binary: Path | str,
    env: Mapping[str, str] | None,
    cwd: Path | str,
    session_id: str | None = None,
    resume: str | None = None,
    timeout: float = DEFAULT_CLARIFY_TIMEOUT,
) -> ClarifyAssessment | None:
    """Run one structured assessment round through Qwen Code.

    The caller sets exactly one of *session_id* (the session may not exist
    yet — pin/create it) or *resume* (the research round or a previous
    assessment already created it); the session itself carries the
    description, the research summary, and every previous answer.

    Never raises for a plain assessment failure: a timeout, a crash, or a
    payload that fails to parse returns ``None`` so the create command can
    degrade to direct generation instead of blocking the user.
    """
    try:
        result = run_qwen_code_headless(
            prompt,
            binary=binary,
            env=env,
            cwd=cwd,
            timeout=timeout,
            max_session_turns=ASSESS_SESSION_TURNS,
            session_id=session_id,
            resume=resume,
            json_schema=CLARIFY_SCHEMA,
        )
    except AICodegenError as exc:
        logger.debug("Clarification assessment unavailable: %s", exc)
        return None
    if result.is_error:
        logger.debug(
            "Clarification assessment failed: exit_code=%s stderr=%s",
            result.exit_code,
            (result.raw_stderr or "").strip()[:200],
        )
        return None
    return parse_assessment(result.structured)
