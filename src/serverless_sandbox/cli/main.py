"""sbox CLI — command-line interface for Serverless Sandbox.

Uses lazy loading to keep ``sbox --help`` fast (< 200 ms).
Heavy imports only happen when a command actually executes.
"""
from __future__ import annotations

import functools
from typing import Any

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
        # format: "serverless_sandbox.cli.commands.sandbox:create"
        mod_path, attr_name = module_path.rsplit(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr_name)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_AUTH = 3
EXIT_NOT_FOUND = 4
EXIT_TIMEOUT = 5
EXIT_QUOTA = 6


def handle_errors(func):  # noqa: ANN001,ANN201
    """Decorator that catches SandboxError and maps to exit codes."""

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
            # Re-import the original exception to test against
            import sys as _sys

            from serverless_sandbox.models.errors import (
                AuthenticationError,
                CommandTimeoutError,
                FileNotFoundError_,
                QuotaExceededError,
                SandboxError,
                TemplateNotFoundError,
            )

            exc_type, exc_val, _ = _sys.exc_info()

            # Determine formatter (best-effort)
            from serverless_sandbox.cli.formatters import OutputFormatter

            ctx = click.get_current_context(silent=True)
            obj = (ctx.obj if ctx else None) or {}
            fmt = OutputFormatter(
                use_json=obj.get("json", False),
                quiet=obj.get("quiet", False),
                no_color=obj.get("no_color", False),
            )

            if isinstance(exc_val, AuthenticationError):
                fmt.print_error(
                    exc_val.message, code=exc_val.code, suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_AUTH)
            elif isinstance(exc_val, (TemplateNotFoundError, FileNotFoundError_)):
                fmt.print_error(
                    exc_val.message, code=exc_val.code, suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_NOT_FOUND)
            elif isinstance(exc_val, CommandTimeoutError):
                fmt.print_error(
                    exc_val.message, code=exc_val.code, suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_TIMEOUT)
            elif isinstance(exc_val, QuotaExceededError):
                fmt.print_error(
                    exc_val.message, code=exc_val.code, suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_QUOTA)
            elif isinstance(exc_val, SandboxError):
                fmt.print_error(
                    exc_val.message, code=exc_val.code, suggestion=exc_val.suggestion,
                )
                _sys.exit(EXIT_GENERAL)
            else:
                # Not a SandboxError — let it propagate
                raise

    return wrapper


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group(
    cls=LazyGroup,
    invoke_without_command=True,
    lazy_subcommands={
        "create": "serverless_sandbox.cli.commands.sandbox:create",
        "list": "serverless_sandbox.cli.commands.sandbox:list_cmd",
        "info": "serverless_sandbox.cli.commands.sandbox:info",
        "kill": "serverless_sandbox.cli.commands.sandbox:kill",
        "exec": "serverless_sandbox.cli.commands.sandbox:exec_cmd",
        "connect": "serverless_sandbox.cli.commands.sandbox:connect",
        "sandbox": "serverless_sandbox.cli.commands.sandbox:sandbox",
        "config": "serverless_sandbox.cli.commands.config_cmd:config",
        "mcp": "serverless_sandbox.cli.commands.mcp:mcp",
        "template": "serverless_sandbox.cli.commands.template:template",
        "install": "serverless_sandbox.cli.commands.template:install_shortcut",
        "upload": "serverless_sandbox.cli.commands.sandbox:upload",
        "download": "serverless_sandbox.cli.commands.sandbox:download",
        "run": "serverless_sandbox.cli.commands.sandbox:run_cmd",
        "deploy": "serverless_sandbox.cli.commands.deploy:deploy_shortcut",
        "session": "serverless_sandbox.cli.commands.session:session",
        "secret": "serverless_sandbox.cli.commands.secret:secret",
        "skill": "serverless_sandbox.cli.commands.skill:skill",
        "auth": "serverless_sandbox.cli.commands.auth:auth",
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
@click.version_option(package_name="serverless-sandbox")
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
    """sbox — Serverless Sandbox CLI

    Create, manage, and interact with cloud sandboxes.
    """
    # Lazy import to keep --help fast
    from serverless_sandbox.cli.output import OutputManager, is_ci_env

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
    ctx.meta["sbox.output"] = output
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
