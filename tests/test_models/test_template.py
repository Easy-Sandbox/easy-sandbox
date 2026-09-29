"""Tests for SandboxTemplate and TemplateRef models."""

from __future__ import annotations

from easy_sandbox.models.template import SandboxTemplate, TemplateRef


class TestSandboxTemplate:
    """Tests for SandboxTemplate model."""

    def test_minimal_template(self) -> None:
        tmpl = SandboxTemplate(name="test")
        assert tmpl.name == "test"
        assert tmpl.version == "1.0.0"
        assert tmpl.env == {}
        assert tmpl.ports == []
        assert tmpl.capabilities is None
        assert tmpl.custom_commands == {}

    def test_full_template(self) -> None:
        tmpl = SandboxTemplate(
            name="data-science",
            version="2.0.0",
            description="Data science template",
            env={"LANG": "C.UTF-8"},
            cpu_count=2,
            memory_mb=4096,
            author="test-author",
            license="MIT",
            tags=["data", "python"],
            capabilities=["shell", "files", "code"],
        )
        assert tmpl.name == "data-science"
        assert tmpl.version == "2.0.0"
        assert tmpl.cpu_count == 2
        assert tmpl.memory_mb == 4096
        assert tmpl.tags == ["data", "python"]
        assert tmpl.capabilities == ["shell", "files", "code"]

    def test_extra_fields_ignored(self) -> None:
        """Legacy build fields (base, system_packages, etc.) are silently ignored."""
        tmpl = SandboxTemplate(
            name="test",
            base="python:3.11",  # type: ignore[call-arg]
            system_packages=["git"],  # type: ignore[call-arg]
            python_packages=["flask"],  # type: ignore[call-arg]
        )
        assert tmpl.name == "test"
        # extra fields are silently dropped by model_config = {"extra": "ignore"}
        assert not hasattr(tmpl, "base")
        assert not hasattr(tmpl, "system_packages")


class TestTemplateRef:
    """Tests for TemplateRef model."""

    def test_default(self) -> None:
        ref = TemplateRef()
        assert ref.owner is None
        assert ref.repo is None
        assert ref.tag is None
        assert ref.path is None
        assert ref.is_builtin is False
        assert ref.registry_url == "https://github.com"
        assert ref.registry_type == "github"
        assert ref.local_path is None

    def test_builtin(self) -> None:
        ref = TemplateRef(is_builtin=True, tag="base")
        assert ref.is_builtin is True
        assert ref.tag == "base"
        assert ref.path is None

    def test_github_ref(self) -> None:
        ref = TemplateRef(
            owner="org",
            repo="sandbox-templates",
            tag="v1.0",
            registry_url="https://github.com",
        )
        assert ref.owner == "org"
        assert ref.repo == "sandbox-templates"
        assert ref.tag == "v1.0"
        assert ref.path is None
        assert ref.is_builtin is False

    def test_path_field(self) -> None:
        """path 字段应正确存储子目录信息。"""
        ref = TemplateRef(
            owner="demo",
            repo="demo",
            tag="v1.0",
            path="templates/python-data",
        )
        assert ref.owner == "demo"
        assert ref.repo == "demo"
        assert ref.tag == "v1.0"
        assert ref.path == "templates/python-data"
        assert ref.is_builtin is False

    def test_path_field_default_none(self) -> None:
        """path 字段默认为 None。"""
        ref = TemplateRef(owner="a", repo="b")
        assert ref.path is None

    def test_path_with_nested_dirs(self) -> None:
        """深层子目录路径。"""
        ref = TemplateRef(
            owner="org",
            repo="templates",
            path="a/b/c/d",
        )
        assert ref.path == "a/b/c/d"

    def test_registry_type_default(self) -> None:
        """registry_type 默认值为 github。"""
        ref = TemplateRef()
        assert ref.registry_type == "github"

    def test_registry_type_local(self) -> None:
        """registry_type 可设为 local。"""
        ref = TemplateRef(registry_type="local", local_path="/tmp/my-template")
        assert ref.registry_type == "local"
        assert ref.local_path == "/tmp/my-template"

    def test_local_path_default_none(self) -> None:
        """local_path 默认为 None。"""
        ref = TemplateRef()
        assert ref.local_path is None

    def test_local_ref_full(self) -> None:
        """完整的本地模板引用。"""
        ref = TemplateRef(
            registry_type="local",
            local_path="/home/user/templates/python",
            is_builtin=False,
        )
        assert ref.registry_type == "local"
        assert ref.local_path == "/home/user/templates/python"
        assert ref.is_builtin is False
        assert ref.owner is None
        assert ref.repo is None
