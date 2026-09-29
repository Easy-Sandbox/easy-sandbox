"""Shared command-level ``--region`` option and resolution.

``region`` is not a global CLI switch (unlike ``--json``/``--quiet``/``--verbose``):
only commands that actually talk to a regional control plane, the template
pipeline (ACR / FC), or MCP deployment accept it.

Resolution priority (implemented once in :func:`easy_sandbox.transport.config.load_config`
via its override mechanism, reused by every command):

1. Command ``--region/-r`` value
2. ``ebx config set region <value>`` (persisted in ``~/.ebx/config.toml``)
   or the ``SANDBOX_REGION`` environment variable
3. Default ``cn-hangzhou``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from collections.abc import Callable

#: Fallback region when nothing is configured.
DEFAULT_REGION = "cn-hangzhou"

_REGION_HELP = (
    "Region override for this command (default: 'ebx config set region' value, else cn-hangzhou)"
)


def region_option(func: Callable[..., Any]) -> Callable[..., Any]:
    """Attach the shared command-level ``--region/-r`` option.

    The callback receives the value as the ``region`` keyword argument
    (``None`` when the user did not pass the flag, which then falls back to
    the configured/persisted region).
    """
    return click.option(
        "--region",
        "-r",
        "region",
        default=None,
        metavar="TEXT",
        help=_REGION_HELP,
    )(func)


def resolve_region(cli_region: str | None) -> str:
    """Return the effective region for a command invocation.

    Priority: command ``--region`` > ``ebx config set region`` /
    ``SANDBOX_REGION`` env > ``cn-hangzhou``.  Commands that build the full
    transport config should instead call
    ``load_config(region=cli_region)`` directly — the same priority applies.
    """
    from easy_sandbox.transport.config import load_config

    return load_config(region=cli_region).region
