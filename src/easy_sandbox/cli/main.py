"""ebx CLI — command-line interface for Easy Sandbox.

Uses lazy loading to keep ``ebx --help`` fast (< 200 ms).
Heavy imports only happen when a command actually executes.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import click

# ---------------------------------------------------------------------------
# Command registry & shortcuts
# ---------------------------------------------------------------------------

# Core command groups — always registered, cannot be overridden by shortcuts
_CORE_COMMANDS: dict[str, str] = {
    "sandbox": "easy_sandbox.cli.commands.sandbox:sandbox",
    "config": "easy_sandbox.cli.commands.config_cmd:config",
    "mcp": "easy_sandbox.cli.commands.mcp:mcp",
    "template": "easy_sandbox.cli.commands.template:template",
}

# Reserved names that user shortcuts cannot override
RESERVED_NAMES: frozenset[str] = frozenset(_CORE_COMMANDS)

# Default shortcuts: alias → human-readable target string.
# Used by ``config_cmd`` when generating the default ``~/.ebx/config.toml``
# only. At runtime the config file is the single source of truth — these
# values are never merged in implicitly.
_DEFAULT_SHORTCUTS: dict[str, str] = {
    "create": "sandbox create",
    "list": "sandbox list",
    "info": "sandbox info",
    "kill": "sandbox kill",
    "exec": "sandbox exec",
    "connect": "sandbox connect",
    "upload": "sandbox upload",
    "download": "sandbox download",
    "run": "sandbox run",
    "install": "template install",
    # Same click.Command object as 'ebx template init' (task 211); the option
    # surface and scaffolding logic are shared, nothing is duplicated.
    "init": "template init",
    "deploy": "deploy",
}

# All valid shortcut targets: human-readable string → module:attr import path.
# This includes both default-enabled and additional commands users can enable.
_SHORTCUT_TARGET_MAP: dict[str, str] = {
    "sandbox create": "easy_sandbox.cli.commands.sandbox:create",
    "sandbox list": "easy_sandbox.cli.commands.sandbox:list_cmd",
    "sandbox info": "easy_sandbox.cli.commands.sandbox:info",
    "sandbox kill": "easy_sandbox.cli.commands.sandbox:kill",
    "sandbox exec": "easy_sandbox.cli.commands.sandbox:exec_cmd",
    "sandbox connect": "easy_sandbox.cli.commands.sandbox:connect",
    "sandbox upload": "easy_sandbox.cli.commands.sandbox:upload",
    "sandbox download": "easy_sandbox.cli.commands.sandbox:download",
    "sandbox run": "easy_sandbox.cli.commands.sandbox:run_cmd",
    "template install": "easy_sandbox.cli.commands.template:install_shortcut",
    "template init": "easy_sandbox.cli.commands.template:init",
    "deploy": "easy_sandbox.cli.commands.deploy:deploy_shortcut",
    # Additional commands (not enabled by default, users can enable via config)
    "sandbox files list": "easy_sandbox.cli.commands.sandbox_files:files_list",
    "sandbox process list": "easy_sandbox.cli.commands.sandbox_process:process_list",
    "sandbox system info": "easy_sandbox.cli.commands.sandbox_system:system_info",
    "template build": "easy_sandbox.cli.commands.template:build",
    "template search": "easy_sandbox.cli.commands.template:search",
}


def _describe_invalid_shortcut_target(target: str, *, alias: str | None = None) -> str:
    """Explain an unrecognized shortcut target in plain language.

    The stored value is the command path only (``template init``), never the
    full invocation (``ebx template init``). A leading ``ebx`` is called out
    on its own; when dropping it leaves a real target, the text includes the
    command to retry. Any other value gets the same rule plus the target
    list, grouped by command.
    """
    normalized = " ".join(target.split())
    head, _, rest = normalized.partition(" ")
    dropped_ebx = head.lower() == "ebx"
    stripped = rest if dropped_ebx else None

    if stripped and stripped in _SHORTCUT_TARGET_MAP:
        lines = [
            'Drop the leading "ebx". The target is the command path only, '
            f'for example "{stripped}".'
        ]
        if alias:
            lines.append(f'Try: ebx config set shortcuts.{alias} "{stripped}"')
        return "\n".join(lines)

    if dropped_ebx and stripped:
        lead = (
            'Drop the leading "ebx". '
            f'"{stripped}" is not a command path. '
            'Use a path such as "template init".'
        )
    elif dropped_ebx:
        lead = (
            'Drop the leading "ebx". The target is the command path only, '
            'for example "template init".'
        )
    else:
        lead = 'Use the command path without the "ebx" prefix, for example "template init".'
    return lead + "\n" + _format_shortcut_targets()


def _format_shortcut_targets() -> str:
    """Render valid shortcut targets grouped by their first word."""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for name in sorted(_SHORTCUT_TARGET_MAP):
        group, _, tail = name.partition(" ")
        if group not in groups:
            groups[group] = []
            order.append(group)
        if tail:
            groups[group].append(tail)
    lines = ["Available targets:"]
    for group in order:
        tails = groups[group]
        if tails:
            lines.append(f"  {group}: {', '.join(tails)}")
        else:
            lines.append(f"  {group}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lazy Group
# ---------------------------------------------------------------------------


class LazyGroup(click.Group):
    """Click group that lazily loads subcommands.

    Subcommands are registered as import paths and only loaded
    when actually invoked, keeping ``--help`` fast.

    When ``merge_shortcuts`` is enabled (root CLI group only), the user
    shortcuts configured in ``~/.ebx/config.toml`` are merged in as well.
    """

    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, str] | None = None,
        merge_shortcuts: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_subcommands = lazy_subcommands or {}
        if merge_shortcuts:
            self._merge_user_shortcuts()

    def _merge_user_shortcuts(self) -> None:
        """Merge the user-configured shortcuts into lazy subcommands.

        ``~/.ebx/config.toml`` is the single source of truth: on a fresh
        install the default config file is created first, then the
        ``[shortcuts]`` section is honoured as-is — remapped or deleted
        defaults included, there is no implicit fallback to the built-in
        defaults. A corrupted config only disables shortcuts (with a stderr
        warning): the core command groups keep working, the CLI never breaks.
        """
        try:
            from easy_sandbox.cli.commands.config_cmd import (
                _config_file_exists,
                _create_default_config,
                load_shortcuts,
            )

            if not _config_file_exists():
                # Fresh install: materialise the default config file so the
                # shortcut list always has a single, inspectable source.
                _create_default_config()

            shortcuts = load_shortcuts()

            for alias, target in shortcuts.items():
                if alias in RESERVED_NAMES:
                    click.echo(
                        f"⚠ Warning: Shortcut '{alias} = \"{target}\"' conflicts with "
                        f"built-in command '{alias}', ignored.",
                        err=True,
                    )
                    continue
                if alias in _CORE_COMMANDS:
                    continue  # Already registered as core command
                import_path = _SHORTCUT_TARGET_MAP.get(target)
                if import_path is None:
                    hint = _describe_invalid_shortcut_target(target, alias=alias)
                    detail = "\n".join(f"  {line}" for line in hint.splitlines())
                    click.echo(
                        f"⚠ Warning: Invalid shortcut ignored: '{alias} = \"{target}\"' "
                        f"in ~/.ebx/config.toml\n"
                        f"{detail}",
                        err=True,
                    )
                    continue
                self._lazy_subcommands[alias] = import_path
        except Exception as exc:
            # Corrupted config (or missing config helpers): warn and keep
            # going without shortcuts — the CLI must never break.
            click.echo(
                f"⚠ Warning: Failed to load shortcuts from config: {exc}\n"
                "  Shortcuts are unavailable for this session; the built-in "
                "commands (sandbox/config/mcp/template) still work.\n"
                "  Options:\n"
                "    • Fix manually: edit ~/.ebx/config.toml\n"
                "    • Reset config: ebx config init (re-run guided setup)\n"
                "    • Reset shortcuts only: ebx config init --reset-shortcuts",
                err=True,
            )

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(self._lazy_subcommands.keys())
        return base + lazy

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name in self._lazy_subcommands:
            return self._load_command(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _load_command(self, cmd_name: str) -> click.Command:
        import importlib

        module_path = self._lazy_subcommands[cmd_name]
        # format: "easy_sandbox.cli.commands.sandbox:create"
        mod_path, attr_name = module_path.rsplit(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr_name)  # type: ignore[no-any-return]

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str, click.Command, list[str]]:
        """Enrich the unknown-top-level-command error with a targeted hint.

        * A high-confidence spelling candidate (difflib, cutoff 0.6) gets
          only a "Did you mean" correction suggestion.
        * With no plausible candidate, the user is pointed to template
          ``custom_commands`` (declared in template.yaml and invoked via
          ``ebx run COMMAND``) and to a shortcut example whose target is the
          command path without the ``ebx`` prefix
          (``ebx config set shortcuts.NAME "template init"``).

        Contract preserved: Click ``UsageError`` semantics — exit code 2,
        message on stderr. Only the root group is affected.
        """
        try:
            cmd_name, cmd, cmd_args = super().resolve_command(ctx, args)
        except click.UsageError:
            # Only the root group gets the hint; nested groups keep the
            # stock Click message.
            if ctx.parent is not None or not args:
                raise
            import difflib

            cmd_name = args[0]
            candidates = difflib.get_close_matches(
                cmd_name, self.list_commands(ctx), n=3, cutoff=0.6
            )
            if candidates:
                hint = "Did you mean " + ", ".join(f"'{c}'" for c in candidates) + "?"
            else:
                hint = (
                    "No similar command. "
                    'To add a shortcut, use the command path without the "ebx" '
                    "prefix, for example: "
                    'ebx config set shortcuts.NAME "template init". '
                    "A custom command inside a sandbox is declared in "
                    "template.yaml (custom_commands) and run with "
                    "'ebx run COMMAND'."
                )
            raise click.UsageError(f"No such command '{cmd_name}'. {hint}", ctx) from None
        assert cmd is not None and cmd_name is not None
        return cmd_name, cmd, cmd_args


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_TIMEOUT = 5
EXIT_QUOTA = 6


F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Decorator that catches SandboxError and remote exceptions, mapping to exit codes."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except SystemExit:
            raise
        except click.exceptions.Exit:
            raise
        except click.Abort:
            raise
        except Exception:
            # Lazy import so that --help is still fast
            import sys as _sys

            from easy_sandbox.models.errors import (
                AuthenticationError,
                CommandTimeoutError,
                FileNotFoundError_,
                QuotaExceededError,
                SandboxError,
                TemplateNotFoundError,
            )

            exc_type, exc_val, _ = _sys.exc_info()

            # Determine formatter (best-effort)
            from easy_sandbox.cli.formatters import OutputFormatter

            ctx = click.get_current_context(silent=True)
            obj = (ctx.obj if ctx else None) or {}
            fmt = OutputFormatter(
                use_json=obj.get("json", False),
                quiet=obj.get("quiet", False),
                no_color=obj.get("no_color", False),
            )

            if isinstance(exc_val, AuthenticationError):
                fmt.print_error(
                    exc_val.message,
                    code=exc_val.code,
                    suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_AUTH)
            elif isinstance(exc_val, (TemplateNotFoundError, FileNotFoundError_)):
                fmt.print_error(
                    exc_val.message,
                    code=exc_val.code,
                    suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_NOT_FOUND)
            elif isinstance(exc_val, CommandTimeoutError):
                fmt.print_error(
                    exc_val.message,
                    code=exc_val.code,
                    suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_TIMEOUT)
            elif isinstance(exc_val, QuotaExceededError):
                fmt.print_error(
                    exc_val.message,
                    code=exc_val.code,
                    suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_QUOTA)
            elif isinstance(exc_val, SandboxError):
                fmt.print_error(
                    exc_val.message,
                    code=exc_val.code,
                    suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_GENERAL)
            else:
                # --- Remote / network exceptions (BUG-04) ---
                _handle_remote_exception(exc_val, fmt)

    return wrapper  # type: ignore[return-value]


def _handle_remote_exception(
    exc_val: BaseException | None,
    fmt: Any,
) -> None:
    """Map non-SandboxError remote exceptions to friendly CLI messages.

    Catches httpx HTTP status errors, timeouts, connection errors,
    built-in FileNotFoundError / OSError, and asyncio timeouts so the
    user never sees a raw traceback.
    """
    import sys as _sys

    # httpx errors (optional import — only present when httpx is installed)
    try:
        import httpx
    except ImportError:  # pragma: no cover
        httpx = None  # type: ignore[assignment]

    if httpx is not None and isinstance(exc_val, httpx.HTTPStatusError):
        status = exc_val.response.status_code
        if status == 401:
            fmt.print_error(
                f"Authentication failed (HTTP {status}).",
                code="E1000",
                suggestion="Check your API key or AK/SK credentials "
                "(ebx config set sandbox_api_key <KEY>).",
            )
            _sys.exit(EXIT_AUTH)
        elif status == 404:
            fmt.print_error(
                f"Resource not found (HTTP {status}).",
                code="E5000",
                suggestion="Verify the sandbox ID, template ID, or endpoint URL.",
            )
            _sys.exit(EXIT_NOT_FOUND)
        elif status == 403:
            fmt.print_error(
                f"Access denied (HTTP {status}).",
                code="E1000",
                suggestion="Check your credentials and permissions.",
            )
            _sys.exit(EXIT_AUTH)
        elif status == 429:
            fmt.print_error(
                f"Rate limit exceeded (HTTP {status}).",
                code="E2002",
                suggestion="Wait a moment and retry, or request a quota increase.",
            )
            _sys.exit(EXIT_QUOTA)
        else:
            fmt.print_error(
                f"Remote request failed (HTTP {status}): {exc_val}",
                code="E5000",
                suggestion="Check the platform status and retry. "
                "Use 'ebx -v <command>' for details.",
            )
            _sys.exit(EXIT_GENERAL)

    if httpx is not None and isinstance(
        exc_val, (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout)
    ):
        fmt.print_error(
            f"Request timed out: {exc_val}",
            code="E3001",
            suggestion=(
                "The HTTP request timed out. Try:\n"
                "  1. Increase HTTP timeout: ebx config set http_timeout 120\n"
                "  2. Or set env: export SANDBOX_HTTP_TIMEOUT=120\n"
                "  3. Check network connectivity"
            ),
        )
        _sys.exit(EXIT_TIMEOUT)

    if httpx is not None and isinstance(exc_val, (httpx.ConnectError, httpx.NetworkError)):
        fmt.print_error(
            f"Connection error: {exc_val}",
            code="E5001",
            suggestion="Check network connectivity and firewall rules. "
            "Verify the platform URL is correct.",
        )
        _sys.exit(EXIT_GENERAL)

    if httpx is not None and isinstance(exc_val, httpx.ProtocolError):
        # HTTP/2 StreamReset, peer closing the connection mid-response, etc.
        # (httpx.RemoteProtocolError is a subclass of ProtocolError.)
        fmt.print_error(
            f"Connection reset by remote: {exc_val}",
            code="E5003",
            suggestion=(
                "The platform closed the connection before responding. This usually "
                "means the operation took too long (e.g., sandbox cold start). Try:\n"
                "  1. Increase HTTP timeout: ebx config set http_timeout 120\n"
                "  2. Retry the command\n"
                "  3. Disable HTTP/2: ebx config set http2 false"
            ),
        )
        _sys.exit(EXIT_GENERAL)

    # asyncio.TimeoutError (e.g. from create -T timeout)
    import asyncio

    if isinstance(exc_val, (asyncio.TimeoutError, TimeoutError)):
        fmt.print_error(
            "Operation timed out.",
            code="E3001",
            suggestion=(
                "The operation exceeded its time limit. Try:\n"
                "  1. Increase HTTP timeout: ebx config set http_timeout 120\n"
                "  2. Or set env: export SANDBOX_HTTP_TIMEOUT=120\n"
                "  3. Check if the service is responding"
            ),
        )
        _sys.exit(EXIT_TIMEOUT)

    # Built-in FileNotFoundError (e.g. install with bad path)
    if isinstance(exc_val, FileNotFoundError):
        fmt.print_error(
            f"File or directory not found: {exc_val}",
            code="E4001",
            suggestion="Verify the path exists and is accessible.",
        )
        _sys.exit(EXIT_NOT_FOUND)

    # Built-in OSError (e.g. permission issues)
    if isinstance(exc_val, OSError):
        fmt.print_error(
            f"OS error: {exc_val}",
            suggestion="Check file permissions and disk space.",
        )
        _sys.exit(EXIT_GENERAL)

    # click.ClickException (pass through message cleanly)
    if isinstance(exc_val, click.ClickException):
        fmt.print_error(exc_val.format_message())
        _sys.exit(EXIT_GENERAL)

    # Last resort: unknown exception → friendly message
    fmt.print_error(
        f"Unexpected error: {exc_val}",
        suggestion="Use 'ebx -v <command>' for more details, or report this issue.",
    )
    _sys.exit(EXIT_GENERAL)


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------


@click.group(
    cls=LazyGroup,
    invoke_without_command=True,
    # Single source of truth for the ``-h`` alias: Click inherits
    # ``help_option_names`` from the parent Context down the whole command
    # tree (lazy groups, nested sub-groups and leaf commands), so setting it
    # once here makes ``-h`` work everywhere without per-command wiring.
    # Commands that define a ``-h`` parameter of their own are protected by
    # Click's built-in conflict guard (the alias is dropped for that command,
    # ``--help`` keeps working) — user parameters are never shadowed.
    context_settings={"help_option_names": ["-h", "--help"]},
    # Core command groups are always registered; the top-level shortcuts are
    # merged dynamically from ``~/.ebx/config.toml`` by ``LazyGroup``.
    lazy_subcommands=dict(_CORE_COMMANDS),
    merge_shortcuts=True,
)
@click.option("--json", "-j", "output_json", is_flag=True, help="Output as JSON")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output (DEBUG level)")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="Set log level explicitly",
)
@click.option("--ci", is_flag=True, help="CI/CD mode (quiet + no-color + json)")
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=300,
    help="Default sandbox lifetime in seconds (positive integer; default: 300)",
)
@click.option("--profile", "-p", default=None, help="[Reserved] Configuration profile")
@click.version_option(package_name="easy-sandbox")
@click.pass_context
def cli(
    ctx: click.Context,
    output_json: bool,
    quiet: bool,
    verbose: bool,
    no_color: bool,
    log_level: str | None,
    ci: bool,
    timeout: int,
    profile: str | None,
) -> None:
    """ebx — Easy Sandbox CLI

    Create, manage, and interact with cloud sandboxes.

    \b
    Setup, create, or scaffold:
      ebx config init               Guided credentials setup (run first)
      ebx create [DESCRIPTION]      Create a cloud sandbox (AI or --template)
      ebx template init [DIR]       Scaffold a local template project

    \b
    Examples:
      ebx create --template base
      ebx list --status running
      ebx template search python

    \b
    Related commands:
      ebx config --help    Configure credentials and endpoints
      ebx sandbox --help   Manage sandbox lifecycle and resources
      ebx template --help  Discover, build, and deploy templates
    """
    # Lazy import to keep --help fast
    from easy_sandbox.cli.output import OutputManager, is_ci_env

    # Auto-detect CI environment
    effective_ci = ci or is_ci_env()

    output = OutputManager(
        verbose=verbose,
        quiet=quiet,
        json_mode=output_json or effective_ci,
        no_color=no_color or effective_ci,
        ci=effective_ci,
        log_level=log_level,
    )

    ctx.ensure_object(dict)
    # Store OutputManager in ctx.meta (not ctx.obj) so that
    # ctx.obj stays JSON-serializable for existing tests / debug.
    ctx.meta["ebx.output"] = output
    # Backward-compatible context keys (used by get_formatter / handle_errors)
    ctx.obj["json"] = output.json_mode
    ctx.obj["quiet"] = output.quiet
    ctx.obj["verbose"] = output.verbose
    ctx.obj["no_color"] = output.no_color
    ctx.obj["timeout"] = timeout
    ctx.obj["profile"] = profile
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def main() -> None:
    """Entry point for the CLI."""
    cli()


# ---------------------------------------------------------------------------
# install shortcut (top-level)
# ---------------------------------------------------------------------------
# Defined here but loaded lazily via the LazyGroup.
# The actual implementation is in cli/commands/template.py.


if __name__ == "__main__":
    main()
