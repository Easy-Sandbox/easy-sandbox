"""Natural language sandbox template inference engine.

Three-level fallback:
1. Keyword/regex matching (offline, fast)
2. LLM inference (OpenAI-compatible API)
3. Default fallback to "base"
"""
from __future__ import annotations

import json as _json
import re as _re
from dataclasses import dataclass, field
from typing import Optional

_HAS_CJK = _re.compile(r'[\u4e00-\u9fff]')


def _is_word_boundary_safe(kw: str) -> bool:
    """纯英文关键词可以使用 word boundary 匹配。"""
    return len(kw) > 0 and not _HAS_CJK.search(kw)

from serverless_sandbox.utils.logging import get_logger

logger = get_logger("agent.infer")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TemplateProfile:
    """Template profile with resource defaults."""

    name: str
    display_name: str
    description: str
    keywords: list[str]
    cpu: int = 1
    memory: int = 2048
    ports: list[int] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)


@dataclass
class InferResult:
    """Inference result."""

    template: str
    display_name: str
    cpu: int
    memory: int
    confidence: float  # 0.0 – 1.0
    ports: list[int] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Template catalog
# ---------------------------------------------------------------------------

TEMPLATE_CATALOG: list[TemplateProfile] = [
    TemplateProfile(
        name="code-interpreter",
        display_name="Code Interpreter",
        description="Python 代码执行和数据分析环境",
        keywords=[
            "python", "代码", "code", "运行", "execute", "jupyter",
            "notebook", "脚本", "script", "编程", "programming", "计算", "compute",
        ],
        cpu=2,
        memory=4096,
    ),
    TemplateProfile(
        name="python-data-science",
        display_name="Python Data Science",
        description="数据科学和机器学习环境，预装 pandas/numpy/matplotlib",
        keywords=[
            "数据分析", "data analysis", "csv", "excel", "pandas", "numpy",
            "matplotlib", "scipy", "机器学习", "ml", "deep learning", "深度学习",
            "torch", "tensorflow", "sklearn", "统计", "statistics", "可视化",
            "visualization", "数据科学", "data science", "分析",
        ],
        cpu=2,
        memory=4096,
        extras={"预装": "pandas, numpy, matplotlib, scipy"},
    ),
    TemplateProfile(
        name="node-web",
        display_name="Node.js Web",
        description="Node.js Web 服务开发环境",
        keywords=[
            "node", "nodejs", "node.js", "web服务", "web 服务", "web service",
            "express", "koa", "fastify", "npm", "http服务", "http server",
            "api服务", "api server", "rest", "restful", "后端", "backend",
            "网站", "做网站",
        ],
        cpu=1,
        memory=2048,
        ports=[3000, 9000],
    ),
    TemplateProfile(
        name="browser-automation",
        display_name="Browser Automation",
        description="浏览器自动化环境，预装 Chromium",
        keywords=[
            "playwright", "puppeteer", "selenium", "浏览器", "browser",
            "爬取", "crawl", "爬虫", "spider", "截图", "screenshot",
            "网页", "web page", "scrape", "scraping", "自动化", "automation",
            "headless", "chromium", "chrome",
        ],
        cpu=2,
        memory=4096,
        ports=[9000],
        extras={"附加": "Chromium 浏览器预装"},
    ),
    TemplateProfile(
        name="codex",
        display_name="Codex Agent",
        description="OpenAI Codex CLI Agent 运行环境",
        keywords=[
            "codex", "openai codex", "codex agent", "codex cli",
            "ai编程", "ai coding", "代码生成", "code generation",
        ],
        cpu=2,
        memory=4096,
        ports=[9000],
    ),
    TemplateProfile(
        name="qwen-code",
        display_name="Qwen Code",
        description="通义千问编码 Agent 运行环境，支持 qwen-code 驱动的 AI 自主部署",
        keywords=[
            "qwen", "qwen-code", "qwen code", "通义千问", "dashscope",
            "qwen 编程", "qwen 写代码", "部署", "deploy",
            "智能部署", "自动部署", "发布项目", "上线",
        ],
        cpu=2,
        memory=4096,
        ports=[8080, 9000],
    ),
    TemplateProfile(
        name="claude-code",
        display_name="Claude Code",
        description="Anthropic Claude Code Agent 运行环境",
        keywords=["claude", "claude code", "anthropic", "claude agent",
                  "claude 编程", "claude 写代码"],
        cpu=2, memory=4096,
        ports=[9000],
    ),
    TemplateProfile(
        name="qoder",
        display_name="Qoder",
        description="Qoder AI 编程助手运行环境",
        keywords=["qoder", "qoder agent", "qoder 编程"],
        cpu=2, memory=4096,
        ports=[9000],
    ),
    TemplateProfile(
        name="openclaw",
        display_name="OpenClaw",
        description="OpenClaw AI Agent 框架运行环境",
        keywords=["openclaw", "open claw", "openclaw agent"],
        cpu=2, memory=4096,
        ports=[18789, 9000],
    ),
    TemplateProfile(
        name="hermes-agent",
        display_name="Hermes Agent",
        description="NousResearch Hermes 模型驱动的 AI Agent",
        keywords=["hermes", "hermes agent", "nousresearch",
                  "hermes 模型"],
        cpu=2, memory=4096,
        ports=[9000],
    ),
    TemplateProfile(
        name="deepseek-harness",
        display_name="DeepSeek Harness",
        description="DeepSeek Agent Runtime 运行环境",
        keywords=["deepseek", "deepseek harness", "deepseek agent",
                  "dsh", "deepseek 编程"],
        cpu=2, memory=4096,
        ports=[9000],
    ),
    TemplateProfile(
        name="full-stack",
        display_name="Full Stack Dev",
        description="全栈开发环境，含 Node.js + Python + 常用工具",
        keywords=[
            "全栈", "full stack", "fullstack", "开发环境", "dev environment",
            "react", "vue", "angular", "前端", "frontend",
        ],
        cpu=2,
        memory=4096,
        ports=[3000, 8080],
    ),
    TemplateProfile(
        name="base",
        display_name="Base",
        description="基础 Ubuntu 环境",
        keywords=[
            "ubuntu", "linux", "基础", "basic", "shell", "bash",
            "命令行", "terminal", "通用", "general", "docker",
        ],
        cpu=1,
        memory=1024,
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def infer_template(
    description: str,
    *,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
) -> InferResult:
    """Infer the best sandbox template from a natural-language description.

    Three-level fallback:
    1. Keyword matching (offline, fast)
    2. LLM inference (if *llm_api_key* is provided)
    3. Default → ``base``

    Args:
        description: Natural language description of the desired sandbox.
        llm_api_key: OpenAI-compatible API key (optional).
        llm_model: LLM model name (default ``"qwen-plus"``).
        llm_base_url: API base URL (default DashScope compatible endpoint).

    Returns:
        An :class:`InferResult` with the recommended template and metadata.
    """
    # Level 1: keyword matching
    result = _keyword_infer(description)
    if result and result.confidence >= 0.8:
        logger.debug("Keyword match (high confidence): %s", result.template)
        return result

    # Level 2: LLM inference (if configured)
    if llm_api_key:
        try:
            llm_result = await _llm_infer(
                description,
                api_key=llm_api_key,
                model=llm_model or "qwen-plus",
                base_url=llm_base_url
                or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            if llm_result:
                logger.debug("LLM inferred template: %s", llm_result.template)
                return llm_result
        except Exception:
            logger.warning("LLM inference failed, falling back", exc_info=True)

    # Level 3: low-confidence keyword result is still better than nothing
    if result:
        logger.debug("Keyword match (low confidence): %s", result.template)
        return result

    # Level 4: absolute default
    base = _get_profile("base")
    logger.debug("No match found, using default template 'base'")
    return InferResult(
        template=base.name,
        display_name=base.display_name,
        cpu=base.cpu,
        memory=base.memory,
        confidence=0.5,
        reasoning="未匹配到特定模板，使用默认基础环境",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_profile(name: str) -> TemplateProfile:
    """Look up a catalog entry by name; fall back to *base*."""
    for p in TEMPLATE_CATALOG:
        if p.name == name:
            return p
    return next(p for p in TEMPLATE_CATALOG if p.name == "base")


def _keyword_infer(description: str) -> InferResult | None:
    """Score every catalog template by keyword overlap."""
    desc_lower = description.lower()
    scores: list[tuple[float, TemplateProfile, list[str]]] = []

    for profile in TEMPLATE_CATALOG:
        matched: list[str] = []
        for kw in profile.keywords:
            kw_lower = kw.lower()
            # 对不包含中文字符的关键词使用 word boundary 匹配，避免子串误匹配
            if _is_word_boundary_safe(kw_lower):
                if _re.search(r'\b' + _re.escape(kw_lower) + r'\b', desc_lower):
                    matched.append(kw)
            else:
                if kw_lower in desc_lower:
                    matched.append(kw)
        if matched:
            matched_count = len(matched)
            if matched_count >= 3:
                confidence = min(0.95, 0.82 + matched_count * 0.03)
            elif matched_count == 2:
                confidence = 0.85
            else:
                confidence = 0.80
            scores.append((confidence, profile, matched))

    if not scores:
        return None

    scores.sort(key=lambda x: (x[0], sum(len(k) for k in x[2])), reverse=True)
    confidence, best, matched_kw = scores[0]

    return InferResult(
        template=best.name,
        display_name=best.display_name,
        cpu=best.cpu,
        memory=best.memory,
        confidence=confidence,
        ports=list(best.ports),
        extras=dict(best.extras),
        reasoning=f"关键词匹配: {', '.join(matched_kw)}",
    )


async def _llm_infer(
    description: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> InferResult | None:
    """Call an OpenAI-compatible ``chat/completions`` endpoint."""
    import httpx

    template_list = "\n".join(
        f"- {p.name}: {p.description} (CPU={p.cpu}核, 内存={p.memory}MB)"
        for p in TEMPLATE_CATALOG
    )

    prompt = (
        "你是一个沙箱模板推荐系统。根据用户的描述，推荐最合适的沙箱模板。\n\n"
        f"可用模板:\n{template_list}\n\n"
        f'用户描述: "{description}"\n\n'
        '请返回 JSON 格式（不要返回其他内容）:\n'
        '"template": "模板名", "confidence": 0.0-1.0, "reasoning": "推荐原因"'
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # Strip fenced code blocks if present
            if "```" in content:
                content = content.split("```")[1].strip()
                if content.startswith("json"):
                    content = content[4:].strip()

            # Try to extract first {...} from surrounding text
            try:
                data = _json.loads(content)
            except _json.JSONDecodeError:
                match = _re.search(r'\{[^{}]*\}', content)
                if match:
                    content = match.group(0)
                data = _json.loads(content)
            template_name = data.get("template", "base")
            profile = _get_profile(template_name)
            return InferResult(
                template=profile.name,
                display_name=profile.display_name,
                cpu=profile.cpu,
                memory=profile.memory,
                confidence=max(0.0, min(0.9, float(data.get("confidence", 0.7)))),
                ports=list(profile.ports),
                extras=dict(profile.extras),
                reasoning=data.get("reasoning", "LLM 推断"),
            )
    except Exception:
        return None
