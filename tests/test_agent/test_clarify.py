"""Unit tests for the research-first requirement clarification adapter.

The research, the evaluation, and the questions themselves are produced by
Qwen Code's native session (a plain ``--session-id`` research round, then
``--json-schema`` assessment rounds on ``--resume``); these tests pin only
the thin Easy Sandbox adapter around it:

* the research-first contract — public facts must be settled by the
  agent's own tools before anything is asked (the research prompt and the
  schema carry that rule, and the research run must NOT use
  ``--json-schema`` because the structured-output contract would end the
  tool loop early);
* delegation answers (“你自己决定” / "you decide") never re-ask;
* anti-repetition — asked questions are embedded in every follow-up
  prompt;
* the structured payload parsing and the threshold verdict (our gate);
* the ``evaluate`` / ``run_research`` call contracts (native session
  flags, turn budgets, structured output) and their degrade-to-``None`` /
  ``False`` failure modes.

No test performs real network access or executes the real CLI.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from easy_sandbox.agent import clarify
from easy_sandbox.agent.clarify import (
    ASSESS_SESSION_TURNS,
    CLARIFY_SCHEMA,
    CLARITY_THRESHOLD,
    DEFAULT_CLARIFY_TIMEOUT,
    DEFAULT_RESEARCH_TIMEOUT,
    MAX_CLARIFY_ROUNDS,
    RESEARCH_SESSION_TURNS,
    ClarifyAssessment,
    answer_prompt,
    assessment_prompt,
    is_delegation_answer,
    new_session_id,
    parse_assessment,
    research_prompt,
)
from easy_sandbox.agent.qwen_code import QwenCodeRunResult
from easy_sandbox.models.errors import AICodegenError

_SESSION = "6f0f8e9a-1b2c-4d5e-8f90-123456789abc"

_PAYLOAD: dict[str, Any] = {
    "completeness": 0.9,
    "question": "",
    "missing": [],
    "example": "Python 3.12 with pandas, port 8888",
}


class TestConstants:
    def test_threshold_is_eighty_percent(self) -> None:
        assert CLARITY_THRESHOLD == 0.8

    def test_round_cap_is_bounded(self) -> None:
        assert 1 <= MAX_CLARIFY_ROUNDS <= 10

    def test_assessment_budget_is_small(self) -> None:
        """An assessment is pure reasoning: small turn budget, small timeout."""
        assert ASSESS_SESSION_TURNS < 10
        assert DEFAULT_CLARIFY_TIMEOUT < 600.0

    def test_research_budget_is_larger_than_assessment(self) -> None:
        """Research performs real tool calls: larger turn budget and timeout."""
        assert RESEARCH_SESSION_TURNS > ASSESS_SESSION_TURNS
        assert DEFAULT_RESEARCH_TIMEOUT > DEFAULT_CLARIFY_TIMEOUT
        assert RESEARCH_SESSION_TURNS >= 20


class TestSchema:
    def test_single_question_is_structural(self) -> None:
        """``question`` is one string — a model cannot ask a battery of questions."""
        assert CLARIFY_SCHEMA["properties"]["question"]["type"] == "string"

    def test_required_fields_and_closed_object(self) -> None:
        assert CLARIFY_SCHEMA["required"] == ["completeness", "question", "missing", "example"]
        assert CLARIFY_SCHEMA["additionalProperties"] is False

    def test_schema_is_json_serialisable(self) -> None:
        """The mapping must survive ``--json-schema`` (dumped to a JSON literal)."""
        assert json.loads(json.dumps(CLARIFY_SCHEMA)) == CLARIFY_SCHEMA

    def test_schema_forbids_public_fact_questions(self) -> None:
        """The question/missing descriptions carry the research-first rule."""
        question_desc = CLARIFY_SCHEMA["properties"]["question"]["description"]
        assert "publicly verify" in question_desc
        assert "never repeating" in question_desc
        missing_desc = CLARIFY_SCHEMA["properties"]["missing"]["description"]
        assert "Public facts must not appear here" in missing_desc


class TestPrompts:
    def test_research_prompt_embeds_the_description(self) -> None:
        prompt = research_prompt("  一个 sandbox 里面运行 Serverless Devs CLI  ")
        assert "Serverless Devs CLI" in prompt

    def test_research_prompt_tells_agent_to_research_public_facts(self) -> None:
        """Public facts must be settled with the agent's own tools, not asked."""
        prompt = research_prompt("run serverless devs")
        assert "web_fetch" in prompt
        assert "公开查证" in prompt
        assert "不得向用户提问" in prompt
        assert "默认值" in prompt  # safe-default + recorded-assumption rule

    def test_assessment_prompt_embeds_the_description(self) -> None:
        prompt = assessment_prompt("  运行 python  ")
        assert "运行 python" in prompt
        assert "completeness" in prompt

    def test_assessment_prompt_forbids_public_fact_questions(self) -> None:
        prompt = assessment_prompt("run python")
        assert "公开查证" in prompt
        assert "不得作为问题提出" in prompt
        assert "授权语义" in prompt  # delegation rule
        assert "不得重复" in prompt  # anti-repeat rule

    def test_answer_prompt_embeds_the_answer(self) -> None:
        prompt = answer_prompt("  pandas  ")
        assert "pandas" in prompt
        assert "重新评估" in prompt

    def test_answer_prompt_lists_previously_asked_questions(self) -> None:
        """Asked questions are embedded so the model cannot repeat a topic."""
        prompt = answer_prompt("pandas", asked=("Which port?", "Which region?"))
        assert "- Which port?" in prompt
        assert "- Which region?" in prompt
        assert "不得重复" in prompt

    def test_answer_prompt_without_history_omits_the_asked_clause(self) -> None:
        prompt = answer_prompt("pandas")
        assert "已问过的问题" not in prompt

    def test_new_session_id_is_a_valid_uuid(self) -> None:
        uuid.UUID(new_session_id())  # raises when malformed
        assert new_session_id() != new_session_id()


