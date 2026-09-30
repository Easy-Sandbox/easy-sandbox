"""Shared coding-agent helpers for the ``create`` and ``deploy`` commands.

Both ``ebx create "<description>"`` and the agent-driven ``ebx deploy``
route drive the same pluggable backend
(:mod:`easy_sandbox.agent.coding_agent`): they must locate (or install)
the agent executable and resolve model credentials identically — same
prompts, same non-interactive behaviour, same error codes, same secret
handling.  This internal module is the single home of that front half of
the flow; the command modules keep the orchestration and the
user-facing composition around it.

Deliberate constraints (inherited from the sandbox command these helpers
were extracted from):

* the backend boundary is imported **lazily** inside each helper, so
  tests keep intercepting ``easy_sandbox.agent.coding_agent.*`` (and the
  implementation modules below it) unchanged;
* ``config_cmd`` imports stay function-local — this module must never
  import a sibling command module at import time, or the
  ``cli.commands`` import graph grows a cycle;
* every message is byte-identical to the previous sandbox-local helpers,
  so existing CLI goldens and assertions stay valid;
* secrets are never echoed: the interactive key prompt is hidden, only
  the config key name is reported (never the key itself), and the env
  variable name comes from the backend.

Nothing here is registered as a command; only the command
implementations that share these helpers import this module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import click

from easy_sandbox.cli.output import get_output

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from easy_sandbox.agent.coding_agent import (
        CodingAgentBackend,
        CodingAgentCredentials,
    )

__all__ = [
    "ensure_coding_agent_binary",
    "resolve_coding_agent_backend",
    "resolve_coding_agent_credentials",
]


def _print_quick_setup(out: Any, *, backend: CodingAgentBackend, reason: str) -> None:
    """Print the backend-provided Quick Setup for the AI template path.

    *reason* is ``"not-installed"`` or ``"no-credentials"``.
    """
    out.info("")
    for line in backend.quick_setup_lines(reason=reason):
        out.info(line)


def resolve_coding_agent_backend(name: str | None = None) -> CodingAgentBackend:
    """Instantiate the coding-agent backend selected by *name*.

    ``None`` (the default) selects the default backend — Qwen Code today.
    Unknown names raise :class:`ValueError`: nothing silently falls back
    to a different agent than the caller asked for.
    """
    from easy_sandbox.agent.coding_agent import resolve_coding_agent_backend as _resolve

    if name is None:
        # Preserve the original no-argument call shape, so tests that patch
        # the resolver keep asserting ``resolve_coding_agent_backend()``.
        return _resolve()
    return _resolve(name)


def ensure_coding_agent_binary(
    ctx: click.Context, *, yes: bool, backend: CodingAgentBackend
) -> Path:
    """Return a usable coding-agent executable, offering installation if missing.

    Interactive terminals are offered an automatic install of the official
    standalone build (SHA256-verified); non-interactive shells without
    ``--yes`` get the Quick Setup and a hard error instead of a hang.

    Raises:
        SandboxCreationError: ``backend.not_installed_error`` when the
            binary is missing and cannot (or must not) be installed.
    """
    binary = backend.find_binary()
    if binary is not None:
        return binary

    out = get_output(ctx)
    interactive = sys.stdin.isatty()
    out.warning(f"{backend.display_name} CLI was not found on PATH or in ~/.ebx/bin.")
    _print_quick_setup(out, backend=backend, reason="not-installed")

    not_installed = backend.not_installed_error
    if not yes and not interactive:
        raise not_installed(
            f"{backend.display_name} CLI is required for AI template generation "
            "but is not installed.",
            suggestion=(
                "Install it with the official command from Quick Setup above, then retry — "
                "or use 'ebx create --template <name>' to skip AI generation."
            ),
        )
    if interactive and not yes:
        proceed = click.confirm(
            f"Install the official {backend.display_name} standalone build into ~/.ebx/bin now?",
            default=True,
        )
        if not proceed:
            raise not_installed(
                f"Declined to install {backend.display_name}; AI template generation "
                "cannot continue.",
                suggestion=(
                    "Install it manually (see Quick Setup above) and retry, or use "
                    "'ebx create --template <name>'."
                ),
            )
    feed: list[str] = []
    live: list[Callable[[str], None] | None] = [None]

    def _note(message: str) -> None:
        # Milestones only (mirror name, checksum, extract). Never the URL
        # query, the archive bytes, or the credential env.
        cleaned = message.strip()
        if not cleaned:
            return
        update = live[0]
        if update is None:
            if out.verbose and not out.quiet and not out.json_mode:
                out.info(cleaned)
            return
        feed.append(cleaned)
        del feed[:-10]
        update("\n".join(feed))

    with out.activity(f"Installing {backend.display_name}", tick=True) as update:
        live[0] = update
        installed = backend.install(on_progress=_note)
    out.success(f"Installed {backend.display_name}: {installed}")
    return installed


def resolve_coding_agent_credentials(
    ctx: click.Context, *, yes: bool, backend: CodingAgentBackend
) -> CodingAgentCredentials:
    """Resolve coding-agent credentials, prompting once when allowed.

    Same order as ``ebx config list``: a process environment variable
    (``EBX_LLM_API_KEY``, then vendor ``BAILIAN_CODING_PLAN_API_KEY`` /
    ``DASHSCOPE_API_KEY`` / ``OPENAI_API_KEY``, then a legacy
    ``EBX_QWEN_CODE_API_KEY``) wins over the value stored in ~/.ebx.
    Endpoint and model follow that same env-then-file order. Without
    ``--yes`` and on an interactive terminal, one hidden prompt stores
    the entered key for future runs.

    Raises:
        SandboxCreationError: ``backend.credential_error`` when nothing
            usable is found (or the user declined / cancelled).
    """
    from easy_sandbox.cli.commands.config_cmd import (
        _effective_value,
        _remove_toml_key,
        write_env_var,
    )

    # Same resolution ``ebx config list`` uses. Process environment wins
    # over ~/.ebx; endpoint and model follow llm_* and fall back to a
    # previously stored qwen_code_* value. Built-in defaults are left
    # for the backend.
    stored_key, _key_source = _effective_value("llm_api_key")
    base_url, base_source = _effective_value(backend.base_url_config_key)
    model, model_source = _effective_value(backend.model_config_key)
    stored_base_url = None if base_source == "default" else base_url
    stored_model = None if model_source == "default" else model

    try:
        return backend.resolve_credentials(
            stored_api_key=stored_key,
            stored_base_url=stored_base_url,
            stored_model=stored_model,
        )
    except backend.credential_error:
        pass

    out = get_output(ctx)
    if yes or not sys.stdin.isatty():
        raise backend.credential_error(
            f"{backend.display_name} is installed but no model credentials were found.",
            suggestion=(
                f"Store a key with 'ebx config set {backend.config_key} <KEY>' (or export "
                "OPENAI_API_KEY / DASHSCOPE_API_KEY), then retry. Guided setup: "
                "'ebx config init'."
            ),
        )
    _print_quick_setup(out, backend=backend, reason="no-credentials")
    key = click.prompt(
        backend.credential_prompt,
        hide_input=True,
        default="",
        show_default=False,
    )
    if not key.strip():
        raise backend.credential_error(
            f"No {backend.display_name} API key provided; AI template generation cannot continue.",
            suggestion=(
                f"Store one with 'ebx config set {backend.config_key} <KEY>' and retry, "
                "or use 'ebx create --template <name>'."
            ),
        )
    write_env_var(backend.env_var, key.strip())
    # Same migration as `ebx config set llm_api_key`: drop any legacy
    # [transport] copy once the secure storage is written.
    _remove_toml_key("llm_api_key")
    out.success(f"Stored {backend.config_key} in ~/.ebx/.env")
    return backend.resolve_credentials(
        stored_api_key=key.strip(),
        stored_base_url=stored_base_url,
        stored_model=stored_model,
    )
