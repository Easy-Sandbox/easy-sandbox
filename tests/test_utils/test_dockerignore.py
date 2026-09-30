"""Tests for the .dockerignore matcher (Docker root-anchored semantics)."""

from __future__ import annotations

import pytest

from easy_sandbox.utils.dockerignore import DockerIgnore


def _ex(text: str, path: str) -> bool:
    return DockerIgnore.from_text(text).excludes(path)


class TestBasics:
    def test_empty_file_excludes_nothing(self) -> None:
        assert _ex("", ".env") is False

    def test_comments_and_blank_lines_are_skipped(self) -> None:
        assert _ex("# .env\n\n   \n", ".env") is False

    def test_bare_name_is_root_anchored(self) -> None:
        # The classic pitfall: ``.env`` does not match ``sub/.env``.
        assert _ex(".env", ".env") is True
        assert _ex(".env", "sub/.env") is False

    def test_double_star_prefix_matches_every_directory(self) -> None:
        for path in (".env", "a/.env", "a/b/.env"):
            assert _ex("**/.env", path) is True

    def test_leading_slash_and_dot_slash_are_normalised(self) -> None:
        assert _ex("/.env", ".env") is True
        assert _ex("./.env", ".env") is True

    def test_trailing_slash_names_a_directory(self) -> None:
        assert _ex("secrets/", "secrets/key.txt") is True

    def test_parent_match_excludes_children(self) -> None:
        assert _ex("build", "build/out/app.js") is True

    def test_windows_separators_in_query_are_accepted(self) -> None:
        assert _ex("secrets", "secrets\\key.txt") is True


class TestGlobs:
    @pytest.mark.parametrize(
        ("pattern", "path", "expected"),
        [
            ("*.pem", "key.pem", True),
            ("*.pem", "sub/key.pem", False),  # * never crosses /
            ("**/*.pem", "sub/deep/key.pem", True),
            (".env.*", ".env.local", True),
            (".env.*", ".env", False),
            ("?.txt", "a.txt", True),
            ("?.txt", "ab.txt", False),
            ("[ab].txt", "a.txt", True),
            ("[!ab].txt", "a.txt", False),
            ("[!ab].txt", "c.txt", True),
            ("a/**/z", "a/z", True),
            ("a/**/z", "a/b/c/z", True),
            ("a/**", "a/b/c", True),
            (r"\!file", "!file", True),
        ],
    )
    def test_patterns(self, pattern: str, path: str, expected: bool) -> None:
        assert _ex(pattern, path) is expected


class TestNegation:
    def test_reinclude_after_exclude(self) -> None:
        text = "*.md\n!README.md\n"
        assert _ex(text, "CHANGELOG.md") is True
        assert _ex(text, "README.md") is False

    def test_last_matching_line_wins(self) -> None:
        assert _ex("!.env\n.env\n", ".env") is True
        assert _ex(".env\n!.env\n", ".env") is False

    def test_allow_list_style(self) -> None:
        text = "*\n!src\n"
        assert _ex(text, "src/main.py") is False
        assert _ex(text, ".env") is True

    def test_reinclude_inside_excluded_directory(self) -> None:
        text = "secrets\n!secrets/public.txt\n"
        assert _ex(text, "secrets/key.txt") is True
        assert _ex(text, "secrets/public.txt") is False

    def test_reinclude_can_bring_a_secret_back(self) -> None:
        # ``!`` lines are how a hand-written ignore file silently leaks.
        assert _ex("**/.env\n!.env\n", ".env") is False


class TestFailClosed:
    def test_unterminated_class_in_exclusion_excludes_nothing(self) -> None:
        ig = DockerIgnore.from_text("[abc\n")
        assert ig.unparseable == ("[abc",)
        assert ig.excludes("a") is False

    def test_unparseable_reinclude_distrusts_everything(self) -> None:
        ig = DockerIgnore.from_text("**/.env\n![oops\n")
        assert ig.unparseable == ("![oops",)
        assert ig.excludes(".env") is False

    def test_dangling_escape_is_unparseable(self) -> None:
        assert DockerIgnore.from_text("abc\\\n").unparseable

    def test_root_and_empty_paths_are_never_excluded(self) -> None:
        ig = DockerIgnore.from_text("*\n")
        assert ig.excludes("") is False
        assert ig.excludes(".") is False


def test_from_file(tmp_path) -> None:
    f = tmp_path / ".dockerignore"
    f.write_text("**/.env\n", encoding="utf-8")
    assert DockerIgnore.from_file(f).excludes("a/.env") is True