class TestDelegationAnswers:
    """“你可以自己检索、决定、采用默认”等回答视为授权 Agent 处理。"""

    @pytest.mark.parametrize(
        "answer",
        [
            "你可以自己检索",
            "你自己决定",
            "你决定就好",
            "采用默认",
            "用默认的就行",
            "合理默认即可",
            "随便",
            "都可以",
            "我不确定",
            "you decide",
            "Up to you!",
            "use the default",
            "sensible default is fine",
            "no preference",
        ],
    )
    def test_delegation_phrases_are_recognised(self, answer: str) -> None:
        assert is_delegation_answer(answer)

    @pytest.mark.parametrize(
        "answer",
        [
            "端口必须是 8080",
            "用 Python 3.12，内存 4GB",
            "区域 cn-hangzhou，2 核",
            "entry command: python app.py",
            "port 8888",
        ],
    )
    def test_concrete_answers_are_not_delegation(self, answer: str) -> None:
        assert not is_delegation_answer(answer)

    def test_delegation_answer_gets_explicit_clause(self) -> None:
        """A delegation answer adds the settle-it-yourself instruction."""
        prompt = answer_prompt("你自己决定就好", asked=("Which version?",))
        assert "授权语义" in prompt
        assert "不得就同一主题再次提问" in prompt
        assert "- Which version?" in prompt

    def test_normal_answer_has_no_delegation_clause(self) -> None:
        prompt = answer_prompt("端口 8080")
        assert "授权语义" not in prompt


class TestParseAssessment:
    def test_full_payload(self) -> None:
        assessment = parse_assessment(
            {
                "completeness": 0.5,
                "question": "Which port should be exposed?",
                "missing": ["ports", "data"],
                "example": "python 3.12 with pandas, port 8888",
            }
        )
        assert assessment is not None
        assert assessment.completeness == 0.5
        assert assessment.question == "Which port should be exposed?"
        assert assessment.missing == ("ports", "data")
        assert assessment.example == "python 3.12 with pandas, port 8888"

    def test_non_mapping_returns_none(self) -> None:
        assert parse_assessment("not a mapping") is None
        assert parse_assessment(None) is None

    def test_missing_or_non_numeric_completeness_returns_none(self) -> None:
        assert parse_assessment({"question": "q"}) is None
        assert parse_assessment({"completeness": "high"}) is None

    def test_hundred_scale_is_divided(self) -> None:
        assessment = parse_assessment({"completeness": 90})
        assert assessment is not None
        assert assessment.completeness == 0.9

    def test_values_are_clamped_into_range(self) -> None:
        negative = parse_assessment({"completeness": -5})
        assert negative is not None and negative.completeness == 0.0
        oversized = parse_assessment({"completeness": 200})
        assert oversized is not None and oversized.completeness == 1.0

    def test_blank_question_and_example_become_none(self) -> None:
        assessment = parse_assessment(
            {"completeness": 0.9, "question": "  ", "missing": [], "example": ""}
        )
        assert assessment is not None
        assert assessment.question is None
        assert assessment.example is None

    def test_missing_entries_are_cleaned(self) -> None:
        assessment = parse_assessment(
            {
                "completeness": 0.4,
                "question": "q",
                "missing": [" ports ", "", 7, None],
                "example": "e",
            }
        )
        assert assessment is not None
        assert assessment.missing == ("ports",)


