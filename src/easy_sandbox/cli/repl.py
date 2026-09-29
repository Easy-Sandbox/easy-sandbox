"""Interactive REPL helpers for ``ebx connect``.

``ebx connect`` is deliberately a *line-based* command REPL — not a PTY and
not an SSH session: every entered line is executed as its own process and no
shell state survives between lines.  This module owns the two behaviours
that are specific to that loop:

* :func:`enable_line_editing` — activates the stdlib ``readline`` module for
  the builtin :func:`input` when the session is interactive, so Up/Down
  history, Ctrl+R search and the usual editing keys work.
* :func:`describe_command_failure` — maps whatever ``commands.run()`` raised
  to a *single* friendly ``(message, suggestion)`` pair.  Transport text is
  sanitised (never the full sandbox URL or an MDN status link) and
  ``EnvdRpcError.envd_error`` is mined for the executable envd could not
  start, so a command-not-found is reported with the real command name.

Spelling hints are only produced from commands that already ran in this
session — a guess about what a remote image happens to install would not be
reliable, so no such guess is made.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import shlex
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from easy_sandbox.models.errors import CommandTimeoutError, EnvdRpcError, SandboxError

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "REPL_TIMEOUT",
    "CommandFailure",
    "describe_command_failure",
    "enable_line_editing",
    "program_name",
    "sanitize_text",
]

#: Wall-clock limit applied to every REPL line; ``ebx exec --timeout``
#: accepts larger values for long-running commands.
REPL_TIMEOUT = 30

#: Short form used inside suggestions (the real sandbox id would be noise).
_EXEC_HINT = "ebx exec <SANDBOX_ID>"

_STATUS_HINT = "Check the sandbox status with 'ebx info <SANDBOX_ID>' and retry."

_MAX_MESSAGE_LEN = 240

#: Shell builtins have no standalone executable, so envd reports them as
#: "not found" even though the shell supports them.
_SHELL_BUILTINS = frozenset(
    {
        "alias",
        "bg",
        "cd",
        "dirs",
        "disown",
        "eval",
        "exec",
        "export",
        "fc",
        "fg",
        "hash",
        "history",
        "jobs",
        "local",
        "popd",
        "pushd",
        "read",
        "set",
        "shopt",
        "source",
        "trap",
        "typeset",
        "ulimit",
        "umask",
        "unalias",
        "unset",
        "wait",
    }
)


# ---------------------------------------------------------------------------
# Line editing
# ---------------------------------------------------------------------------


def enable_line_editing() -> bool:
    """Enable readline-backed line editing for ``input()`` when possible.

    Returns ``True`` when the stdlib ``readline`` module was imported for an
    interactive stdin.  Non-interactive sessions (pipes, CI, test runners)
    keep the plain ``input()`` behaviour, and platforms without ``readline``
    (e.g. bare Windows Python) degrade gracefully instead of failing.
    """
    stdin = getattr(sys, "stdin", None)
    isatty = getattr(stdin, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    try:
        import readline  # noqa: F401  (import side effect enables editing)
    except ImportError:  # pragma: no cover - platform without readline
        return False
    return True


def program_name(command: str) -> str:
    """Return the first token of *command* (the program that would run)."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    return parts[0] if parts else ""


# ---------------------------------------------------------------------------
# Sanitising
# ---------------------------------------------------------------------------

#: httpx appends "For more information check: https://developer.mozilla.org/…"
#: to status errors; drop the whole clause, URL included. Requiring the URL
#: keeps legitimate prose like "check the logs" intact.
_MDN_CLAUSE_RE = re.compile(r"\s*For more information check:?\s*https?://\S*", re.IGNORECASE)
#: Also swallows the surrounding quotes so a scrubbed URL leaves no stray ``'``.
_URL_RE = re.compile(r"""['"]?https?://[^\s'"]+['"]?""")


