"""Consistency tests for the bilingual Agent Skill installation guide.

Task 193 added ``docs/en/guide/agent-skill-installation.md`` and
``docs/zh/guide/agent-skill-installation.md`` plus short entry points in
``SKILL.md``, ``llms.txt``, the bilingual READMEs, and the docs indexes.

These tests keep the verified facts honest and both language versions in sync:

- both guides exist and every relative link resolves;
- every tool skill directory verified on 2026-09-29 is listed in both guides;
- ``npx skills add -a`` only ever names agents the CLI really supports;
- no code block pipes ``curl`` into a shell (project policy), while both
  guides do warn against that pattern;
- version pinning (``<TAG-OR-COMMIT>``) and hash verification are documented;
- commands, paths, and lockfile names shared across languages stay identical;
- entry points (SKILL.md / llms.txt / READMEs / docs indexes) link the guides.

Scope note: this file covers only the installation/distribution docs. The
natural-language create docs, tests, and golden files are out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

GUIDES = {
    "en": REPO_ROOT / "docs/en/guide/agent-skill-installation.md",
    "zh": REPO_ROOT / "docs/zh/guide/agent-skill-installation.md",
}
SKILL_MD = REPO_ROOT / "SKILL.md"
LLMS_TXT = REPO_ROOT / "llms.txt"
README_EN = REPO_ROOT / "README.md"
README_ZH = REPO_ROOT / "README.zh-CN.md"
DOCS_INDEX_EN = REPO_ROOT / "docs/en/README.md"
DOCS_INDEX_ZH = REPO_ROOT / "docs/zh/README.md"

# `skills` CLI agents verified against v1.7.0 `--help` output and the
# vercel-labs/skills README on 2026-09-29.
ALLOWED_AGENTS = {"qoder", "qoder-cn", "claude-code", "cursor", "qwen-code", "codex", "*"}

# Skill directories per tool (user and project level), verified against each
# vendor's documentation on 2026-09-29. Each fragment must appear in both guides.
REQUIRED_DIRECTORY_FRAGMENTS = (
    "~/.qoder/skills/",
    ".qoder/skills/",
    "~/.qoder-cn/skills/",
    "~/.claude/skills/",
    ".claude/skills/",
    "~/.cursor/skills/",
    ".cursor/skills/",
    "~/.agents/skills/",
    ".agents/skills/",
    "$HOME/.agents/skills/",
    "~/.qwen/skills/",
    ".qwen/skills/",
)

# Commands, URLs, and filenames that must stay byte-identical in both languages.
SHARED_TOKENS = (
    "Easy-Sandbox/easy-sandbox",
    "npx skills add",
    "pip index versions easy-sandbox",
    "skills-lock.json",
    "experimental_install",
    "git sparse-checkout set --no-cone /SKILL.md",
    "easy-sandbox[cli] @ git+https://github.com/Easy-Sandbox/easy-sandbox.git",
    "--target cursor",
    "~/.ebx/.env",
    "DISABLE_TELEMETRY=1",
    "DO_NOT_TRACK=1",
    "/plugin marketplace add",
    ".claude-plugin/marketplace.json",
    ".cursor-plugin/",
    "qoder-cn",
    "<TAG-OR-COMMIT>",
    "shasum -a 256",
)


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
    assert len(text) > 4000, f"{GUIDES[lang]} looks too short to be the full guide"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_relative_links_resolve(lang: str) -> None:
    path = GUIDES[lang]
    targets = re.findall(r"\]\(([^()\s]+)\)", _read(path))
    relative = [t for t in targets if not t.startswith(("http://", "https://", "#", "mailto:"))]
    assert relative, f"{path} should link sibling guides (mcp-integration, authentication)"
    missing = [t for t in relative if not (path.parent / t).exists()]
    assert not missing, f"{path} has broken relative links: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_in_guide_anchors_match_headings(lang: str) -> None:
    text = _read(GUIDES[lang])
    anchors = set(re.findall(r"\]\(#([^)\s]+)\)", text))
    if not anchors:
        return
    headings = re.findall(r"^#{1,6}\s+(.*)$", text, flags=re.MULTILINE)
    slugs = {_github_slug(h) for h in headings}
    missing = anchors - slugs
    assert not missing, f"{GUIDES[lang]} anchors do not match any heading: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_tool_directory_matrix_covers_all_tools(lang: str) -> None:
    text = _read(GUIDES[lang])
    missing = [frag for frag in REQUIRED_DIRECTORY_FRAGMENTS if frag not in text]
    assert not missing, f"guide ({lang}) is missing verified tool directories: {missing}"


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_agent_names_enumerated_in_guide(lang: str) -> None:
    text = _read(GUIDES[lang])
    missing = [name for name in sorted(ALLOWED_AGENTS - {"*"}) if name not in text]
    assert not missing, f"guide ({lang}) does not mention supported agents: {missing}"


def test_skills_cli_agent_flags_use_whitelisted_names() -> None:
    for path in (GUIDES["en"], GUIDES["zh"], SKILL_MD, README_EN, README_ZH):
        # Agent names start with a lowercase letter; `'?'*'?'` is the CLI wildcard.
        # (A bare [\w*-]+ also matched `shasum -a 256`, hence the narrower form.)
        used = set(re.findall(r"-a\s+([a-z][\w-]*|'?\*'?)", _read(path)))
        unknown = {name for name in used if name.strip("'") not in ALLOWED_AGENTS}
        assert not unknown, f"{path.name} passes unknown agents to the skills CLI: {unknown}"


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
def test_version_pinning_and_verification_documented(lang: str) -> None:
    text = _read(GUIDES[lang])
    for token in ("<TAG-OR-COMMIT>", "shasum -a 256"):
        assert token in text, f"guide ({lang}) must document {token!r}"


def test_en_zh_keep_shared_commands_identical() -> None:
    en = _read(GUIDES["en"])
    zh = _read(GUIDES["zh"])
    missing = [t for t in SHARED_TOKENS if t not in en or t not in zh]
    assert not missing, f"command/path tokens drifted between guides: {missing}"


def test_skill_first_sdk_second_messaging() -> None:
    assert "Skill first, SDK second" in _read(GUIDES["en"])
    assert "先装 Skill，后装 SDK" in _read(GUIDES["zh"])


def test_guides_declare_static_scope_without_restoring_ebx_skill() -> None:
    en = _read(GUIDES["en"])
    zh = _read(GUIDES["zh"])
    assert "adds no runtime to this repository" in en
    assert "不会给本仓库引入任何运行时" in zh
    assert "ebx skill" not in en, "guides must not reintroduce the removed `ebx skill` command"
    assert "ebx skill" not in zh


def test_entry_points_link_to_installation_guides() -> None:
    assert "docs/en/guide/agent-skill-installation.md" in _read(SKILL_MD)
    assert "docs/zh/guide/agent-skill-installation.md" in _read(SKILL_MD)
    assert "docs/en/guide/agent-skill-installation.md" in _read(LLMS_TXT)
    assert "docs/en/guide/agent-skill-installation.md" in _read(README_EN)
    assert "docs/zh/guide/agent-skill-installation.md" in _read(README_ZH)
    assert "guide/agent-skill-installation.md" in _read(DOCS_INDEX_EN)
    assert "guide/agent-skill-installation.md" in _read(DOCS_INDEX_ZH)
