"""The server SDK reference given to the coding agent must match the real SDK.

The guide is prompt text, so nothing else would notice if ``easy_sandbox.server``
changed and the guide kept teaching the agent an API that no longer exists.
"""

from __future__ import annotations

import ast
import re
from unittest.mock import patch

import pytest

import easy_sandbox.server as server_pkg
from easy_sandbox.agent import template_guide
from easy_sandbox.agent.template_guide import (
    REFERENCE_COMMANDS_PY,
    REQUIRED_TEMPLATE_FILES,
    SERVER_ENTRYPOINT,
    SERVER_PORT,
    TEMPLATE_GUIDE,
)
from easy_sandbox.models.template import STANDARD_CAPABILITIES
from easy_sandbox.server import CapabilityGroup, RouteTable, SandboxServer


class TestConstants:
    def test_required_files_include_the_server_entry_point(self) -> None:
        assert SERVER_ENTRYPOINT in REQUIRED_TEMPLATE_FILES
        assert {"Dockerfile", "template.yaml"} <= set(REQUIRED_TEMPLATE_FILES)

    def test_port_matches_the_server_default(self) -> None:
        import inspect

        default = inspect.signature(SandboxServer.serve).parameters["port"].default
        assert default == SERVER_PORT

    def test_public_names_are_exported(self) -> None:
        for name in template_guide.__all__:
            assert hasattr(template_guide, name)


class TestGuideText:
    def test_explains_why_a_server_is_needed(self) -> None:
        assert "HTTP" in TEMPLATE_GUIDE
        assert "commands.py" in TEMPLATE_GUIDE
        assert f"EXPOSE {SERVER_PORT}" in TEMPLATE_GUIDE
        assert 'CMD ["python3", "commands.py"]' in TEMPLATE_GUIDE

    def test_sdk_install_pattern_is_the_established_one(self) -> None:
        assert "COPY *.whl /tmp/" in TEMPLATE_GUIDE
        assert "pip install --no-cache-dir easy-sandbox" in TEMPLATE_GUIDE

    def test_no_clarification_wording_leaks_into_the_prompt(self) -> None:
        assert "澄清" not in TEMPLATE_GUIDE

    def test_every_capability_group_it_names_exists(self) -> None:
        # ``CapabilityGroup.X`` is the guide's own placeholder, not a group.
        named = set(re.findall(r"CapabilityGroup\.([A-Z_]+)", TEMPLATE_GUIDE)) - {"X"}
        assert named  # the guide does talk about groups
        assert named <= {group.name for group in CapabilityGroup}

    def test_describes_every_capability_group(self) -> None:
        for group in CapabilityGroup:
            assert group.name in TEMPLATE_GUIDE

    def test_default_disabled_groups_are_called_out(self) -> None:
        assert re.search(r"DEV_TOOLS[^\n]*默认关闭", TEMPLATE_GUIDE)
        assert re.search(r"BROWSER[^\n]*默认关闭", TEMPLATE_GUIDE)

    def test_capability_tokens_are_the_standard_ones(self) -> None:
        line = next(
            entry for entry in TEMPLATE_GUIDE.splitlines() if "`capabilities` 取自" in entry
        )
        tokens = set(re.findall(r"[a-z]+", line.split("取自", 1)[1].split("，", 1)[0]))
        assert tokens == set(STANDARD_CAPABILITIES)

    def test_imports_shown_in_the_guide_exist(self) -> None:
        block = re.search(r"from easy_sandbox\.server import \((.*?)\)", TEMPLATE_GUIDE, re.S)
        assert block is not None
        names = [n.strip() for n in block.group(1).replace("\n", " ").split(",") if n.strip()]
        assert names
        for name in names:
            assert name in server_pkg.__all__, name


class TestReferenceCommandsPy:
    def test_is_valid_python(self) -> None:
        ast.parse(REFERENCE_COMMANDS_PY)

    def test_only_imports_public_server_names(self) -> None:
        tree = ast.parse(REFERENCE_COMMANDS_PY)
        imported = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "easy_sandbox.server"
            for alias in node.names
        ]
        assert imported
        assert set(imported) <= set(server_pkg.__all__)

    def test_loads_registers_a_command_and_serves_on_the_documented_port(self) -> None:
        """Run the reference exactly like the template e2e tests do: serve() patched out."""
        table = RouteTable()
        namespace: dict[str, object] = {"__name__": "reference_commands"}
        with (
            patch.object(SandboxServer, "serve", autospec=True) as serve,
            patch("easy_sandbox.server.default_table", return_value=table),
        ):
            exec(compile(REFERENCE_COMMANDS_PY, "commands.py", "exec"), namespace)

        registry = namespace["registry"]
        assert "hello" in registry  # type: ignore[operator]
        assert registry.get("hello").fn("Ada") == "Hello, Ada!"  # type: ignore[attr-defined]
        assert serve.call_count == 1
        assert serve.call_args.kwargs == {"port": SERVER_PORT}
        route, params = table.match("GET", "/hello/Ada")
        assert route is not None
        assert params == {"name": "Ada"}

    def test_registry_is_frozen_before_serving(self) -> None:
        source = REFERENCE_COMMANDS_PY
        assert source.index("registry.freeze()") < source.index(".serve(")
        assert source.rstrip().splitlines()[-1].strip().startswith("server.serve(")

    @pytest.mark.parametrize("marker", ["FILE_OPS", "PROCESS", "SYSTEM"])
    def test_enables_the_groups_the_capabilities_example_relies_on(self, marker: str) -> None:
        assert f"CapabilityGroup.{marker}" in REFERENCE_COMMANDS_PY
