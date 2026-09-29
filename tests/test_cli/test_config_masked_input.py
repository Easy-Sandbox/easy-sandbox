"""Tests for the masked secret input used by `ebx config init`.

``_feed_masked`` / ``_read_masked_line`` are driven with an injected
reader/writer; a real-pty suite (POSIX only) pins the asterisk behaviour
end to end: one ``*`` per character, never the plaintext.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from easy_sandbox.cli.commands.config_cmd import (
    _feed_masked,
    _mask_supported,
    _mask_value,
    _read_masked_line,
)

_CHILD_CODE = r"""
import sys
from easy_sandbox.cli.commands.config_cmd import _prompt_secret
try:
    value = _prompt_secret("Prompt")
except BaseException as exc:
    sys.stdout.write("\nRESULT:ERR:" + type(exc).__name__ + "\n")
else:
    sys.stdout.write("\nRESULT:" + repr(value) + "\n")
sys.stdout.flush()
"""


class TestMaskValue:
    def test_short_values_are_masked_completely(self) -> None:
        assert _mask_value("ab") == "***"
        assert _mask_value("12345678") == "***"

    def test_long_values_show_only_edges(self) -> None:
        assert _mask_value("sk-test-abcdef123456") == "sk-***456"

    def test_empty_value_stays_empty(self) -> None:
        assert _mask_value("") == ""


class TestMaskSupported:
    def test_false_for_non_tty_stdin(self) -> None:
        with patch("sys.stdin", io.StringIO()):
            assert _mask_supported() is False


class TestFeedMasked:
    def test_one_asterisk_per_printable_char(self) -> None:
        chars: list[str] = []
        out: list[str] = []
        assert _feed_masked("abc", chars, out.append) is None
        assert chars == ["a", "b", "c"]
        assert "".join(out) == "***"

    def test_enter_finishes_line(self) -> None:
        chars: list[str] = []
        out: list[str] = []
        assert _feed_masked("abc\n", chars, out.append) == "abc"
        assert "".join(out) == "***\n"

    def test_carriage_return_finishes_line(self) -> None:
        assert _feed_masked("abc\r", [], lambda _: None) == "abc"

    def test_backspace_erases_last_char(self) -> None:
        chars = ["a", "b"]
        out: list[str] = []
        assert _feed_masked("\x7f", chars, out.append) is None
        assert chars == ["a"]
        assert "".join(out) == "\b \b"

    def test_backspace_on_empty_is_noop(self) -> None:
        chars: list[str] = []
        out: list[str] = []
        assert _feed_masked("\x7f", chars, out.append) is None
        assert chars == []
        assert out == []

    def test_ctrl_c_raises_keyboard_interrupt(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            _feed_masked("\x03", [], lambda _: None)

    def test_ctrl_d_on_empty_raises_eof(self) -> None:
        with pytest.raises(EOFError):
            _feed_masked("\x04", [], lambda _: None)

    def test_ctrl_d_with_input_submits(self) -> None:
        assert _feed_masked("\x04", ["a", "b"], lambda _: None) == "ab"

    def test_ctrl_z_on_empty_raises_eof(self) -> None:
        with pytest.raises(EOFError):
            _feed_masked("\x1a", [], lambda _: None)

    def test_paste_block_counts_per_character(self) -> None:
        chars: list[str] = []
        out: list[str] = []
        assert _feed_masked("pastedSecret123\n", chars, out.append) == "pastedSecret123"
        assert "".join(out) == "*" * 15 + "\n"

    def test_unicode_counts_characters_not_bytes(self) -> None:
        chars: list[str] = []
        out: list[str] = []
        assert _feed_masked("päö🔥\n", chars, out.append) == "päö🔥"
        assert "".join(out) == "****\n"

    def test_other_control_chars_are_neither_stored_nor_printed(self) -> None:
        chars: list[str] = []
        out: list[str] = []
        assert _feed_masked("\x01\x02ab", chars, out.append) is None
        assert chars == ["a", "b"]
        assert "".join(out) == "**"


class TestReadMaskedLine:
    def test_reads_char_by_char(self) -> None:
        keys = iter(["a", "b", "c", "\n"])
        out: list[str] = []
        value = _read_masked_line("Prompt: ", reader=lambda: next(keys), writer=out.append)
        assert value == "abc"
        assert "".join(out) == "Prompt: ***\n"

    def test_accepts_paste_chunk(self) -> None:
        chunks = iter(["pastedSecret\n"])
        out: list[str] = []
        value = _read_masked_line("Prompt: ", reader=lambda: next(chunks), writer=out.append)
        assert value == "pastedSecret"
        assert "".join(out) == "Prompt: " + "*" * 12 + "\n"

    def test_eof_raises(self) -> None:
        keys = iter(["a", ""])
        with pytest.raises(EOFError):
            _read_masked_line("Prompt: ", reader=lambda: next(keys), writer=lambda _: None)

    def test_ctrl_c_raises(self) -> None:
        keys = iter(["a", "\x03"])
        with pytest.raises(KeyboardInterrupt):
            _read_masked_line("Prompt: ", reader=lambda: next(keys), writer=lambda _: None)

    def test_plaintext_never_written(self) -> None:
        keys = iter([*"secret123", "\n"])
        out: list[str] = []
        value = _read_masked_line("Prompt: ", reader=lambda: next(keys), writer=out.append)
        rendered = "".join(out)
        assert value == "secret123"
        assert "secret123" not in rendered


# ─── real pty (POSIX only) ─────────────────────────────────────────────────


def _run_prompt_in_pty(
    payload: bytes,
    *,
    hold: int | None = None,
    wait_for: bytes | None = None,
) -> tuple[str, str]:
    """Drive ``_prompt_secret`` in a child process owning a real pty.

    Returns ``(terminal_output, result_line)`` where *terminal_output* is
    everything the terminal displayed (including the prompt and asterisks)
    and *result_line* is what the child printed after ``RESULT:``.

    When *hold* is given, the first *hold* payload bytes are sent after the
    prompt, the remainder only after *wait_for* appears on the terminal —
    mirroring a user typing and then pressing Ctrl-C.
    """
    import fcntl
    import pty
    import select
    import subprocess
    import termios
    import time

    project_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root / "src") + os.pathsep + env.get("PYTHONPATH", "")

    master, slave = pty.openpty()

    def preexec() -> None:  # pragma: no cover - child process setup
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_CODE],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        preexec_fn=preexec,
        env=env,
    )
    os.close(slave)
    out = bytearray()
    parts = [payload] if hold is None else [payload[:hold], payload[hold:]]
    sent = 0
    deadline = time.time() + 15
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out.extend(chunk)
            if sent == 0 and b"Prompt: " in bytes(out):
                time.sleep(0.1)
                os.write(master, parts[0])
                sent = 1
            elif sent == 1 and len(parts) > 1 and wait_for is not None and wait_for in bytes(out):
                time.sleep(0.05)
                os.write(master, parts[1])
                sent = 2
            if proc.poll() is not None:
                time.sleep(0.2)
                try:
                    while True:
                        r2, _, _ = select.select([master], [], [], 0.1)
                        if not r2:
                            break
                        tail = os.read(master, 4096)
                        if not tail:
                            break
                        out.extend(tail)
                except OSError:
                    pass
                break
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.close(master)

    text = bytes(out).decode("utf-8", "replace")
    head, sep, result = text.partition("RESULT:")
    return (head if sep else text), (result.strip() if sep else "")


@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX-only")
@pytest.mark.parametrize(
    ("payload", "expected_result", "expected_stars", "secret"),
    [
        (b"secret123\n", "'secret123'", 9, b"secret123"),
        (b"pastedsecret456\n", "'pastedsecret456'", 15, b"pastedsecret456"),
        (b"ab\x7fc\n", "'ac'", 3, None),
        ("päö🔥\n".encode(), "'päö🔥'", 4, None),
        (b"\n", "''", 0, None),
    ],
    ids=["typed", "paste-block", "backspace", "unicode", "plain-enter"],
)
def test_masked_prompt_in_real_tty(
    payload: bytes, expected_result: str, expected_stars: int, secret: bytes | None
) -> None:
    head, result = _run_prompt_in_pty(payload)

    assert result == expected_result
    assert head.count("*") == expected_stars
    # Masking must actually be active — not the no-echo fallback.
    assert "asterisk masking is not supported" not in head
    # The plaintext must never be echoed by the terminal.
    if secret is not None:
        assert secret.decode() not in head


@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX-only")
def test_ctrl_c_in_real_tty_aborts_without_plaintext() -> None:
    head, result = _run_prompt_in_pty(b"abc\x03", hold=3, wait_for=b"***")

    assert result == "ERR:Abort"
    assert head.count("*") == 3
    assert "abc" not in head


@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX-only")
def test_ctrl_d_on_empty_in_real_tty_aborts() -> None:
    head, result = _run_prompt_in_pty(b"\x04")

    assert result == "ERR:Abort"
    assert head.count("*") == 0


@pytest.mark.skipif(os.name == "nt", reason="pty is POSIX-only")
def test_ctrl_d_after_input_in_real_tty_submits() -> None:
    head, result = _run_prompt_in_pty(b"abc\x04")

    assert result == "'abc'"
    assert head.count("*") == 3
