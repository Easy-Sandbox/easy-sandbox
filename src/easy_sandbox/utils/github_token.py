"""GitHub token guidance shared by the template utilities and the CLI.

Task 206 — safe, fast guidance when an anonymous GitHub rate limit is hit:

* One canonical remedy for both the registry tarball client
  (:mod:`easy_sandbox.utils.registry`) and the template-index client
  (:mod:`easy_sandbox.utils.template_index`) — see
  :func:`rate_limit_message` / :func:`rate_limit_suggestion`.
* The persistent ``ebx config set github_token`` flow is the recommended
  fix (masked input, stored in ``~/.ebx/.env``, reused automatically).
  The explicit ``--token`` flag keeps working as a temporary override but
  is documented as leak-prone (shell history / process list).
* :data:`FINE_GRAINED_PAT_URL` is GitHub's officially documented pre-filled
  fine-grained PAT form.  ``contents=read`` implicitly grants the required
  ``metadata:read`` and public repositories need no other permissions; a
  90-day lifetime is pre-selected.

Security posture: nothing in this module ever reads ``gh auth token``,
opens a browser, or prints / logs a token value.
"""

from __future__ import annotations

__all__ = [
    "FINE_GRAINED_PAT_URL",
    "GITHUB_TOKEN_CONFIG_KEY",
    "GITHUB_TOKEN_ENV_VAR",
    "rate_limit_message",
    "rate_limit_suggestion",
]

#: Environment variable GitHub itself uses, and the env var mapped to the
#: persistent ``github_token`` config key.
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"

#: Config key for ``ebx config set github_token`` (stored in ``~/.ebx/.env``
#: under :data:`GITHUB_TOKEN_ENV_VAR`).
GITHUB_TOKEN_CONFIG_KEY = "github_token"

#: Officially documented URL that opens GitHub's "new fine-grained personal
#: access token" form with the fields pre-filled: read-only repository
#: contents access, a 90-day lifetime, and a descriptive name.
#:
#: Verified against GitHub docs, "Pre-filling fine-grained personal access
#: token details using URL parameters": supported parameters are ``name``,
#: ``description``, ``target_name``, ``expires_in`` (1-366 days or ``none``)
#: and ``<permission>=read|write|admin``.  ``contents=read`` also selects
#: ``metadata:read``.  Public repositories need no extra permissions.
FINE_GRAINED_PAT_URL = (
    "https://github.com/settings/personal-access-tokens/new"
    "?name=ebx-template-token"
    "&description=Read-only+access+for+ebx+template+installs"
    "&expires_in=90"
    "&contents=read"
)


def rate_limit_message(*, operation: str = "") -> str:
    """Return the unified anonymous-rate-limit headline.

    Args:
        operation: optional short phrase naming what was being fetched
            (e.g. ``"fetching the template index"``); the tarball client
            uses the base sentence without it.
    """
    where = f" while {operation}" if operation else ""
    return f"GitHub API rate limit exceeded{where} (anonymous requests are limited to 60/hour)."


def rate_limit_suggestion(*, extra: str = "") -> str:
    """Return the unified remediation for an anonymous rate limit.

    Recommends the persistent ``ebx config set github_token`` flow first
    (interactive, masked input), points at the officially verified
    fine-grained PAT prefill URL (public repositories need no extra
    permissions; 90-day lifetime recommended), keeps ``--token`` as an
    explicit temporary override with a leak warning, and covers
    non-TTY / CI sessions by pointing at secret injection.

    Args:
        extra: optional extra sentence appended last (e.g. the mirror hint
            of the template-index client).
    """
    parts = [
        "Authenticate to raise the limit to 5000/hour: run "
        "'ebx config set github_token' in an interactive terminal "
        "(masked input; stored in ~/.ebx/.env and reused automatically).",
        "Create a fine-grained token here - public repositories need no "
        "extra permissions and a 90-day expiry is recommended: "
        f"{FINE_GRAINED_PAT_URL}",
        "In CI / non-interactive sessions, inject GITHUB_TOKEN as a secret "
        "instead. The explicit '--token <value>' flag also works but may "
        "leak into shell history and process listings.",
    ]
    if extra:
        parts.append(extra)
    return " ".join(parts)
