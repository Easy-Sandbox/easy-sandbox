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
# Lazy Group
# ---------------------------------------------------------------------------


class LazyGroup(click.Group):
    """Click group that lazily loads subcommands.

    Subcommands are registered as import paths and only loaded
    when actually invoked, keeping ``--help`` fast.
    """

    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_subcommands = lazy_subcommands or {}

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
                "(ebx config set api_key <KEY>).",
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

    if httpx is not None and isinstance(
        exc_val, (httpx.ConnectError, httpx.NetworkError)
    ):
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
    lazy_subcommands={
        "create": "easy_sandbox.cli.commands.sandbox:create",
        "list": "easy_sandbox.cli.commands.sandbox:list_cmd",
        "info": "easy_sandbox.cli.commands.sandbox:info",
        "kill": "easy_sandbox.cli.commands.sandbox:kill",
        "exec": "easy_sandbox.cli.commands.sandbox:exec_cmd",
        "connect": "easy_sandbox.cli.commands.sandbox:connect",
        "sandbox": "easy_sandbox.cli.commands.sandbox:sandbox",
        "config": "easy_sandbox.cli.commands.config_cmd:config",
        "mcp": "easy_sandbox.cli.commands.mcp:mcp",
        "template": "easy_sandbox.cli.commands.template:template",
        "install": "easy_sandbox.cli.commands.template:install_shortcut",
        "init": "easy_sandbox.cli.commands.template:init_shortcut",
        "upload": "easy_sandbox.cli.commands.sandbox:upload",
        "download": "easy_sandbox.cli.commands.sandbox:download",
        "run": "easy_sandbox.cli.commands.sandbox:run_cmd",
        "deploy": "easy_sandbox.cli.commands.deploy:deploy_shortcut",
    },
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
@click.option("--timeout", "-t", type=int, default=300, help="Default timeout in seconds")
@click.option("--region", "-r", default=None, help="Region (default: cn-hangzhou)")
@click.option("--profile", "-p", default=None, help="[预留] Configuration profile")
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
    region: str | None,
    profile: str | None,
) -> None:
    """ebx — Easy Sandbox CLI

    Create, manage, and interact with cloud sandboxes.
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
    ctx.obj["region"] = region
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
