"""Tests for agent/infer.py — NL template inference engine."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from serverless_sandbox.agent.infer import (
    InferResult,
    TEMPLATE_CATALOG,
    TemplateProfile,
    _keyword_infer,
    _llm_infer,
    infer_template,
)


# ---------------------------------------------------------------------------
# Catalog sanity checks
# ---------------------------------------------------------------------------

class TestTemplateCatalog:
    """Verify template catalog configuration."""

    def test_catalog_not_empty(self) -> None:
        assert len(TEMPLATE_CATALOG) >= 12

    def test_base_template_exists(self) -> None:
        names = [p.name for p in TEMPLATE_CATALOG]
        assert "base" in names

    def test_code_interpreter_template_exists(self) -> None:
        names = [p.name for p in TEMPLATE_CATALOG]
        assert "code-interpreter" in names

    def test_python_data_science_template_exists(self) -> None:
        names = [p.name for p in TEMPLATE_CATALOG]
        assert "python-data-science" in names

    def test_node_web_template_exists(self) -> None:
        names = [p.name for p in TEMPLATE_CATALOG]
        assert "node-web" in names

    def test_browser_automation_template_exists(self) -> None:
        names = [p.name for p in TEMPLATE_CATALOG]
        assert "browser-automation" in names

    def test_profile_is_dataclass(self) -> None:
        p = TEMPLATE_CATALOG[0]
        assert isinstance(p, TemplateProfile)
        assert isinstance(p.keywords, list)

    def test_each_profile_has_keywords(self) -> None:
        for p in TEMPLATE_CATALOG:
            assert len(p.keywords) > 0, f"{p.name} has no keywords"

    def test_all_twelve_templates_present(self) -> None:
        """All 12 templates must exist in the catalog."""
        names = {p.name for p in TEMPLATE_CATALOG}
        expected = {
            "code-interpreter",
            "python-data-science",
            "node-web",
            "browser-automation",
            "codex",
            "claude-code",
            "qoder",
            "openclaw",
            "hermes-agent",
            "deepseek-harness",
            "full-stack",
            "base",
        }
        assert expected.issubset(names), f"Missing templates: {expected - names}"

    def test_chinese_keywords_present(self) -> None:
        """Catalog should contain Chinese keywords for i18n support."""
        all_kws = []
        for p in TEMPLATE_CATALOG:
            all_kws.extend(p.keywords)
        assert "数据分析" in all_kws
        assert "机器学习" in all_kws
        assert "深度学习" in all_kws


# ---------------------------------------------------------------------------
# Keyword inference
# ---------------------------------------------------------------------------

class TestKeywordInfer:
    """Tests for the private _keyword_infer helper."""

    def test_python_keyword(self) -> None:
        result = _keyword_infer("I need python")
        assert result is not None
        assert result.template == "code-interpreter"

    def test_pandas_matches_data_science(self) -> None:
        result = _keyword_infer("use pandas to analyze CSV")
        assert result is not None
        assert result.template == "python-data-science"

    def test_no_match_returns_none(self) -> None:
        result = _keyword_infer("something completely unrelated xyz")
        assert result is None

    def test_confidence_range(self) -> None:
        result = _keyword_infer("python jupyter notebook")
        assert result is not None
        assert 0.0 < result.confidence <= 1.0


# ---------------------------------------------------------------------------
# Full infer_template
# ---------------------------------------------------------------------------

class TestInferTemplate:
    """Tests for infer_template()."""

    @pytest.mark.asyncio
    async def test_infer_python(self) -> None:
        result = await infer_template("I need a Python sandbox")
        assert isinstance(result, InferResult)
        assert result.template == "code-interpreter"

    @pytest.mark.asyncio
    async def test_infer_pandas(self) -> None:
        result = await infer_template("Run pandas data analysis")
        assert result.template == "python-data-science"

    @pytest.mark.asyncio
    async def test_infer_numpy(self) -> None:
        result = await infer_template("I want to use numpy for matrix operations")
        assert result.template == "python-data-science"

    @pytest.mark.asyncio
    async def test_infer_chinese_data_analysis(self) -> None:
        result = await infer_template("我需要做数据分析")
        assert result.template == "python-data-science"

    @pytest.mark.asyncio
    async def test_infer_chinese_machine_learning(self) -> None:
        result = await infer_template("做机器学习和数据分析")
        assert result.template == "python-data-science"

    @pytest.mark.asyncio
    async def test_infer_node(self) -> None:
        result = await infer_template("Run a node.js application with npm")
        assert result.template == "node-web"

    @pytest.mark.asyncio
    async def test_infer_web(self) -> None:
        result = await infer_template("Create a web application with express")
        assert result.template == "node-web"

    @pytest.mark.asyncio
    async def test_infer_react(self) -> None:
        result = await infer_template("Build a react frontend app")
        assert result.template == "full-stack"

    @pytest.mark.asyncio
    async def test_infer_default_fallback(self) -> None:
        result = await infer_template("just a random unrelated topic about cooking recipes xyz123")
        assert result.template == "base"
        assert result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_infer_case_insensitive(self) -> None:
        result = await infer_template("Use PANDAS for analysis")
        assert result.template == "python-data-science"

    @pytest.mark.asyncio
    async def test_infer_with_api_key_no_llm(self) -> None:
        """With an API key but LLM unreachable, should fall back to keyword or default."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await infer_template(
                "some obscure query about cooking xyz123",
                llm_api_key="fake-key",
            )
        assert result.template == "base"

    @pytest.mark.asyncio
    async def test_infer_torch(self) -> None:
        result = await infer_template("Train a model with torch")
        assert result.template == "python-data-science"

    @pytest.mark.asyncio
    async def test_infer_playwright(self) -> None:
        result = await infer_template("Use playwright to test web pages")
        assert result.template == "browser-automation"

    @pytest.mark.asyncio
    async def test_infer_result_has_reasoning(self) -> None:
        result = await infer_template("I need python")
        assert result.reasoning != ""

    @pytest.mark.asyncio
    async def test_infer_result_has_resources(self) -> None:
        result = await infer_template("I need python")
        assert result.cpu > 0
        assert result.memory > 0


