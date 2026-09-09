"""SDK 工作流端到端测试 — Mock 后端验证完整链路。

Tests the complete workflow from template definition → capability resolution
→ image build → CLI command completeness → declarative↔server bridge.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from serverless_sandbox.api.capability import (
    ResolvedCapabilities,
    check_capability,
    resolve_capabilities,
)
from serverless_sandbox.api.image import Image
from serverless_sandbox.cli.main import cli
from serverless_sandbox.models.errors import CapabilityNotSupportedError
from serverless_sandbox.models.template import (
    DEFAULT_CAPABILITIES,
    SandboxTemplate,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_HELLO_YAML = _PROJECT_ROOT / "examples" / "templates" / "python-hello" / "template.yaml"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Test 1: Template definition and Dockerfile generation
# ---------------------------------------------------------------------------


class TestTemplateDefinition:
    """Load template.yaml → parse → validate Dockerfile output."""

    def test_parse_python_hello_template(self):
        """examples/templates/python-hello/template.yaml should parse correctly."""
        assert _PYTHON_HELLO_YAML.exists(), f"Missing {_PYTHON_HELLO_YAML}"
        data = yaml.safe_load(_PYTHON_HELLO_YAML.read_text())
        template = SandboxTemplate.model_validate(data)

        assert template.name == "python-hello"
        assert template.base == "ubuntu:22.04"
        assert "python3" in template.system_packages
        assert "shell" in template.capabilities
        assert "ports" in template.capabilities
        assert template.ports == [9000]
        assert "run" in template.custom_commands
        assert "test" in template.custom_commands

    def test_dockerfile_generation(self):
        """to_dockerfile() should produce valid Dockerfile lines."""
        data = yaml.safe_load(_PYTHON_HELLO_YAML.read_text())
        template = SandboxTemplate.model_validate(data)
        dockerfile = template.to_dockerfile()

        assert dockerfile.startswith("FROM ubuntu:22.04")
        assert "apt-get" in dockerfile
        assert "python3" in dockerfile
        # ENV directives
        assert "ENV LANG=C.UTF-8" in dockerfile

    def test_custom_commands_parsed(self):
        """Custom commands in the template should have correct args and fields."""
        data = yaml.safe_load(_PYTHON_HELLO_YAML.read_text())
        template = SandboxTemplate.model_validate(data)

        run_cmd = template.custom_commands["run"]
        assert run_cmd.cmd == "python3 {file}"
        assert run_cmd.timeout == 60
        assert len(run_cmd.args) == 1
        assert run_cmd.args[0].name == "file"
        assert run_cmd.args[0].default == "main.py"

        test_cmd = template.custom_commands["test"]
        assert test_cmd.cmd == "python3 -m pytest {path}"
        assert test_cmd.timeout == 120

    def test_template_with_capabilities_none_uses_defaults(self):
        """When capabilities is None, DEFAULT_CAPABILITIES should apply."""
        tmpl = SandboxTemplate(name="minimal")
        assert tmpl.capabilities is None

    def test_template_with_explicit_capabilities(self):
        """Explicit capabilities override defaults."""
        tmpl = SandboxTemplate(name="custom", capabilities=["shell", "terminal"])
        assert set(tmpl.capabilities) == {"shell", "terminal"}


# ---------------------------------------------------------------------------
# Test 2: Capability resolution
# ---------------------------------------------------------------------------


class TestCapabilityResolution:
    """Test resolve_capabilities() with 4-level fallback."""

    async def test_resolve_from_local_yaml(self, tmp_path):
        """Priority 1: explicit local_yaml_path."""
        yaml_content = {
            "name": "test-template",
            "capabilities": ["shell", "files", "terminal"],
        }
        yaml_file = tmp_path / "template.yaml"
        yaml_file.write_text(yaml.dump(yaml_content))

        result = await resolve_capabilities(
            "test-template",
            local_yaml_path=str(yaml_file),
        )
        assert isinstance(result, ResolvedCapabilities)
        assert result.capabilities == {"shell", "files", "terminal"}

    async def test_resolve_from_local_cache(self, tmp_path):
        """Priority 2: scan ~/.sbox/templates/."""
        cache_dir = tmp_path / "templates" / "my-template"
        cache_dir.mkdir(parents=True)
        yaml_content = {
            "name": "my-template",
            "capabilities": ["shell", "files", "code", "ports"],
            "ports": [8080],
        }
        (cache_dir / "template.yaml").write_text(yaml.dump(yaml_content))

        with patch("serverless_sandbox.api.capability.TEMPLATE_CACHE_DIR", tmp_path / "templates"):
            result = await resolve_capabilities("my-template")

        assert "ports" in result.capabilities
        assert "shell" in result.capabilities

    async def test_resolve_fallback_to_defaults(self):
        """Priority 4: when nothing matches, fall back to DEFAULT_CAPABILITIES."""
        result = await resolve_capabilities("nonexistent-template-xyz")
        assert result.capabilities == set(DEFAULT_CAPABILITIES)
        assert result.custom_commands == {}

    def test_check_capability_raises_on_missing(self):
        """check_capability raises CapabilityNotSupportedError for undeclared caps."""
        caps = {"shell", "files"}
        with pytest.raises(CapabilityNotSupportedError) as exc_info:
            check_capability(caps, "terminal")
        assert "terminal" in str(exc_info.value)
        assert exc_info.value.code == "E3004"

    def test_check_capability_passes_on_present(self):
        """check_capability does not raise when the capability is present."""
        caps = {"shell", "files", "code"}
        check_capability(caps, "shell")  # should not raise

    async def test_resolve_with_custom_commands(self, tmp_path):
        """Custom commands from template.yaml should appear in resolved result."""
        yaml_content = {
            "name": "cmd-template",
            "capabilities": ["shell"],
            "custom_commands": {
                "build": {
                    "cmd": "make build",
                    "description": "Build the project",
                    "timeout": 120,
                }
            },
        }
        yaml_file = tmp_path / "template.yaml"
        yaml_file.write_text(yaml.dump(yaml_content))

        result = await resolve_capabilities(
            "cmd-template",
            local_yaml_path=str(yaml_file),
        )
        assert "build" in result.custom_commands
        assert result.custom_commands["build"].cmd == "make build"


# ---------------------------------------------------------------------------
# Test 3: Image chain builder
# ---------------------------------------------------------------------------


class TestImageChainBuilder:
    """Test Image.from_image(...).pip_install(...).env(...) chain."""

    def test_basic_chain(self):
        """Chain API produces correct Dockerfile."""
        image = (
            Image.from_image("python:3.11")
            .pip_install("flask")
            .env(PORT="8080")
        )
        dockerfile = image.to_dockerfile()
        lines = dockerfile.split("\n")

        assert lines[0] == "FROM python:3.11"
        assert any("pip install" in line and "flask" in line for line in lines)
        assert any("ENV PORT=8080" in line for line in lines)

    def test_full_chain(self):
        """Test all chain methods together."""
        image = (
            Image.from_image("python:3.11-slim")
            .apt_install("curl", "git")
            .pip_install("flask", "sqlalchemy")
            .run_command("echo 'setup done'")
            .env(APP_ENV="production", DEBUG="false")
            .workdir("/app")
            .expose(8080, 443)
            .entrypoint("python main.py")
        )
        dockerfile = image.to_dockerfile()

        assert "FROM python:3.11-slim" in dockerfile
        assert "apt-get" in dockerfile
        assert "curl" in dockerfile and "git" in dockerfile
        assert "pip install" in dockerfile
        assert "flask" in dockerfile and "sqlalchemy" in dockerfile
        assert "echo 'setup done'" in dockerfile
        assert "ENV APP_ENV=production" in dockerfile
        assert "ENV DEBUG=false" in dockerfile
        assert "WORKDIR /app" in dockerfile
        assert "EXPOSE 8080" in dockerfile
        assert "EXPOSE 443" in dockerfile
        assert "CMD python main.py" in dockerfile

    def test_from_template(self):
        """from_template sets the base to the template name."""
        image = Image.from_template("python-base").pip_install("numpy")
        dockerfile = image.to_dockerfile()
        assert "FROM python-base" in dockerfile
        assert "pip install" in dockerfile
        assert "numpy" in dockerfile

    def test_empty_image(self):
        """Default image uses ubuntu:22.04."""
        image = Image()
        dockerfile = image.to_dockerfile()
        assert dockerfile == "FROM ubuntu:22.04"

    def test_repr(self):
        """repr shows meaningful info."""
        image = Image.from_image("python:3.11").pip_install("a").env(X="1")
        r = repr(image)
        assert "python:3.11" in r
        assert "steps=1" in r
        assert "envs=1" in r


# ---------------------------------------------------------------------------
# Test 4: CLI command completeness verification
# ---------------------------------------------------------------------------


class TestCLICompleteness:
    """Verify that all expected commands are registered and accessible."""

    def test_sbox_help_contains_all_commands(self, runner):
        """sbox --help should list all expected subcommands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        output = result.output

        expected_commands = [
            "auth", "config", "connect", "create", "deploy",
            "download", "exec", "info", "install", "kill",
            "list", "mcp", "run", "secret", "session",
            "skill", "template", "upload",
        ]
        for cmd in expected_commands:
            assert cmd in output, f"Command '{cmd}' not found in sbox --help output"

    def test_template_help(self, runner):
        """sbox template --help should show subcommands."""
        result = runner.invoke(cli, ["template", "--help"])
        assert result.exit_code == 0
        assert "template" in result.output.lower()

    def test_config_list_runs(self, runner):
        """sbox config list should run without errors."""
        result = runner.invoke(cli, ["config", "list"])
        assert result.exit_code == 0

    def test_auth_help(self, runner):
        """sbox auth --help should show auth subcommands."""
        result = runner.invoke(cli, ["auth", "--help"])
        assert result.exit_code == 0

    def test_session_help(self, runner):
        """sbox session --help should be accessible."""
        result = runner.invoke(cli, ["session", "--help"])
        assert result.exit_code == 0

    def test_secret_help(self, runner):
        """sbox secret --help should be accessible."""
        result = runner.invoke(cli, ["secret", "--help"])
        assert result.exit_code == 0

    def test_skill_help(self, runner):
        """sbox skill --help should be accessible."""
        result = runner.invoke(cli, ["skill", "--help"])
        assert result.exit_code == 0

    def test_version_option(self, runner):
        """sbox --version should print package version."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test 5: Declarative → Server bridge verification
# ---------------------------------------------------------------------------


class TestDeclarativeServerBridge:
    """Verify that @sandbox.register bridges to the server registry."""

    def test_register_bridges_to_server_registry(self):
        """@sandbox.register should register the command in both registries."""
        # Import fresh to avoid cross-test pollution of the default registry
        from serverless_sandbox.declarative.decorator import _SandboxFactory
        from serverless_sandbox.server.registry import CommandRegistry as ServerCommandRegistry

        # Create a fresh server registry and patch default_registry()
        fresh_server_reg = ServerCommandRegistry()

        with patch(
            "serverless_sandbox.server.registry.default_registry",
            return_value=fresh_server_reg,
        ):
            factory = _SandboxFactory()

            @factory.register
            def demo(x: int, y: str) -> str:
                return f"{y}={x}"

        # Verify declarative registry
        assert "demo" in factory._registry
        decl_cmd = factory._registry["demo"]
        assert decl_cmd.name == "demo"
        assert len(decl_cmd.args) == 2
        assert decl_cmd.args[0].name == "x"
        assert decl_cmd.args[0].type == "integer"
        assert decl_cmd.args[0].required is True
        assert decl_cmd.args[1].name == "y"
        assert decl_cmd.args[1].type == "string"
        assert decl_cmd.args[1].required is True

        # Verify server registry
        assert "demo" in fresh_server_reg
        srv_cmd = fresh_server_reg.get("demo")
        assert srv_cmd is not None
        assert srv_cmd.name == "demo"
        assert len(srv_cmd.args) == 2
        assert srv_cmd.args[0].name == "x"
        assert srv_cmd.args[0].type == "integer"
        assert srv_cmd.args[1].name == "y"
        assert srv_cmd.args[1].type == "string"

    def test_register_with_defaults(self):
        """Arguments with defaults should be marked required=False."""
        from serverless_sandbox.declarative.decorator import _SandboxFactory
        from serverless_sandbox.server.registry import CommandRegistry as ServerCommandRegistry

        fresh_server_reg = ServerCommandRegistry()

        with patch(
            "serverless_sandbox.server.registry.default_registry",
            return_value=fresh_server_reg,
        ):
            factory = _SandboxFactory()

            @factory.register
            def greet(name: str, greeting: str = "Hello") -> str:
                return f"{greeting}, {name}!"

        decl_cmd = factory._registry["greet"]
        assert decl_cmd.args[0].required is True   # name
        assert decl_cmd.args[1].required is False   # greeting has default

        srv_cmd = fresh_server_reg.get("greet")
        assert srv_cmd.args[0].required is True
        assert srv_cmd.args[1].required is False
        assert srv_cmd.args[1].default == "Hello"

    def test_registered_function_still_callable(self):
        """The original function should still be callable locally."""
        from serverless_sandbox.declarative.decorator import _SandboxFactory
        from serverless_sandbox.server.registry import CommandRegistry as ServerCommandRegistry

        fresh_server_reg = ServerCommandRegistry()

        with patch(
            "serverless_sandbox.server.registry.default_registry",
            return_value=fresh_server_reg,
        ):
            factory = _SandboxFactory()

            @factory.register
            def add(a: int, b: int) -> int:
                return a + b

        # The decorator should return the original function unchanged
        assert add(3, 4) == 7

    def test_list_registered_commands(self):
        """list_registered() returns metadata for all registered commands."""
        from serverless_sandbox.declarative.decorator import _SandboxFactory
        from serverless_sandbox.server.registry import CommandRegistry as ServerCommandRegistry

        fresh_server_reg = ServerCommandRegistry()

        with patch(
            "serverless_sandbox.server.registry.default_registry",
            return_value=fresh_server_reg,
        ):
            factory = _SandboxFactory()

            @factory.register
            def foo(x: int) -> int:
                return x * 2

            @factory.register
            def bar(s: str) -> str:
                return s.upper()

        registered = factory.list_registered()
        names = {cmd["name"] for cmd in registered}
        assert names == {"foo", "bar"}
