"""密钥管理 CLI 命令。"""
from __future__ import annotations

import sys

import click

from easy_sandbox.cli.formatters import get_formatter
from easy_sandbox.cli.main import handle_errors


@click.group()
@click.pass_context
def secret(ctx: click.Context) -> None:
    """密钥管理。安全存储和注入 API Key、Token 等敏感信息。"""
    ctx.ensure_object(dict)


@secret.command("create")
@click.argument("name")
@click.option("--value", prompt=True, hide_input=True, confirmation_prompt=True,
              help="密钥值（交互式安全输入）")
@click.pass_context
@handle_errors
def create(ctx: click.Context, name: str, value: str) -> None:
    """创建密钥。值通过安全提示输入。"""
    from easy_sandbox.utils.keychain import SecretStore

    fmt = get_formatter(ctx)
    store = SecretStore()
    store.set(name, value)

    if fmt.use_json:
        fmt.print_data({"name": name, "status": "created"})
    else:
        fmt.print_success(f"Secret {name!r} created.")


@secret.command("list")
@click.pass_context
@handle_errors
def list_secrets(ctx: click.Context) -> None:
    """列出所有密钥（只显示名称，不显示值）。"""
    from easy_sandbox.utils.keychain import SecretStore

    fmt = get_formatter(ctx)
    store = SecretStore()
    names = store.list_names()

    if not names:
        fmt.print_success("No secrets found.")
        return

    if fmt.use_json:
        fmt.print_data({"secrets": names})
    else:
        headers = ["Name"]
        rows = [[n] for n in names]
        fmt.print_table(headers, rows)


@secret.command("delete")
@click.argument("name")
@click.confirmation_option(prompt="确认删除？")
@click.pass_context
@handle_errors
def delete(ctx: click.Context, name: str) -> None:
    """删除密钥。"""
    from easy_sandbox.utils.keychain import SecretStore

    fmt = get_formatter(ctx)
    store = SecretStore()
    deleted = store.delete(name)

    if deleted:
        if fmt.use_json:
            fmt.print_data({"name": name, "status": "deleted"})
        else:
            fmt.print_success(f"Secret {name!r} deleted.")
    else:
        fmt.print_error(f"Secret {name!r} not found.")
        sys.exit(1)


@secret.command("inject")
@click.argument("sandbox_id")
@click.option("--secret", "-s", "secret_names", multiple=True, required=True,
              help="要注入的密钥名称（可多次指定）")
@click.pass_context
@handle_errors
def inject(ctx: click.Context, sandbox_id: str, secret_names: tuple[str, ...]) -> None:
    """将密钥注入到沙箱环境变量中。"""
    from easy_sandbox.api.sandbox import Sandbox
    from easy_sandbox.utils.async_bridge import run_sync
    from easy_sandbox.utils.keychain import SecretStore

    fmt = get_formatter(ctx)
    store = SecretStore()

    # 读取所有需要注入的密钥
    envs: dict[str, str] = {}
    missing: list[str] = []
    for sn in secret_names:
        val = store.get(sn)
        if val is None:
            missing.append(sn)
        else:
            envs[sn] = val

    if missing:
        fmt.print_error(f"Secrets not found: {', '.join(missing)}")
        sys.exit(1)

    # 通过沙箱 API 设置环境变量
    sandbox = run_sync(Sandbox.connect(sandbox_id))
    for key, value in envs.items():
        run_sync(sandbox.commands.run(f"export {key}={value}"))

    injected = list(envs.keys())
    if fmt.use_json:
        fmt.print_data({
            "sandbox_id": sandbox_id,
            "injected": injected,
        })
    else:
        fmt.print_success(
            f"Injected {len(injected)} secret(s) into sandbox {sandbox_id}: "
            + ", ".join(injected)
        )