class TestAssessmentVerdict:
    def test_complete_at_the_threshold(self) -> None:
        assert ClarifyAssessment(completeness=0.8, question=None).complete

    def test_below_the_threshold_is_incomplete(self) -> None:
        assert not ClarifyAssessment(completeness=0.79, question="q").complete

    def test_missing_summary_falls_back_to_unknown(self) -> None:
        assert ClarifyAssessment(completeness=0.1, question="q").missing_summary() == "unknown"
        summary = ClarifyAssessment(
            completeness=0.1, question="q", missing=("ports", "data")
        ).missing_summary()
        assert summary == "ports, data"


class TestRunResearch:
    def _capture(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        result: QwenCodeRunResult | None = None,
        raises: Exception | None = None,
    ) -> dict[str, Any]:
        captured: dict[str, Any] = {}
        outcome = result or QwenCodeRunResult(text="facts", is_error=False, exit_code=0)

        def _fake(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
            captured["prompt"] = prompt
            captured.update(kwargs)
            if raises is not None:
                raise raises
            return outcome

        monkeypatch.setattr(clarify, "run_qwen_code_headless", _fake)
        return captured

    def test_research_uses_plain_run_with_session_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Research pins the native session and runs WITHOUT --json-schema."""
        captured = self._capture(monkeypatch)

        ok = clarify.run_research(
            "research this",
            binary=Path("/fake/qwen"),
            env={"OPENAI_API_KEY": "sk-test"},
            cwd=tmp_path,
            session_id=_SESSION,
        )

        assert ok is True
        assert captured["prompt"] == "research this"
        assert captured["session_id"] == _SESSION
        assert captured.get("resume") is None
        assert "json_schema" not in captured  # plain run — tool loop stays free
        assert captured["max_session_turns"] == RESEARCH_SESSION_TURNS
        assert captured["timeout"] == DEFAULT_RESEARCH_TIMEOUT

    def test_failed_run_degrades_to_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = QwenCodeRunResult(text="boom", is_error=True, exit_code=1)
        self._capture(monkeypatch, result=result)

        assert not clarify.run_research(
            "p", binary=Path("/fake/qwen"), env=None, cwd=tmp_path, session_id=_SESSION
        )

    def test_codegen_error_degrades_to_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture(monkeypatch, raises=AICodegenError("timed out"))

        assert not clarify.run_research(
            "p", binary=Path("/fake/qwen"), env=None, cwd=tmp_path, session_id=_SESSION
        )


class TestEvaluate:
    def _capture(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        result: QwenCodeRunResult | None = None,
    ) -> dict[str, Any]:
        captured: dict[str, Any] = {}
        outcome = result or QwenCodeRunResult(
            text=json.dumps(_PAYLOAD), is_error=False, exit_code=0, structured=_PAYLOAD
        )

        def _fake(prompt: str, **kwargs: Any) -> QwenCodeRunResult:
            captured["prompt"] = prompt
            captured.update(kwargs)
            return outcome

        monkeypatch.setattr(clarify, "run_qwen_code_headless", _fake)
        return captured

    def test_uses_native_session_and_structured_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture(monkeypatch)

        assessment = clarify.evaluate(
            "assess this",
            binary=Path("/fake/qwen"),
            env={"OPENAI_API_KEY": "sk-test"},
            cwd=tmp_path,
            session_id=_SESSION,
        )

        assert assessment is not None
        assert assessment.completeness == 0.9
        assert captured["prompt"] == "assess this"
        assert captured["session_id"] == _SESSION
        assert captured["resume"] is None
        assert captured["json_schema"] is CLARIFY_SCHEMA
        assert captured["max_session_turns"] == ASSESS_SESSION_TURNS

    def test_resume_round_continues_the_same_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture(monkeypatch)

        clarify.evaluate(
            "answer",
            binary=Path("/fake/qwen"),
            env=None,
            cwd=tmp_path,
            resume=_SESSION,
        )

        assert captured["resume"] == _SESSION
        assert captured["session_id"] is None

    def test_failed_run_degrades_to_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = QwenCodeRunResult(text="boom", is_error=True, exit_code=1)
        self._capture(monkeypatch, result=result)

        assert clarify.evaluate("p", binary=Path("/fake/qwen"), env=None, cwd=tmp_path) is None

    def test_codegen_error_degrades_to_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise AICodegenError("timed out")

        monkeypatch.setattr(clarify, "run_qwen_code_headless", _boom)

        assert clarify.evaluate("p", binary=Path("/fake/qwen"), env=None, cwd=tmp_path) is None

    def test_unparseable_payload_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = QwenCodeRunResult(text="hi", is_error=False, exit_code=0, structured="nope")
        self._capture(monkeypatch, result=result)

        assert clarify.evaluate("p", binary=Path("/fake/qwen"), env=None, cwd=tmp_path) is None


class TestOutcomeDefaults:
    def test_outcome_is_inert_by_default(self) -> None:
        outcome = clarify.ClarifyOutcome()
        assert outcome.session_id == ""
        assert outcome.rounds == 0
        assert not outcome.degraded
        assert not outcome.skipped