def sanitize_text(text: str) -> str:
    """Remove sandbox URLs / MDN links from *text* and collapse whitespace."""
    cleaned = _MDN_CLAUSE_RE.sub("", text or "")
    cleaned = _URL_RE.sub("", cleaned)
    cleaned = cleaned.replace("''", "").replace('""', "")
    return " ".join(cleaned.split())


def _clip(text: str, limit: int = _MAX_MESSAGE_LEN) -> str:
    """Truncate long remote details so one failure stays one short line."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


# ---------------------------------------------------------------------------
# envd error mining
# ---------------------------------------------------------------------------

_NOT_FOUND_MARKERS = ("not found", "no such file", "cannot find", "not installed")

_MISSING_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""exec:\s*["']?([^"'\s:]+)["']?"""),
    re.compile(r"([^\s:]+):\s*(?:command\s+)?not found", re.IGNORECASE),
    re.compile(r"([^\s:]+):\s*executable file not found", re.IGNORECASE),
    re.compile(r"not found:\s*([^\s:]+)", re.IGNORECASE),
)

_NOT_NAMES = frozenset({"exec", "found", "in", "not", "the", "$path"})


def _envd_detail(exc: EnvdRpcError) -> str:
    """Best-effort human detail from the structured envd error body.

    Mirrors the shapes the transport accepts: nested ``{"error": {...}}``,
    flat ``{"message": ...}`` and plain string errors.
    """
    err = exc.envd_error
    if isinstance(err, dict):
        inner = err.get("error")
        if isinstance(inner, dict):
            for key in ("message", "msg", "detail"):
                value = inner.get(key)
                if isinstance(value, str) and value:
                    return value
        elif isinstance(inner, str) and inner:
            return inner
        for key in ("message", "msg", "detail"):
            value = err.get(key)
            if isinstance(value, str) and value:
                return value
    return exc.body_text or ""


def _missing_command(exc: EnvdRpcError, typed: str) -> str:
    """Name of the executable envd could not start, or ``""``.

    Prefers the structured error body (``EnvdRpcError.envd_error``); falls
    back to the executable the user actually typed when envd reports a
    not-found without naming it (e.g. ``"exec not found"``).
    """
    detail = _envd_detail(exc) or exc.message
    lowered = detail.lower()
    if not any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return ""
    for pattern in _MISSING_NAME_PATTERNS:
        match = pattern.search(detail)
        if match:
            name = match.group(1).strip("\"'` ")
            if name and name.lower() not in _NOT_NAMES:
                return name
    return program_name(typed)


# ---------------------------------------------------------------------------
# Spelling hints (session-verified commands only)
# ---------------------------------------------------------------------------


def _one_edit_away(candidate: str, name: str) -> bool:
    """Return ``True`` for a single substitution, insertion, deletion or
    adjacent transposition between *candidate* and *name*."""
    if candidate == name or abs(len(candidate) - len(name)) > 1:
        return False
    if len(candidate) == len(name):
        diff = [i for i in range(len(name)) if name[i] != candidate[i]]
        if len(diff) == 1:
            return True
        return (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and name[diff[0]] == candidate[diff[1]]
            and name[diff[1]] == candidate[diff[0]]
        )
    shorter, longer = (name, candidate) if len(name) < len(candidate) else (candidate, name)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def _spell_suggestion(name: str, known: Iterable[str]) -> str:
    """Closest session-verified command name, or ``""`` when not confident."""
    candidates = sorted({c for c in known if c and c != name})
    if not name or not candidates:
        return ""
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.7)
    if matches:
        return matches[0]
    near = [c for c in candidates if _one_edit_away(name, c)]
    if near:
        return min(near, key=lambda c: (abs(len(c) - len(name)), len(c)))
    return ""


# ---------------------------------------------------------------------------
# Failure description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandFailure:
    """A single friendly failure notice for one REPL command."""

    message: str
    suggestion: str = ""
    code: str = ""


def _timeout_failure(timeout: int) -> CommandFailure:
    return CommandFailure(
        message=f"Command timed out after {timeout}s.",
        suggestion=(
            f"Each REPL line has a {timeout}s limit - use "
            f"'{_EXEC_HINT} \"<cmd>\" --timeout N' for long-running commands."
        ),
        code="E3001",
    )