# ---------------------------------------------------------------------------
# Core use-case tests (4 exact user scenarios)
# ---------------------------------------------------------------------------

class TestCoreUseCases:
    """Verify the 4 core user scenarios produce correct template + high confidence."""

    @pytest.mark.asyncio
    async def test_run_python_run_codex(self) -> None:
        result = await infer_template("运行 python，运行 codex")
        assert result.template == "code-interpreter"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_start_nodejs_web_service(self) -> None:
        result = await infer_template("启动一个 Node.js Web 服务")
        assert result.template == "node-web"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_playwright_crawl_screenshot(self) -> None:
        result = await infer_template("用 playwright 爬取网页并截图")
        assert result.template == "browser-automation"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_analyze_csv_file(self) -> None:
        result = await infer_template("分析这个 CSV 文件")
        assert result.template == "python-data-science"
        assert result.confidence >= 0.8


# ---------------------------------------------------------------------------
# English description matching
# ---------------------------------------------------------------------------

class TestEnglishDescriptions:
    """English descriptions should also match correctly."""

    @pytest.mark.asyncio
    async def test_data_analysis(self) -> None:
        result = await infer_template("data analysis with pandas and csv")
        assert result.template == "python-data-science"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_web_scraping(self) -> None:
        result = await infer_template("web scraping with playwright browser")
        assert result.template == "browser-automation"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_machine_learning(self) -> None:
        result = await infer_template("deep learning with torch and sklearn")
        assert result.template == "python-data-science"
        assert result.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_node_backend(self) -> None:
        result = await infer_template("build a restful api server with express")
        assert result.template == "node-web"
        assert result.confidence >= 0.8


# ---------------------------------------------------------------------------
# Confidence range checks
# ---------------------------------------------------------------------------

class TestConfidenceRange:
    """Confidence must always be in [0.0, 1.0]."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "desc",
        [
            "python jupyter notebook 脚本",
            "use pandas and numpy for statistics",
            "playwright browser screenshot",
            "just a random thing xyz123",
        ],
    )
    async def test_confidence_within_bounds(self, desc: str) -> None:
        result = await infer_template(desc)
        assert 0.0 <= result.confidence <= 1.0


# ---------------------------------------------------------------------------
# LLM inference (mocked)
# ---------------------------------------------------------------------------

class TestLLMInference:
    """LLM fallback path with mocked httpx.AsyncClient."""

    @pytest.mark.asyncio
    async def test_llm_infer_success(self) -> None:
        """Mock a successful LLM response returning a valid template."""
        llm_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "template": "browser-automation",
                                "confidence": 0.85,
                                "reasoning": "用户需要浏览器自动化",
                            }
                        )
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = llm_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _llm_infer(
                "我要自动化测试",
                api_key="sk-test",
                model="qwen-plus",
                base_url="https://example.com/v1",
            )

        assert result is not None
        assert result.template == "browser-automation"
        assert result.confidence <= 0.9  # capped at 0.9

    @pytest.mark.asyncio
    async def test_llm_infer_fenced_json(self) -> None:
        """LLM returns JSON inside markdown fenced block."""
        content = '```json\n{"template": "node-web", "confidence": 0.8, "reasoning": "test"}\n```'
        llm_response = {"choices": [{"message": {"content": content}}]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = llm_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _llm_infer(
                "web service",
                api_key="sk-test",
                model="qwen-plus",
                base_url="https://example.com/v1",
            )

        assert result is not None
        assert result.template == "node-web"

    @pytest.mark.asyncio
    async def test_llm_infer_http_error_returns_none(self) -> None:
        """HTTP error from the LLM endpoint should return None."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock()
            )
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _llm_infer(
                "anything",
                api_key="sk-test",
                model="qwen-plus",
                base_url="https://example.com/v1",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_infer_invalid_json_returns_none(self) -> None:
        """Malformed JSON from LLM should return None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "not valid json {{{"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await _llm_infer(
                "anything",
                api_key="sk-test",
                model="qwen-plus",
                base_url="https://example.com/v1",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_infer_template_llm_fallback_on_low_keyword_confidence(self) -> None:
        """When keyword match is low-confidence, LLM should be tried."""
        llm_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "template": "full-stack",
                                "confidence": 0.9,
                                "reasoning": "LLM decided",
                            }
                        )
                    }
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = llm_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await infer_template(
                "zxy987 unrelated topic about cooking recipes",
                llm_api_key="sk-test",
            )

        assert result.template == "full-stack"

    @pytest.mark.asyncio
    async def test_infer_template_llm_failure_graceful_fallback(self) -> None:
        """LLM call fails → should fall back to keyword or default."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await infer_template(
                "something completely unrelated xyz987 about cooking",
                llm_api_key="sk-test",
            )

        # Should fall back to base since no keywords match
        assert result.template == "base"
        assert result.confidence == 0.5
