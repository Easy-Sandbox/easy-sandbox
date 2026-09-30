""".dockerignore matcher (Docker / BuildKit semantics).

``ebx template init --adopt`` must know whether a file such as ``.env`` would
be sent to ``docker build`` — ``.gitignore`` is irrelevant, the build context
is the whole directory minus the ignore file.  This module reimplements the
documented matching rules so the check needs no Docker daemon:

* one pattern per line; blank lines and ``#`` comments are skipped;
* patterns are **root-anchored** (a bare ``.env`` matches only ``./.env``;
  use ``**/.env`` for every directory);
* ``*`` and ``?`` never cross ``/``; ``**`` matches any number of directories;
  ``[...]`` is a character class; ``\\`` escapes;
* a pattern that matches a directory also excludes everything below it;
* a leading ``!`` re-includes, and the **last** matching line wins.

Fail closed: a line this matcher cannot compile is recorded in
:attr:`DockerIgnore.unparseable`.  An unparseable *exclusion* excludes nothing;
an unparseable *re-include* makes :meth:`DockerIgnore.excludes` answer
``False`` for every path, i.e. "assume it would be sent".
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["DockerIgnore"]


@dataclass(frozen=True)
class _Rule:
    regex: re.Pattern[str]
    negate: bool


def _translate(pattern: str) -> str:
    """Translate one cleaned ignore pattern into a regex source (no anchors)."""
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        at_segment_start = i == 0 or pattern[i - 1] == "/"
        if ch == "*" and pattern[i : i + 2] == "**" and at_segment_start:
            after = pattern[i + 2 : i + 3]
            if after == "/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if after == "":
                out.append(".*")
                i += 2
                continue
        if ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "\\":
            if i + 1 >= n:
                raise ValueError("dangling escape")
            out.append(re.escape(pattern[i + 1]))
            i += 2
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                raise ValueError("unterminated character class")
            body = pattern[i + 1 : j]
            if body[:1] in ("!", "^"):
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = j + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


@dataclass
class DockerIgnore:
    """Compiled ignore rules for one build context."""

    rules: tuple[_Rule, ...] = ()
    unparseable: tuple[str, ...] = ()
    _distrust: bool = field(default=False, repr=False)

    @classmethod
    def from_text(cls, text: str) -> DockerIgnore:
        rules: list[_Rule] = []
        bad: list[str] = []
        distrust = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:].strip()
            line = posixpath.normpath(line) if line not in ("", ".") else ""
            line = line.lstrip("/")
            if not line or line == ".":
                # A pattern that names the context root itself: not meaningful.
                if negate:
                    bad.append(raw.strip())
                    distrust = True
                continue
            try:
                regex = re.compile("^" + _translate(line) + "$")
            except (ValueError, re.error):
                bad.append(raw.strip())
                if negate:
                    distrust = True
                continue
            rules.append(_Rule(regex, negate))
        return cls(tuple(rules), tuple(bad), distrust)

    @classmethod
    def from_file(cls, path: Path) -> DockerIgnore:
        return cls.from_text(path.read_text(encoding="utf-8", errors="replace"))

    @property
    def has_negation(self) -> bool:
        """Whether any ``!`` line exists (directory pruning is then unsafe)."""
        return self._distrust or any(rule.negate for rule in self.rules)

    def excludes(self, rel_path: str) -> bool:
        """Return whether *rel_path* (POSIX, relative to the context) is ignored.

        ``True`` means Docker would not send the file.  Any doubt answers
        ``False``.
        """
        if self._distrust:
            return False
        path = posixpath.normpath(rel_path.replace("\\", "/")).lstrip("/")
        if path in ("", "."):
            return False
        parts = path.split("/")
        prefixes = ["/".join(parts[: k + 1]) for k in range(len(parts))]
        ignored = False
        for rule in self.rules:
            # Docker skips a rule unless it can flip the current state.
            if rule.negate != ignored:
                continue
            if any(rule.regex.match(prefix) for prefix in prefixes):
                ignored = not rule.negate
        return ignored
