"""Consistency tests for the static agent guide (SKILL.md + llms.txt).

These tests keep the agent-facing guide honest against the code:

- SKILL.md follows the common Agent Skills frontmatter format (name/description).
- SKILL.md covers the required usage topics (install, credentials, MCP vs SDK,
  lifecycle, files, cleanup, error diagnosis, credential-leak rules).
- SKILL.md is explicitly a static guide and documents that it does not restore
  the removed ``ebx skill`` command group / Skills registry / runtime.
- MCP tool names cited in SKILL.md match ``agent/tools.py`` TOOL_SCHEMAS.
- Repository paths cited in SKILL.md / llms.txt exist.
- llms.txt references SKILL.md and only names commands the CLI really registers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="pyyaml (cli extra) is required for frontmatter parsing")

from easy_sandbox.agent.tools import TOOL_SCHEMAS

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "SKILL.md"
LLMS_TXT = REPO_ROOT / "llms.txt"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing agent-facing doc: {path}"
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    end = text.find("\n---\n", 4)
    assert end != -1, "SKILL.md frontmatter is not closed"
    import yaml

    data = yaml.safe_load(text[4 : end + 1])
    assert isinstance(data, dict), "SKILL.md frontmatter must be a mapping"
    return data


# ---------------------------------------------------------------------------
# SKILL.md — Agent Skills format
# ---------------------------------------------------------------------------


class TestSkillFrontmatter:
    def test_name_and_description_present(self) -> None:
        fm = _frontmatter(_read(SKILL_MD))
        assert fm.get("name") == "easy-sandbox"
        assert isinstance(fm.get("description"), str) and fm["description"].strip()

    def test_name_format_matches_agent_skills_convention(self) -> None:
        name = _frontmatter(_read(SKILL_MD))["name"]
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name), (
            "skill name must be lowercase with hyphens (Agent Skills convention)"
        )
        assert len(name) <= 64

    def test_description_mentions_when_to_use(self) -> None:
        description = _frontmatter(_read(SKILL_MD))["description"]
        assert len(description) <= 1024
        lowered = description.lower()
        assert "use this" in lowered or "use when" in lowered, (
            "description should state when the agent should use the skill"
        )


# ---------------------------------------------------------------------------
# SKILL.md — required coverage and static-guide scope
# ---------------------------------------------------------------------------

_REQUIRED_TOPICS = {
    "when to use": "applicable scenarios",
    "installation": "install",
    "credential": "credential handling",
    "mcp": "MCP interface rules",
    "sdk": "Python SDK",
    "creating a sandbox": "sandbox creation",
    "executing code and commands": "code/command execution",
    "file operations": "file operations",
    "destroying resources": "resource cleanup",
    "diagnosing common errors": "error diagnosis",
    "never print, echo, log": "credential-leak prohibition",
}


class TestSkillCoverage:
    def test_required_topics_covered(self) -> None:
        text = _read(SKILL_MD).lower()
        missing = [label for needle, label in _REQUIRED_TOPICS.items() if needle not in text]
        assert not missing, f"SKILL.md is missing required topics: {missing}"

    def test_declares_static_guide_scope(self) -> None:
        text = _read(SKILL_MD)
        normalized = text.replace("**", "")
        lowered = normalized.lower()
        assert "static usage guide" in lowered
        assert "does not restore" in lowered, (
            "SKILL.md must state it does not restore the removed skills system"
        )
        assert "not executed, parsed, or registered" in lowered

    def test_skill_command_mentions_are_disclaimers_only(self) -> None:
        """`ebx skill` may only appear inside the removal disclaimer."""
        normalized = _read(SKILL_MD).replace("**", "")
        for line in normalized.splitlines():
            if "ebx skill" in line.lower():
                assert "removed" in line.lower(), (
                    "mentions of `ebx skill` must reference its removal, not usage"
                )


# ---------------------------------------------------------------------------
# SKILL.md — code alignment
# ---------------------------------------------------------------------------


class TestSkillMatchesCode:
    def test_mcp_tool_names_match_tool_schemas(self) -> None:
        """Every MCP tool shipped by agent/tools.py is documented in SKILL.md."""
        text = _read(SKILL_MD)
        documented = {t["name"] for t in TOOL_SCHEMAS if t["name"] in text}
        expected = {t["name"] for t in TOOL_SCHEMAS}
        assert documented == expected, (
            f"SKILL.md MCP tool coverage drifted from agent/tools.py: {expected - documented}"
        )

    def test_referenced_repo_paths_exist(self) -> None:
        """Backtick-quoted relative paths in SKILL.md resolve on disk."""
        text = _read(SKILL_MD)
        candidates = re.findall(r"`([^`\n]+)`", text)
        paths = [
            c
            for c in candidates
            if (
                ("/" in c or c.endswith((".md", ".txt")))
                and not c.startswith(("/", "~"))
                and re.fullmatch(r"[\w./-]+", c)
                and "<" not in c
            )
        ]
        assert paths, "expected SKILL.md to reference at least one repo path"
        missing = [p for p in paths if not (REPO_ROOT / p).exists()]
        assert not missing, f"SKILL.md references non-existent paths: {missing}"

    def test_cited_error_codes_exist(self) -> None:
        """Error codes cited in SKILL.md are defined in models/errors.py."""
        from easy_sandbox.models import errors as err_mod

        cited = set(re.findall(r"\bE\d{4}\b", _read(SKILL_MD)))
        assert cited, "expected SKILL.md to cite error codes"
        defined: set[str] = set()
        for attr in vars(err_mod).values():
            if isinstance(attr, type) and issubclass(attr, Exception):
                for match in re.findall(r"\bE\d{4}\b", str(getattr(attr, "code", ""))):
                    defined.add(match)
        # Also accept codes the CLI maps for raw HTTP failures (main.py).
        defined |= {"E1000", "E2002", "E3001", "E5000", "E5001", "E5003"}
        unknown = cited - defined
        assert not unknown, f"SKILL.md cites undefined error codes: {unknown}"


# ---------------------------------------------------------------------------
# llms.txt — cross references and real commands
# ---------------------------------------------------------------------------


class TestLlmsTxt:
    def test_references_skill_md(self) -> None:
        assert "SKILL.md" in _read(LLMS_TXT)

    def test_links_section_paths_exist(self) -> None:
        text = _read(LLMS_TXT)
        links = re.findall(r"^- (?:.*?):\s*(\S+)\s*$", text, flags=re.MULTILINE)
        assert links, "expected llms.txt to have a Links section"
        local = [link for link in links if not link.startswith(("http://", "https://"))]
        missing = [link for link in local if not (REPO_ROOT / link).exists()]
        assert not missing, f"llms.txt Links point to non-existent paths: {missing}"

    def test_cli_examples_use_registered_commands(self) -> None:
        """Every `ebx <cmd>` first token in llms.txt is a real CLI command."""
        import click

        from easy_sandbox.cli.main import cli

        registered = set(cli.list_commands(click.Context(cli)))
        text = _read(LLMS_TXT)
        used = set(re.findall(r"^\s*ebx\s+(\S+)", text, flags=re.MULTILINE))
        unknown = used - registered
        assert not unknown, f"llms.txt references unknown CLI commands: {unknown}"
