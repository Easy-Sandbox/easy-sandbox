"""End-to-end check that every credential consumer uses one order.

The order is: explicit argument, process environment, ``./.env``, ``~/.ebx``,
then a built-in default. ``.env`` files merge per key, so a project file that
omits a key does not hide ``~/.ebx``.

Consumers covered here:

* ``ebx config list``
* ``load_config`` (``Sandbox.create`` and the other SDK clients)
* ``resolve_llm_env`` (``Sandbox.deploy``)
* the coding agent used by natural-language ``ebx create``
* ``resolve_github_token`` (template install / search)
* ``ebx mcp install`` via ``_read_api_key`` and ``_build_mcp_server_config``
* ``resolve_region`` (command ``--region``)
* ACR namespace (``--acr-namespace`` / ``ACR_NAMESPACE`` / ``./.env`` / ``~/.ebx``)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click
import pytest
from click.testing import CliRunner

from easy_sandbox.agent.coding_agent import QwenCodeBackend
from easy_sandbox.api import deploy as deploy_mod
from easy_sandbox.api.deploy import resolve_llm_env
from easy_sandbox.cli.commands import config_cmd
from easy_sandbox.cli.commands._coding_agent import resolve_coding_agent_credentials
from easy_sandbox.cli.commands.config_cmd import resolve_github_token
from easy_sandbox.cli.commands.mcp import _build_mcp_server_config, _read_api_key
from easy_sandbox.cli.commands.template import _resolve_acr_namespace
from easy_sandbox.cli.main import cli
from easy_sandbox.cli.region import resolve_region
from easy_sandbox.transport import config as transport_config
from easy_sandbox.transport.config import load_config, reset_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


_STORED_SANDBOX = "e2b-stored-sandbox-aaa"
_ENV_SANDBOX = "e2b-env-sandbox-bbb"
_PROJECT_SANDBOX = "e2b-project-sandbox-ccc"
_STORED_LLM = "sk-stored-llm-aaa111"
_ENV_LLM = "sk-env-llm-key-bbb222"
_STORED_GITHUB = "ghp-stored-token-111"
_ENV_GITHUB = "ghp-env-token-222"
_ALIAS_SANDBOX = "e2b-alias-sandbox-ddd"
_VENDOR_LLM = "sk-vendor-llm-ddd444"
_LEGACY_LLM = "sk-legacy-qwen-eee555"
_FILE_QWEN = "sk-file-qwen-fff666"

_ISOLATED_ENV = (
    "E2B_API_KEY",
    "SANDBOX_API_KEY",
    "E2B_API_URL",
    "SANDBOX_API_BASE_URL",
    "SANDBOX_REGION",
    "ALICLOUD_ACCESS_KEY_ID",
    "ALICLOUD_ACCESS_KEY_SECRET",
    "AccessKey",
    "AccessSecret",
    "ACR_NAMESPACE",
)


@pytest.fixture
def credential_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Point every credential reader at one temporary home and project file."""
    ebx = tmp_path / "ebx"
    ebx.mkdir()
    project = tmp_path / "project.env"
    monkeypatch.setattr(config_cmd, "_EBX_DIR", ebx)
    monkeypatch.setattr(config_cmd, "_CONFIG_FILE", ebx / "config.toml")
    monkeypatch.setattr(config_cmd, "_ENV_FILE", ebx / ".env")
    monkeypatch.setattr(deploy_mod, "_EBX_DIR", ebx)
    monkeypatch.setattr(transport_config, "_CONFIG_FILE", ebx / "config.toml")
    monkeypatch.setattr(transport_config, "_ENV_FILE_CANDIDATES", [project, ebx / ".env"])
    monkeypatch.setattr(transport_config, "_PROJECT_ENV_FILE", project)
    for name in _ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    reset_config()
    yield {"ebx": ebx, "project": project}
    reset_config()


