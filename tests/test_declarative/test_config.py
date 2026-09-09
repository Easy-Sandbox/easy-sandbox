"""Tests for declarative/config.py — YAML 配置解析。"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from serverless_sandbox.declarative.config import SandboxDeclarativeConfig


class TestSandboxDeclarativeConfigDefaults:
    """Default values when no YAML file is present."""

    def test_defaults(self) -> None:
        cfg = SandboxDeclarativeConfig()
        assert cfg.template == "code-interpreter-v1"
        assert cfg.timeout == 300
        assert cfg.envs == {}
        assert cfg.python_packages == []
        assert cfg.files == {}
        assert cfg.serializer == "json"
        assert cfg.image is None
        assert cfg.cpu is None
        assert cfg.memory is None

    def test_from_file_missing(self, tmp_path: Path) -> None:
        """from_file returns defaults when file does not exist."""
        cfg = SandboxDeclarativeConfig.from_file(tmp_path / "nonexistent.yaml")
        assert cfg.template == "code-interpreter-v1"
        assert cfg.timeout == 300


class TestSandboxDeclarativeConfigFromFile:
    """Loading from an actual YAML file."""

    @pytest.fixture(autouse=True)
    def _check_yaml(self) -> None:
        pytest.importorskip("yaml")

    def test_full_config(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            template: python-base
            timeout: 600
            envs:
              MY_VAR: "hello"
            python_packages:
              - numpy
              - pandas
            files:
              ./local.txt: /remote/local.txt
            serializer: pickle
        """)
        p = tmp_path / "sandbox.yaml"
        p.write_text(yaml_content)
        cfg = SandboxDeclarativeConfig.from_file(p)
        assert cfg.template == "python-base"
        assert cfg.timeout == 600
        assert cfg.envs == {"MY_VAR": "hello"}
        assert cfg.python_packages == ["numpy", "pandas"]
        assert cfg.files == {"./local.txt": "/remote/local.txt"}
        assert cfg.serializer == "pickle"

    def test_partial_config(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            template: my-template
        """)
        p = tmp_path / "sandbox.yaml"
        p.write_text(yaml_content)
        cfg = SandboxDeclarativeConfig.from_file(p)
        assert cfg.template == "my-template"
        assert cfg.timeout == 300  # default

    def test_empty_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "sandbox.yaml"
        p.write_text("")
        cfg = SandboxDeclarativeConfig.from_file(p)
        assert cfg.template == "code-interpreter-v1"

    def test_extra_keys_ignored(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            template: base
            unknown_key: should_be_ignored
        """)
        p = tmp_path / "sandbox.yaml"
        p.write_text(yaml_content)
        cfg = SandboxDeclarativeConfig.from_file(p)
        assert cfg.template == "base"


class TestSandboxDeclarativeConfigFromDict:
    """from_dict construction."""

    def test_from_dict(self) -> None:
        cfg = SandboxDeclarativeConfig.from_dict({
            "template": "go-base",
            "timeout": 120,
            "serializer": "msgpack",
        })
        assert cfg.template == "go-base"
        assert cfg.timeout == 120
        assert cfg.serializer == "msgpack"

    def test_from_dict_empty(self) -> None:
        cfg = SandboxDeclarativeConfig.from_dict({})
        assert cfg.template == "code-interpreter-v1"


class TestSandboxDeclarativeConfigResourceFields:
    """New cpu / memory / image fields."""

    def test_cpu_memory_set(self) -> None:
        cfg = SandboxDeclarativeConfig(cpu=2, memory=512)
        assert cfg.cpu == 2
        assert cfg.memory == 512

    def test_cpu_memory_from_dict(self) -> None:
        cfg = SandboxDeclarativeConfig.from_dict({"cpu": 4, "memory": 1024})
        assert cfg.cpu == 4
        assert cfg.memory == 1024

    def test_image_field_accepts_object(self) -> None:
        """image field accepts any object (duck-typed Image)."""
        sentinel = object()
        cfg = SandboxDeclarativeConfig(image=sentinel)
        assert cfg.image is sentinel

    def test_image_excluded_from_dict_export(self) -> None:
        """image is excluded from model_dump (not serialisable)."""
        cfg = SandboxDeclarativeConfig(image=object())
        data = cfg.model_dump()
        assert "image" not in data

    @pytest.fixture(autouse=True)
    def _check_yaml(self) -> None:
        pytest.importorskip("yaml")

    def test_cpu_memory_from_yaml(self, tmp_path: Path) -> None:
        import textwrap as tw
        yaml_content = tw.dedent("""\
            template: gpu-base
            cpu: 8
            memory: 2048
        """)
        p = tmp_path / "sandbox.yaml"
        p.write_text(yaml_content)
        cfg = SandboxDeclarativeConfig.from_file(p)
        assert cfg.template == "gpu-base"
        assert cfg.cpu == 8
        assert cfg.memory == 2048