def _missing_suggestion(name: str, known: Iterable[str]) -> str:
    if name == "cd":
        return (
            "'cd' is a shell builtin and needs a shell: use 'cd /path && <cmd>' on one line, "
            f"or '{_EXEC_HINT} \"<cmd>\" --cwd /path'."
        )
    if name in _SHELL_BUILTINS:
        return (
            f"'{name}' is a shell builtin with no standalone executable; shell state "
            "(working directory, environment variables, aliases) does not persist between lines."
        )
    spell = _spell_suggestion(name, known)
    if spell:
        return f"Did you mean '{spell}'? It ran earlier in this session."
    return f"Check that '{name}' exists in the sandbox image - each line runs in its own process."


def _envd_failure(
    exc: EnvdRpcError,
    *,
    command: str,
    known_commands: Iterable[str],
) -> CommandFailure:
    missing = _missing_command(exc, command)
    if missing:
        return CommandFailure(
            message=f"Command not found: {missing}",
            suggestion=_missing_suggestion(missing, known_commands),
            code=exc.code,
        )
    detail = _clip(sanitize_text(_envd_detail(exc)))
    status = f" (HTTP {exc.status_code})" if exc.status_code else ""
    message = f"Sandbox envd rejected the command{status}"
    if detail:
        message = f"{message}: {detail}"
    return CommandFailure(
        message=message,
        suggestion=sanitize_text(exc.suggestion),
        code=exc.code,
    )


def describe_command_failure(
    exc: BaseException,
    *,
    command: str,
    timeout: int = REPL_TIMEOUT,
    known_commands: Iterable[str] = (),
) -> CommandFailure:
    """Map a REPL command failure to one friendly ``(message, suggestion)``.

    ``known_commands`` are executables observed to run in this session; they
    are the *only* source used for "did you mean" hints, so a suggestion is
    never based on a guess about the sandbox image.
    """
    if isinstance(exc, EnvdRpcError):
        return _envd_failure(exc, command=command, known_commands=known_commands)
    if isinstance(exc, (CommandTimeoutError, httpx.TimeoutException, asyncio.TimeoutError)):
        return _timeout_failure(timeout)
    if isinstance(exc, httpx.HTTPStatusError):
        return CommandFailure(
            message=f"Remote request failed (HTTP {exc.response.status_code}).",
            suggestion=_STATUS_HINT,
            code="E5000",
        )
    if isinstance(exc, httpx.ProtocolError):
        detail = _clip(sanitize_text(str(exc)))
        message = "Connection to the sandbox was interrupted"
        if detail:
            message = f"{message}: {detail}"
        return CommandFailure(
            message=message,
            suggestion=(
                "The sandbox may have stopped or hit its lifetime limit - "
                "check 'ebx info <SANDBOX_ID>' and retry."
            ),
            code="E5003",
        )
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        detail = _clip(sanitize_text(str(exc)))
        message = "Cannot reach the sandbox envd"
        if detail:
            message = f"{message}: {detail}"
        return CommandFailure(message=message, suggestion=_STATUS_HINT, code="E5001")
    if isinstance(exc, httpx.HTTPError):
        detail = _clip(sanitize_text(str(exc))) or type(exc).__name__
        return CommandFailure(message=f"Sandbox request failed: {detail}", suggestion=_STATUS_HINT)
    if isinstance(exc, SandboxError):
        return CommandFailure(
            message=_clip(sanitize_text(exc.message)) or type(exc).__name__,
            suggestion=sanitize_text(exc.suggestion),
            code=exc.code,
        )
    detail = _clip(sanitize_text(str(exc))) or type(exc).__name__
    return CommandFailure(
        message=f"Unexpected error while running this line: {detail}",
        suggestion="Run 'ebx -v connect <SANDBOX_ID>' for DEBUG diagnostics.",
    )
