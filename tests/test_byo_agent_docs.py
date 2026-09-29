"""Consistency tests for the bilingual BYO agent integration guide.

Task 196 added ``docs/en/guide/byo-agent-integration.md`` and
``docs/zh/guide/byo-agent-integration.md`` plus index entries in
``docs/{en,zh}/README.md`` / ``docs/{en,zh}/DESIGN.md`` and the ADR
``.agents/notes/implemented/architecture/2026-09-29-byo-agent-integration-contract.md``.

These tests keep the verified facts honest and both language versions in sync:

- both guides exist and every relative link resolves;
- every agent covered by task 195 (Qwen Code, Codex, Claude Code, Qoder CLI,
  custom agents) is present in both guides;
- the responsibility split, the two-axes explanation, and the
  "no agent CLI in the base image" rule are documented in both languages;
- the credential whitelist, version pinning (``<X.Y.Z>`` / ``shasum -a 256``),
  license boundaries, and the sandbox-only permission-bypass rule are present;
- the minimal ``custom_commands`` contract fields are documented;
- the Qwen Code example uses the current positional prompt form
  (``qwen {prompt}``), and the deprecated ``qwen -p`` flag is absent;
- no code block pipes ``curl`` into a shell (project policy), while both
  guides do warn against that pattern;
- commands, flags, environment-variable names, and paths shared across
  languages stay identical;
- the docs indexes and the ADR link the guides.

Scope note: this file covers only the BYO agent integration docs. External
template convergence (awesome-templates repository) and the Agent Skill
installation guides (task 193) are out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

GUIDES = {
    "en": REPO_ROOT / "docs/en/guide/byo-agent-integration.md",
    "zh": REPO_ROOT / "docs/zh/guide/byo-agent-integration.md",
}
DOCS_INDEX_EN = REPO_ROOT / "docs/en/README.md"
DOCS_INDEX_ZH = REPO_ROOT / "docs/zh/README.md"
DESIGN_EN = REPO_ROOT / "docs/en/DESIGN.md"
DESIGN_ZH = REPO_ROOT / "docs/zh/DESIGN.md"
ADR = (
    REPO_ROOT
    / ".agents/notes/implemented/architecture/2026-09-29-byo-agent-integration-contract.md"
)

# Every agent from task 195 that the guide must cover, in both languages.
REQUIRED_AGENTS = ("Qwen Code", "Codex", "Claude Code", "Qoder CLI")

# Authentication environment variables from the verified whitelist.
REQUIRED_ENV_VARS = (
    "DASHSCOPE_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "QODER_PERSONAL_ACCESS_TOKEN",
)

# Commands, flags, env names, and paths that must stay byte-identical in both
# languages (verified 2026-09-29 against vendor documentation).
SHARED_TOKENS = (
    "custom_commands",
    "agent_probe",
    "agent_run",
    "command -v qwen",
    "qwen {prompt} --output-format json --max-session-turns {max_turns}",
    'codex exec "<prompt>" --json',
    'claude -p "<prompt>"',
    'qoder -p "<prompt>"',
    "codex exec",
    "claude -p",
    "qoder -p",
    'qwen "<prompt>" --output-format json',
    "--output-format json",
    "stream-json",
    "--max-session-turns",
    "--max-turns",
    "--allowedTools",
    "--sandbox workspace-write",
    "--permission-mode bypass_permissions",
    "--yolo",
    "--bare",
    "DASHSCOPE_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "QODER_PERSONAL_ACCESS_TOKEN",
    "@qwen-code/qwen-code@<X.Y.Z>",
    "@openai/codex@<X.Y.Z>",
    "npm install -g @qwen-code/qwen-code@<X.Y.Z>",
    "<X.Y.Z>",
    "shasum -a 256",
    "shlex.quote()",
    "/workspace",
    "template.yaml",
    "resources.cpu",
    "resources.memory",
    "SANDBOX_HTTP_TIMEOUT",
    "ebx config set http_timeout N",
    "ebx kill <id>",
    "ebx create --template my-qwen-agent --env DASHSCOPE_API_KEY=<YOUR_KEY> --timeout 3600",
    "ebx run <sandbox-id> agent_probe",
    'ebx run <sandbox-id> agent_run --arg prompt="fix the failing test in tests/"',
    'sb.custom("agent_run", prompt="fix the failing test in tests/")',
    "sandbox.custom()",
    "sandbox.list_commands()",
    "CommandResult",
    "exit_code",
    "stderr",
    "Apache-2.0",
    "curl … | sh",
    "/usr/local/bin",
    "2026-09-29",
)

# Facts that are asserted in each language (paraphrase-tolerant pins).
REQUIRED_FRAGMENTS = {
    "en": (
        "Easy Sandbox provides",
        "The agent CLI provides",
        "ships no agent CLI",
        "two independent axes",
        "does not recommend",
        "Official template eligible",
        "Proprietary",
        "distributes no proprietary binaries",
        "disposable sandboxes",
    ),
    "zh": (
        "Easy Sandbox 提供",
        "Agent CLI 自行提供",
        "默认基础镜像不预装任何 Agent CLI",
        "两条彼此独立的轴",
        "不推荐",
        "可做官方模板",
        "专有",
        "本仓库不分发任何专有二进制",
        "可丢弃的沙箱",
    ),
}

# Minimal-contract fields of the CustomCommand model.
CONTRACT_FIELDS = ("cmd", "description", "cwd", "timeout", "env", "args")


def _read(path: Path) -> str:
    assert path.is_file(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def _fenced_blocks(text: str) -> str:
    """Concatenated contents of all fenced code blocks in *text*."""
    return "\n".join(re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL))


def _github_slug(heading: str) -> str:
    """Approximate GitHub's heading anchor slug for in-guide anchor checks."""
    cleaned = re.sub(r"[^\w\s-]", "", heading.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", "-", cleaned.strip())


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_guide_exists_and_is_substantial(lang: str) -> None:
    text = _read(GUIDES[lang])
    assert len(text) > 6000, f"{GUIDES[lang]} looks too short to be the full guide"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_relative_links_resolve(lang: str) -> None:
    path = GUIDES[lang]
    targets = re.findall(r"\]\(([^()\s]+)\)", _read(path))
    relative = [t for t in targets if not t.startswith(("http://", "https://", "#", "mailto:"))]
    assert relative, f"{path} should link sibling guides (authoring-templates, mcp-integration)"
    missing = [t for t in relative if not (path.parent / t).exists()]
    assert not missing, f"{path} has broken relative links: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_in_guide_anchors_match_headings(lang: str) -> None:
    text = _read(GUIDES[lang])
    anchors = set(re.findall(r"\]\(#([^)\s]+)\)", text))
    assert anchors, f"{GUIDES[lang]} should cross-reference its own sections"
    headings = re.findall(r"^#{1,6}\s+(.*)$", text, flags=re.MULTILINE)
    slugs = {_github_slug(h) for h in headings}
    missing = anchors - slugs
    assert not missing, f"{GUIDES[lang]} anchors do not match any heading: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_agent_matrix_covers_all_agents(lang: str) -> None:
    text = _read(GUIDES[lang])
    missing = [name for name in REQUIRED_AGENTS if name not in text]
    assert not missing, f"guide ({lang}) does not cover agents: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_responsibility_split_and_two_axes_documented(lang: str) -> None:
    text = _read(GUIDES[lang])
    missing = [frag for frag in REQUIRED_FRAGMENTS[lang] if frag not in text]
    assert not missing, f"guide ({lang}) is missing required statements: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_credential_whitelist_names_present(lang: str) -> None:
    text = _read(GUIDES[lang])
    missing = [name for name in REQUIRED_ENV_VARS if name not in text]
    assert not missing, f"guide ({lang}) is missing whitelisted env vars: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_custom_commands_contract_fields_documented(lang: str) -> None:
    text = _read(GUIDES[lang])
    assert "custom_commands" in text, f"guide ({lang}) must anchor the contract on custom_commands"
    for field in CONTRACT_FIELDS:
        assert f"`{field}`" in text, f"guide ({lang}) must document CustomCommand field {field!r}"
    assert "CustomCommand" in text, f"guide ({lang}) should name the CustomCommand model"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_no_curl_pipe_into_shell_in_code_blocks(lang: str) -> None:
    blocks = _fenced_blocks(_read(GUIDES[lang]))
    pattern = r"curl[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"
    assert not re.search(pattern, blocks), (
        f"{GUIDES[lang]} must never demonstrate piping curl into a shell"
    )


def test_guides_warn_against_curl_pipes() -> None:
    en = _read(GUIDES["en"])
    zh = _read(GUIDES["zh"])
    assert "curl" in en and "| sh" in en and "does not recommend" in en
    assert "curl" in zh and "| sh" in zh and "不推荐" in zh


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_version_pinning_and_hash_verification_documented(lang: str) -> None:
    text = _read(GUIDES[lang])
    for token in ("<X.Y.Z>", "shasum -a 256"):
        assert token in text, f"guide ({lang}) must document {token!r}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_qwen_uses_positional_prompt(lang: str) -> None:
    """Task 204: Qwen Code takes the prompt as a positional argument
    (``qwen {prompt}``); the deprecated ``qwen -p`` prompt flag must not
    reappear in examples, tables, or notes."""
    text = _read(GUIDES[lang])
    assert "qwen -p" not in text, (
        f"guide ({lang}) must not show the deprecated `qwen -p` prompt form"
    )
    assert "qwen {prompt}" in text, (
        f"guide ({lang}) must document the positional form `qwen {{prompt}}`"
    )
    marker = "deprecated" if lang == "en" else "已弃用"
    assert marker in text, f"guide ({lang}) should flag the `-p` form as deprecated"


def test_en_zh_keep_shared_tokens_identical() -> None:
    en = _read(GUIDES["en"])
    zh = _read(GUIDES["zh"])
    missing = [t for t in SHARED_TOKENS if t not in en or t not in zh]
    assert not missing, f"command/flag/env tokens drifted between guides: {missing}"


def test_guides_cross_link_languages() -> None:
    # Guides live in docs/<lang>/guide/, so cross-language links climb two levels.
    assert "../../zh/guide/byo-agent-integration.md" in _read(GUIDES["en"])
    assert "../../en/guide/byo-agent-integration.md" in _read(GUIDES["zh"])


def test_guides_do_not_reintroduce_removed_surfaces() -> None:
    for lang in GUIDES:
        text = _read(GUIDES[lang])
        assert "ebx skill" not in text, (
            f"guide ({lang}) must not reintroduce the removed `ebx skill` command"
        )


def test_docs_indexes_link_the_guides() -> None:
    assert "guide/byo-agent-integration.md" in _read(DOCS_INDEX_EN)
    assert "guide/byo-agent-integration.md" in _read(DOCS_INDEX_ZH)
    assert "guide/byo-agent-integration.md" in _read(DESIGN_EN)
    assert "guide/byo-agent-integration.md" in _read(DESIGN_ZH)


def test_adr_records_the_decision_and_links_guides() -> None:
    text = _read(ADR)
    assert "Status: implemented" in text, "ADR status must match its implemented/ directory"
    assert "docs/en/guide/byo-agent-integration.md" in text
    assert "docs/zh/guide/byo-agent-integration.md" in text
    assert "no in-SDK agent runtime" in text
    assert "custom_commands contract" in text