def _write_system(ebx: Path) -> None:
    (ebx / ".env").write_text(
        f"E2B_API_KEY={_STORED_SANDBOX}\n"
        "ALICLOUD_ACCESS_KEY_ID=stored-ak-id\n"
        "ALICLOUD_ACCESS_KEY_SECRET=stored-ak-secret\n"
        f"EBX_LLM_API_KEY={_STORED_LLM}\n"
        f"GITHUB_TOKEN={_STORED_GITHUB}\n"
        "ACR_NAMESPACE=ns-stored\n",
        encoding="utf-8",
    )
    (ebx / "config.toml").write_text(
        "[transport]\n"
        'llm_base_url = "https://stored.example/v1"\n'
        'llm_model = "stored-model"\n'
        'region = "cn-beijing"\n',
        encoding="utf-8",
    )


def _agent_env() -> dict[str, str]:
    ctx = click.Context(click.Command("ebx"))
    creds = resolve_coding_agent_credentials(ctx, yes=True, backend=QwenCodeBackend())
    return creds.as_env()


class TestCredentialPriorityEndToEnd:
    def test_process_env_beats_system_config(
        self,
        credential_home: dict[str, Path],
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_system(credential_home["ebx"])
        monkeypatch.setenv("E2B_API_KEY", _ENV_SANDBOX)
        monkeypatch.setenv("DASHSCOPE_API_KEY", _ENV_LLM)
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
        monkeypatch.setenv("OPENAI_MODEL", "env-model")
        monkeypatch.setenv("GITHUB_TOKEN", _ENV_GITHUB)
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_ID", "env-ak-id")
        reset_config()

        listed = runner.invoke(cli, ["config", "list"])
        assert listed.exit_code == 0
        assert "e2b***bbb (env)" in listed.output
        assert "sk-***222 (env)" in listed.output
        assert "https://env.example/v1 (env)" in listed.output
        assert "env-model (env)" in listed.output
        assert "ghp***222 (env)" in listed.output
        assert "cn-shenzhen (env)" in listed.output
        assert _STORED_SANDBOX not in listed.output
        assert "stored-model" not in listed.output

        reset_config()
        assert load_config().api_key == _ENV_SANDBOX
        assert load_config().access_key_id == "env-ak-id"
        assert load_config().region == "cn-shenzhen"
        assert _read_api_key() == _ENV_SANDBOX

        deployed = resolve_llm_env()
        assert deployed["DASHSCOPE_API_KEY"] == _ENV_LLM
        assert deployed["OPENAI_BASE_URL"] == "https://env.example/v1"
        assert deployed["OPENAI_MODEL"] == "env-model"
        assert _agent_env()["OPENAI_API_KEY"] == _ENV_LLM
        assert _agent_env()["OPENAI_BASE_URL"] == "https://env.example/v1"
        assert resolve_github_token() == _ENV_GITHUB

        # A one-off argument still beats the environment.
        assert (
            resolve_llm_env(llm_api_key="sk-placeholder")["DASHSCOPE_API_KEY"] == "sk-placeholder"
        )
        assert resolve_github_token("ghp-explicit") == "ghp-explicit"

    def test_system_config_when_env_and_project_file_omit_the_key(
        self, credential_home: dict[str, Path], runner: CliRunner
    ) -> None:
        _write_system(credential_home["ebx"])
        # The project file exists and sets an unrelated key. That must not
        # hide the sandbox key, LLM key, or GitHub token saved in ~/.ebx.
        credential_home["project"].write_text("SANDBOX_HTTP_TIMEOUT=15\n", encoding="utf-8")
        reset_config()

        listed = runner.invoke(cli, ["config", "list"])
        assert listed.exit_code == 0
        assert "e2b***aaa (user)" in listed.output
        assert "sk-***111 (user)" in listed.output
        assert "https://stored.example/v1 (user)" in listed.output
        assert "stored-model (user)" in listed.output
        assert "ghp***111 (user)" in listed.output
        assert "cn-beijing (user)" in listed.output
        assert "ns-stored (user)" in listed.output

        reset_config()
        loaded = load_config()
        assert loaded.api_key == _STORED_SANDBOX
        assert loaded.access_key_id == "stored-ak-id"
        assert loaded.access_key_secret == "stored-ak-secret"
        assert loaded.region == "cn-beijing"
        assert loaded.http_timeout == 15.0
        assert _read_api_key() == _STORED_SANDBOX

        deployed = resolve_llm_env()
        assert deployed["DASHSCOPE_API_KEY"] == _STORED_LLM
        assert deployed["OPENAI_BASE_URL"] == "https://stored.example/v1"
        assert deployed["OPENAI_MODEL"] == "stored-model"
        assert _agent_env()["OPENAI_API_KEY"] == _STORED_LLM
        assert _agent_env()["OPENAI_MODEL"] == "stored-model"
        assert resolve_github_token() == _STORED_GITHUB
        assert resolve_region(None) == "cn-beijing"

        # The editor config copies the resolved sandbox key. Region saved
        # only in config.toml is not frozen into that file.
        embedded = _build_mcp_server_config()
        assert embedded["env"]["E2B_API_KEY"] == _STORED_SANDBOX
        assert "SANDBOX_REGION" not in embedded["env"]

    def test_project_dotenv_beats_system_and_loses_to_process_env(
        self,
        credential_home: dict[str, Path],
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_system(credential_home["ebx"])
        credential_home["project"].write_text(
            f"E2B_API_KEY={_PROJECT_SANDBOX}\n"
            "EBX_LLM_API_KEY=sk-project-llm-ccc333\n"
            "OPENAI_BASE_URL=https://project.example/v1\n",
            encoding="utf-8",
        )
        reset_config()

        listed = runner.invoke(cli, ["config", "list"])
        assert listed.exit_code == 0
        assert "e2b***ccc (user)" in listed.output
        assert "sk-***333 (user)" in listed.output
        assert "https://project.example/v1 (user)" in listed.output
        # The model was not in the project file, so ~/.ebx still supplies it.
        assert "stored-model (user)" in listed.output

        reset_config()
        assert load_config().api_key == _PROJECT_SANDBOX
        assert _read_api_key() == _PROJECT_SANDBOX
        assert resolve_llm_env()["DASHSCOPE_API_KEY"] == "sk-project-llm-ccc333"
        assert resolve_llm_env()["OPENAI_BASE_URL"] == "https://project.example/v1"
        assert resolve_llm_env()["OPENAI_MODEL"] == "stored-model"
        assert _agent_env()["OPENAI_API_KEY"] == "sk-project-llm-ccc333"

        monkeypatch.setenv("E2B_API_KEY", _ENV_SANDBOX)
        monkeypatch.setenv("EBX_LLM_API_KEY", _ENV_LLM)
        reset_config()
        assert load_config().api_key == _ENV_SANDBOX
        assert _read_api_key() == _ENV_SANDBOX
        assert resolve_llm_env()["DASHSCOPE_API_KEY"] == _ENV_LLM
        listed_env = runner.invoke(cli, ["config", "list"])
        assert "e2b***bbb (env)" in listed_env.output
        assert "sk-***222 (env)" in listed_env.output

    def test_same_layer_order_explicit_region_and_mcp_region(
        self,
        credential_home: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_system(credential_home["ebx"])
        monkeypatch.setenv("E2B_API_KEY", _ENV_SANDBOX)
        monkeypatch.setenv("SANDBOX_API_KEY", _ALIAS_SANDBOX)
        monkeypatch.setenv("EBX_LLM_API_KEY", _ENV_LLM)
        monkeypatch.setenv("DASHSCOPE_API_KEY", _VENDOR_LLM)
        monkeypatch.setenv("ALICLOUD_ACCESS_KEY_ID", "env-alicld-ak")
        monkeypatch.setenv("AccessKey", "env-legacy-ak")
        monkeypatch.setenv("SANDBOX_REGION", "cn-shenzhen")
        reset_config()

        assert load_config().api_key == _ENV_SANDBOX
        assert load_config().access_key_id == "env-alicld-ak"
        assert resolve_llm_env()["DASHSCOPE_API_KEY"] == _ENV_LLM
        assert _agent_env()["OPENAI_API_KEY"] == _ENV_LLM
        assert resolve_region("cn-shanghai") == "cn-shanghai"
        assert resolve_region(None) == "cn-shenzhen"

        embedded = _build_mcp_server_config()
        assert embedded["env"]["E2B_API_KEY"] == _ENV_SANDBOX
        assert embedded["env"]["SANDBOX_REGION"] == "cn-shenzhen"
        assert "E2B_API_URL" not in embedded["env"]

    def test_blank_values_fall_through(
        self,
        credential_home: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_system(credential_home["ebx"])
        monkeypatch.setenv("E2B_API_KEY", "   ")
        monkeypatch.setenv("GITHUB_TOKEN", "   ")
        monkeypatch.setenv("SANDBOX_REGION", "   ")
        reset_config()

        assert load_config().api_key == _STORED_SANDBOX
        assert load_config().region == "cn-beijing"
        assert resolve_github_token("   ") == _STORED_GITHUB
        assert resolve_region("   ") == "cn-beijing"

        monkeypatch.setenv("SANDBOX_API_KEY", _ALIAS_SANDBOX)
        reset_config()
        assert load_config().api_key == _ALIAS_SANDBOX

    def test_legacy_qwen_key_when_llm_key_is_absent(
        self,
        credential_home: dict[str, Path],
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ebx = credential_home["ebx"]
        (ebx / ".env").write_text(
            f"E2B_API_KEY={_STORED_SANDBOX}\nEBX_QWEN_CODE_API_KEY={_FILE_QWEN}\n",
            encoding="utf-8",
        )
        (ebx / "config.toml").write_text(
            "[transport]\n"
            'qwen_code_base_url = "https://legacy.example/v1"\n'
            'qwen_code_model = "legacy-model"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("EBX_QWEN_CODE_API_KEY", _LEGACY_LLM)
        reset_config()

        assert resolve_llm_env()["DASHSCOPE_API_KEY"] == _LEGACY_LLM
        assert _agent_env()["OPENAI_API_KEY"] == _LEGACY_LLM
        listed = runner.invoke(cli, ["config", "list"])
        assert listed.exit_code == 0
        assert "sk-***555 (env)" in listed.output

        monkeypatch.delenv("EBX_QWEN_CODE_API_KEY")
        reset_config()
        stored = resolve_llm_env()
        assert stored["DASHSCOPE_API_KEY"] == _FILE_QWEN
        assert stored["OPENAI_BASE_URL"] == "https://legacy.example/v1"
        assert stored["OPENAI_MODEL"] == "legacy-model"
        listed_file = runner.invoke(cli, ["config", "list"])
        assert "sk-***666 (user)" in listed_file.output
        assert "https://legacy.example/v1 (user)" in listed_file.output
        assert "legacy-model (user)" in listed_file.output

    def test_acr_namespace_follows_the_same_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        ebx = home / ".ebx"
        ebx.mkdir(parents=True)
        (ebx / ".env").write_text("ACR_NAMESPACE=ns-stored\n", encoding="utf-8")
        work = tmp_path / "work"
        work.mkdir()
        (work / ".env").write_text("ACR_NAMESPACE=ns-project\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("ACR_NAMESPACE", raising=False)
        monkeypatch.chdir(work)

        assert _resolve_acr_namespace(None) == "ns-project"
        monkeypatch.setenv("ACR_NAMESPACE", "ns-env")
        assert _resolve_acr_namespace(None) == "ns-env"
        assert _resolve_acr_namespace("ns-flag") == "ns-flag"
        monkeypatch.setenv("ACR_NAMESPACE", "   ")
        assert _resolve_acr_namespace("   ") == "ns-project"
