"""Golden-file snapshot tests for CLI evidence cases.

Iterates the offline-deterministic cases from the shared registry, invokes
via CliRunner, normalizes output, and compares against committed golden files
in ``tests/test_cli_evidence/golden/<case>.txt``.

Set ``EBX_UPDATE_EVIDENCE=1`` to **write** (seed / refresh) golden files
instead of asserting against them.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from easy_sandbox.cli.main import cli
from easy_sandbox.transport.config import reset_config

# Import shared registry
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.evidence_cases import REGISTRY, EvidenceCase, format_result, normalize  # noqa: E402

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("EBX_UPDATE_EVIDENCE", "") == "1"


def _safe_stderr(result) -> str:
    """Return result.stderr safely across Click versions.

    Click 8.5 always separates stderr; Click <8.5 raises ValueError
    when mix_stderr was not explicitly set to False.
    """
    try:
        return result.stderr or ""
    except ValueError:
        return ""


def _eligible_cases() -> list[EvidenceCase]:
    """Return cases suitable for golden-file testing (deterministic only)."""
    # Category A cases: always deterministic (offline)
    # Category B cases: deterministic when mocked
    return [c for c in REGISTRY if c.mock_setup is not None or c.category == "A"]


def _case_ids() -> list[str]:
    return [c.output_file for c in _eligible_cases()]


@pytest.fixture(autouse=True)
def _reset_cfg():
    # Remove any test-injected commands from the global CLI group
    # (e.g. _test_ctx added by test_main.py::test_context_options_stored)
    if hasattr(cli, 'commands') and cli.commands:
        for name in list(cli.commands):
            if name.startswith('_test'):
                del cli.commands[name]
    reset_config()
    yield
    reset_config()


@pytest.mark.parametrize("case", _eligible_cases(), ids=_case_ids())
def test_evidence_snapshot(case: EvidenceCase) -> None:
    """Compare normalised CLI output against committed golden file."""
    runner = CliRunner()

    cmd = list(case.command)
    if case.mock_setup is not None:
        with case.mock_setup() as env:
            if "command" in env:
                cmd = env["command"]
            result = runner.invoke(cli, cmd)
    else:
        result = runner.invoke(cli, cmd)

    raw = format_result(result.output or "", _safe_stderr(result), result.exit_code)
    actual = normalize(raw)

    golden_path = GOLDEN_DIR / f"{case.output_file}.txt"

    if UPDATE:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual)
        return  # nothing to assert — we just wrote the golden file

    if not golden_path.exists():
        pytest.skip(
            f"Golden file missing: {golden_path}\n"
            f"Regenerate with: EBX_UPDATE_EVIDENCE=1 pytest tests/test_cli_evidence/ -v\n"
            f"Or run: python scripts/capture_cli_evidence.py"
        )
    expected = golden_path.read_text()
    assert actual == expected, (
        f"Output mismatch for {case.output_file}\n"
        f"--- expected (golden) ---\n{expected}\n"
        f"--- actual ---\n{actual}\n"
        f"Run with EBX_UPDATE_EVIDENCE=1 to update."
    )
