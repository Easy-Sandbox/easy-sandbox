"""Tests for command-level ``--region`` options and the unified priority.

Covers the region-as-command-option design (task 159):

* the root ``ebx`` group no longer accepts ``--region/-r``;
* regional commands (``list``/``kill``, the ``template`` control plane, and
  ``mcp deploy``) accept a local ``--region`` and forward it to
  ``load_config`` / ``resolve_region``;
* priority everywhere: command ``--region`` > ``SANDBOX_REGION`` env /
  ``ebx config set region`` (``~/.ebx/config.toml``) > default
  ``cn-hangzhou``;
* purely local commands reject ``--region`` with the standard Click error;
* the ``template deploy`` alias and the top-level ``install`` / ``deploy``
  shortcuts expose/forward ``--region`` like the commands they delegate to;
* ``mcp deploy`` no longer has its own hardcoded default — it shares the
  same resolution semantics as every other regional command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from easy_sandbox.cli.main import cli
from easy_sandbox.cli.region import resolve_region
from easy_sandbox.transport import config as transport_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _combined_output(result: Any) -> str:
    """Return stdout+stderr across Click runner versions."""
    try:
        return (result.output or "") + (result.stderr or "")
    except ValueError:  # Click < 8.5 mixes stderr into output
        return result.output or ""


@pytest.fixture
def runner() -> CliRunner:
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def isolated_region_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point every transport-config source at a tmp dir for determinism.

    Patches the config.toml / .env candidates inside the transport config
    module and removes all region-relevant environment variables, then
    resets the module-level config cache.
    """
    monkeypatch.setattr(transport_config, "_CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(transport_config, "_ENV_FILE_CANDIDATES", [tmp_path / ".env"])
    for var in (
        "SANDBOX_REGION",
        "E2B_API_KEY",
        "E2B_API_URL",
        "SANDBOX_API_KEY",
        "SANDBOX_API_BASE_URL",
        "ALICLOUD_ACCESS_KEY_ID",
        "ALICLOUD_ACCESS_KEY_SECRET",
        "AccessKey",
        "AccessSecret",
        "EBX_MCP_AUTH_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    transport_config.reset_config()
    yield tmp_path
    transport_config.reset_config()


# ---------------------------------------------------------------------------
# Root option removal
# ---------------------------------------------------------------------------


class TestRootOptionRemoved:
    """The root ``ebx`` group must not expose a global --region."""

    def test_root_help_has_no_region(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--region" not in result.output

    def test_old_global_region_fails_with_click_error(self, runner: CliRunner) -> None:
        """``ebx --region ... list`` now fails with the standard Click error."""
        result = runner.invoke(cli, ["--region", "cn-shanghai", "list"])
        assert result.exit_code == 2
        assert "No such option" in _combined_output(result)

    def test_old_global_short_flag_fails(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["-r", "cn-shanghai", "list"])
        assert result.exit_code == 2
        assert "No such option" in _combined_output(result)


# ---------------------------------------------------------------------------
# Which commands expose --region
# ---------------------------------------------------------------------------

_REGIONAL_COMMANDS: list[list[str]] = [
    ["list", "--help"],
    ["kill", "--help"],
    ["sandbox", "list", "--help"],
    ["sandbox", "kill", "--help"],
    ["template", "list", "--help"],
    ["template", "info", "--help"],
    ["template", "create", "--help"],
    ["template", "push", "--help"],
    ["template", "build", "--help"],
    ["template", "install", "--help"],
    ["template", "delete", "--help"],
    ["template", "deploy", "--help"],  # alias inherits build's params
    ["install", "--help"],  # top-level shortcut
    ["deploy", "--help"],  # top-level shortcut of the template build pipeline
    ["mcp", "deploy", "--help"],
]

_LOCAL_COMMANDS: list[list[str]] = [
    ["create", "--help"],
    ["exec", "--help"],
    ["connect", "--help"],
    ["upload", "--help"],
    ["download", "--help"],
    ["run", "--help"],
    ["config", "--help"],
    ["template", "search", "--help"],
    ["template", "init", "--help"],
    ["mcp", "start", "--help"],
    ["mcp", "install", "--help"],
    ["mcp", "status", "--help"],
    ["sandbox", "create", "--help"],
    ["sandbox", "files", "--help"],
]


class TestRegionOptionPlacement:
    """Only commands that talk to a regional control plane accept --region."""

    @pytest.mark.parametrize("argv", _REGIONAL_COMMANDS)
    def test_regional_command_help_shows_region(self, runner: CliRunner, argv: list[str]) -> None:
        result = runner.invoke(cli, argv)
        assert result.exit_code == 0, result.output
        assert "--region" in result.output, f"{argv} should expose --region"

    @pytest.mark.parametrize("argv", _LOCAL_COMMANDS)
    def test_local_command_help_hides_region(self, runner: CliRunner, argv: list[str]) -> None:
        result = runner.invoke(cli, argv)
        assert result.exit_code == 0, result.output
        assert "--region" not in result.output, f"{argv} must not expose --region"

    @pytest.mark.parametrize(
        "argv",
        [
            ["create", "--template", "base", "--region", "cn-shanghai"],
            ["exec", "sbx-1", "true", "--region", "cn-shanghai"],
            ["connect", "sbx-1", "--region", "cn-shanghai"],
            ["config", "--region", "cn-shanghai"],
            ["template", "search", "python", "--region", "cn-shanghai"],
            ["template", "init", "--region", "cn-shanghai"],
            ["mcp", "start", "--region", "cn-shanghai"],
            ["mcp", "status", "--region", "cn-shanghai"],
            ["mcp", "install", "--target", "cursor", "--region", "cn-shanghai"],
        ],
    )
    def test_local_command_rejects_region_flag(self, runner: CliRunner, argv: list[str]) -> None:
        """Passing --region to a purely local command is a usage error."""
        result = runner.invoke(cli, argv)
        assert result.exit_code == 2
        assert "No such option" in _combined_output(result)


# ---------------------------------------------------------------------------
# Region reaches the transport config (spy on load_config)
# ---------------------------------------------------------------------------


class TestRegionReachesTransportConfig:
    """Command --region must be forwarded to load_config / the HTTP client."""

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["list", "--region", "cn-shanghai"], "cn-shanghai"),
            (["list", "-r", "cn-shenzhen"], "cn-shenzhen"),
            (["list"], None),
            (["sandbox", "list", "--region", "cn-shanghai"], "cn-shanghai"),
        ],
    )
    def test_list_forwards_region_to_load_config(
        self, runner: CliRunner, argv: list[str], expected: str | None
    ) -> None:
        with (
            patch("easy_sandbox.transport.config.load_config") as load_cfg,
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient"),
            patch("easy_sandbox.protocol.sandbox.SandboxProtocol"),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, argv)
        assert result.exit_code == 0, result.output
        assert load_cfg.call_args.kwargs.get("region") == expected

    def test_kill_all_forwards_region_to_load_config(self, runner: CliRunner) -> None:
        with (
            patch("easy_sandbox.transport.config.load_config") as load_cfg,
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient"),
            patch("easy_sandbox.protocol.sandbox.SandboxProtocol"),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, ["kill", "--all", "--yes", "--region", "cn-shanghai"])
        assert result.exit_code == 0, result.output
        assert load_cfg.call_args.kwargs.get("region") == "cn-shanghai"

    def test_template_list_forwards_region_to_load_config(self, runner: CliRunner) -> None:
        with (
            patch("easy_sandbox.transport.config.load_config") as load_cfg,
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient"),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, ["template", "list", "--region", "cn-shanghai"])
        assert result.exit_code == 0, result.output
        assert load_cfg.call_args.kwargs.get("region") == "cn-shanghai"

    def test_sandbox_list_command_region_reaches_http_client(
        self, runner: CliRunner, isolated_region_env: Path
    ) -> None:
        """End-to-end: command --region wins over a persisted config value."""
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        with (
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient") as http_cls,
            patch("easy_sandbox.protocol.sandbox.SandboxProtocol"),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, ["list", "--region", "cn-shanghai"])
        assert result.exit_code == 0, result.output
        config_arg = http_cls.call_args.args[0]
        assert config_arg.region == "cn-shanghai"

    def test_sandbox_list_falls_back_to_config_file(
        self, runner: CliRunner, isolated_region_env: Path
    ) -> None:
        """Without --region the persisted config value is used."""
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        with (
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient") as http_cls,
            patch("easy_sandbox.protocol.sandbox.SandboxProtocol"),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0, result.output
        config_arg = http_cls.call_args.args[0]
        assert config_arg.region == "cn-beijing"

    def test_template_list_default_region(
        self, runner: CliRunner, isolated_region_env: Path
    ) -> None:
        """Without any configuration the default cn-hangzhou is used."""
        with (
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient") as http_cls,
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, ["template", "list"])
        assert result.exit_code == 0, result.output
        config_arg = http_cls.call_args.args[0]
        assert config_arg.region == "cn-hangzhou"


# ---------------------------------------------------------------------------
# resolve_region priority (shared helper)
# ---------------------------------------------------------------------------


class TestResolveRegionPriority:
    """Command > env / config file > default, implemented once for all commands."""

    def test_cli_region_beats_config_file(self, isolated_region_env: Path) -> None:
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        assert resolve_region("cn-shanghai") == "cn-shanghai"

    def test_config_file_fallback(self, isolated_region_env: Path) -> None:
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        assert resolve_region(None) == "cn-beijing"

    def test_env_var_fallback(
        self, isolated_region_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        assert resolve_region(None) == "cn-shenzhen"

    def test_cli_region_beats_env_var(
        self, isolated_region_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        assert resolve_region("cn-shanghai") == "cn-shanghai"

    def test_env_var_beats_config_file(
        self, isolated_region_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        assert resolve_region(None) == "cn-shenzhen"

    def test_default_when_nothing_configured(self, isolated_region_env: Path) -> None:
        assert resolve_region(None) == "cn-hangzhou"


# ---------------------------------------------------------------------------
# mcp deploy no longer has a second region semantic
# ---------------------------------------------------------------------------


class TestMcpDeployRegionSemantics:
    """``mcp deploy`` shares the unified region priority (no hardcoded default)."""

    @staticmethod
    def _deploy(runner: CliRunner, tmp_path: Path, *extra: str) -> dict[str, Any]:
        out = tmp_path / "artifact"
        with patch(
            "easy_sandbox.cli.commands.mcp._read_api_key",
            return_value="k",
        ):
            result = runner.invoke(
                cli,
                ["mcp", "deploy", "--output-dir", str(out), "--generate-token", *extra],
            )
        assert result.exit_code == 0, result.output
        return yaml.safe_load((out / "config.yaml").read_text())

    def test_cli_region_overrides_config_file(
        self, runner: CliRunner, isolated_region_env: Path
    ) -> None:
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        cfg = self._deploy(runner, isolated_region_env, "--region", "cn-shanghai")
        assert cfg["region"] == "cn-shanghai"

    def test_falls_back_to_config_file(self, runner: CliRunner, isolated_region_env: Path) -> None:
        (isolated_region_env / "config.toml").write_text('[transport]\nregion = "cn-beijing"\n')
        cfg = self._deploy(runner, isolated_region_env)
        assert cfg["region"] == "cn-beijing"

    def test_falls_back_to_env_var(
        self, runner: CliRunner, isolated_region_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        cfg = self._deploy(runner, isolated_region_env)
        assert cfg["region"] == "cn-shenzhen"

    def test_default_region(self, runner: CliRunner, isolated_region_env: Path) -> None:
        """No flag, no config, no env → cn-hangzhou."""
        cfg = self._deploy(runner, isolated_region_env)
        assert cfg["region"] == "cn-hangzhou"

    def test_explicit_region_still_wins_over_env(
        self, runner: CliRunner, isolated_region_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        cfg = self._deploy(runner, isolated_region_env, "--region", "cn-shanghai")
        assert cfg["region"] == "cn-shanghai"


# ---------------------------------------------------------------------------
# Shortcuts and aliases forward region to the final command
# ---------------------------------------------------------------------------


class TestShortcutForwarding:
    """Top-level shortcuts / group aliases must keep --region working."""

    def test_top_level_install_accepts_region(self, runner: CliRunner) -> None:
        """``ebx install ./missing --region ...`` parses (fails on the path, not the flag)."""
        result = runner.invoke(cli, ["install", "./definitely-missing", "--region", "cn-shanghai"])
        # EXIT_NOT_FOUND from install's early local-path validation.
        assert result.exit_code == 4
        assert "No such option" not in _combined_output(result)

    def test_top_level_install_forwards_region_to_template_install(self, runner: CliRunner) -> None:
        with patch("easy_sandbox.cli.commands.template.install") as install_cmd:
            result = runner.invoke(
                cli, ["install", "owner/repo", "--yes", "--region", "cn-shanghai"]
            )
        assert result.exit_code == 0, result.output
        assert install_cmd.call_args.kwargs.get("region") == "cn-shanghai"

    def test_template_deploy_alias_inherits_region_param(self) -> None:
        from easy_sandbox.cli.commands.template import deploy as template_deploy

        assert any(p.name == "region" for p in template_deploy.params)

    def test_kill_all_accepts_region_flag(self, runner: CliRunner) -> None:
        """``ebx kill --all --yes --region ...`` is accepted (mocked transport)."""
        with (
            patch("easy_sandbox.transport.config.load_config"),
            patch("easy_sandbox.transport.auth.create_auth_provider"),
            patch("easy_sandbox.transport.http.HttpClient"),
            patch("easy_sandbox.protocol.sandbox.SandboxProtocol"),
            patch("easy_sandbox.utils.async_bridge.run_sync", return_value=[]),
        ):
            result = runner.invoke(cli, ["kill", "--all", "--yes", "--region", "cn-shanghai"])
        assert result.exit_code == 0, result.output
