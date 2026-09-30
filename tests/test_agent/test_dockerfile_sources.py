"""Tests for the minimal COPY/ADD source extractor."""

from __future__ import annotations

from easy_sandbox.agent.dockerfile_sources import CopySource, parse_copy_sources


def _sources(text: str) -> list[tuple[str, str]]:
    return [(c.instruction, c.source) for c in parse_copy_sources(text)]


def test_plain_copy_and_add() -> None:
    text = "FROM x\nCOPY app.py .\nADD lib/ /opt/lib/\n"
    assert _sources(text) == [("COPY", "app.py"), ("ADD", "lib/")]


def test_multiple_sources_last_operand_is_the_destination() -> None:
    assert _sources("COPY a b c /dst/\n") == [("COPY", "a"), ("COPY", "b"), ("COPY", "c")]


def test_instruction_is_case_insensitive() -> None:
    assert _sources("copy a /b\n") == [("COPY", "a")]


def test_flags_are_dropped() -> None:
    text = "COPY --chown=app:app --chmod=755 src/ /app/src/\n"
    assert _sources(text) == [("COPY", "src/")]


def test_from_copies_are_skipped() -> None:
    text = "COPY --from=builder /out/app /app\nCOPY --from builder /x /y\nCOPY real.txt /r\n"
    assert _sources(text) == [("COPY", "real.txt")]


def test_json_form() -> None:
    text = 'COPY ["my file.txt", "other.txt", "/dst/"]\n'
    assert _sources(text) == [("COPY", "my file.txt"), ("COPY", "other.txt")]


def test_broken_json_falls_back_to_shell_form() -> None:
    assert _sources("COPY [a.txt /dst/\n") == [("COPY", "[a.txt")]


def test_urls_are_not_context_paths() -> None:
    text = "ADD https://example.com/x.tgz /x.tgz\nADD git@github.com:o/r.git /r\nADD local.tgz /l\n"
    assert _sources(text) == [("ADD", "local.tgz")]


def test_line_continuation_and_comment_inside() -> None:
    text = "COPY a.py \\\n  # a comment\n  b.py \\\n  /dst/\n"
    assert _sources(text) == [("COPY", "a.py"), ("COPY", "b.py")]


def test_custom_escape_directive() -> None:
    text = "# escape=`\nFROM x\nCOPY a.py `\n  /dst/\n"
    assert _sources(text) == [("COPY", "a.py")]


def test_heredoc_body_is_never_parsed_as_instructions() -> None:
    text = "RUN <<EOF\nCOPY fake.txt /x\nEOF\nCOPY real.txt /r\n"
    assert _sources(text) == [("COPY", "real.txt")]


def test_copy_with_heredoc_is_skipped() -> None:
    text = "COPY <<EOF /etc/conf\nkey=value\nEOF\nCOPY real.txt /r\n"
    assert _sources(text) == [("COPY", "real.txt")]


def test_onbuild_is_ignored() -> None:
    assert _sources("ONBUILD COPY a /b\n") == []


def test_kinds_and_line_numbers() -> None:
    text = "FROM x\n\nCOPY a.py $DIR/ *.whl /tmp/\n"
    result = parse_copy_sources(text)
    assert result == [
        CopySource("COPY", "a.py", 3, "literal"),
        CopySource("COPY", "$DIR/", 3, "variable"),
        CopySource("COPY", "*.whl", 3, "glob"),
    ]


def test_single_operand_is_ignored() -> None:
    assert _sources("COPY lonely\n") == []
