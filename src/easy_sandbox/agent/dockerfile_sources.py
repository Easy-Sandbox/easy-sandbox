"""Minimal ``COPY`` / ``ADD`` source extraction from a Dockerfile.

``ebx template init --adopt`` validates AI-written Dockerfiles *before*
``docker build`` runs for minutes.  The check that matters most is "does every
path the Dockerfile copies actually exist in the build context?".  This
module extracts those source paths; deciding whether they exist is the
caller's job.

Scope is deliberately small and stated:

* handled: ``# escape=`` directive, line continuations, comments inside a
  continuation, shell and JSON forms, ``--chown/--chmod/--link/--parents/
  --exclude/--keep-git-dir/--checksum`` style flags (dropped);
* skipped (never a source): ``--from=`` copies, ``ONBUILD``, URL sources,
  heredoc instructions and their bodies;
* classified rather than resolved: sources with ``$VAR`` are ``variable``
  (build args are unknown), sources with ``* ? [`` are ``glob``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

__all__ = ["CopySource", "parse_copy_sources"]

SourceKind = Literal["literal", "glob", "variable"]

_HEREDOC_RE = re.compile(r"<<(-?)\s*([\"']?)([A-Za-z_][A-Za-z0-9_]*)\2")
_URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|git@)", re.IGNORECASE)
_DIRECTIVE_RE = re.compile(r"^#\s*escape\s*=\s*(\S)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class CopySource:
    """One source operand of a ``COPY``/``ADD`` instruction."""

    instruction: str
    """``"COPY"`` or ``"ADD"``."""

    source: str
    line: int
    """1-based line of the instruction's first physical line."""

    kind: SourceKind


def _escape_char(lines: list[str]) -> str:
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            break
        match = _DIRECTIVE_RE.match(stripped)
        if match:
            return match.group(1)
        if not stripped.startswith("#"):
            break
    return "\\"


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join continuations; return ``(first_line_number, instruction_text)``."""
    lines = text.splitlines()
    esc = _escape_char(lines)
    result: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        start = i + 1
        buf = raw.rstrip()
        while buf.endswith(esc) and i + 1 < len(lines):
            buf = buf[: -len(esc)]
            i += 1
            nxt = lines[i]
            if nxt.strip().startswith("#") or not nxt.strip():
                # Comments / blanks inside a continuation are dropped, and the
                # continuation carries on (BuildKit behaviour).
                buf += " "
                buf = buf.rstrip() + esc
                continue
            buf += nxt.rstrip()
        buf = buf[: -len(esc)] if buf.endswith(esc) else buf
        result.append((start, buf.strip()))
        i += 1
        # Consume heredoc bodies so their lines are not parsed as instructions.
        for match in _HEREDOC_RE.finditer(buf):
            dash, _quote, delim = match.groups()
            while i < len(lines):
                body = lines[i].lstrip("\t") if dash else lines[i]
                i += 1
                if body.strip("\r") == delim:
                    break
    return result


def _split_flags(args: str) -> tuple[list[str], str]:
    flags: list[str] = []
    rest = args.lstrip()
    while rest.startswith("--"):
        token, _, remainder = rest.partition(" ")
        flags.append(token)
        rest = remainder.lstrip()
    return flags, rest


def _classify(source: str) -> SourceKind:
    if "$" in source:
        return "variable"
    if any(ch in source for ch in "*?["):
        return "glob"
    return "literal"


def parse_copy_sources(text: str) -> list[CopySource]:
    """Return every source operand of every ``COPY``/``ADD`` in *text*."""
    found: list[CopySource] = []
    for line_no, logical in _logical_lines(text):
        head, _, args = logical.partition(" ")
        instruction = head.upper()
        if instruction not in ("COPY", "ADD"):
            continue
        if _HEREDOC_RE.search(args):
            continue
        flags, rest = _split_flags(args)
        if any(flag.lower().startswith("--from") for flag in flags):
            continue
        operands: list[str]
        if rest.startswith("["):
            try:
                loaded = json.loads(rest)
            except json.JSONDecodeError:
                operands = rest.split()
            else:
                operands = [str(item) for item in loaded] if isinstance(loaded, list) else []
        else:
            operands = rest.split()
        if len(operands) < 2:
            continue
        for source in operands[:-1]:
            if _URL_RE.match(source):
                continue
            found.append(CopySource(instruction, source, line_no, _classify(source)))
    return found
