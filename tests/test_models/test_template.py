"""Tests for SandboxTemplate and TemplateRef models."""
from __future__ import annotations

import pytest

from serverless_sandbox.models.template import SandboxTemplate, TemplateRef


class TestSandboxTemplate:
    """Tests for SandboxTemplate model."""

    def test_minimal_template(self) -> None:
        tmpl = SandboxTemplate(name="test")
        assert tmpl.name == "test"
        assert tmpl.version == "1.0.0"
        assert tmpl.base == "ubuntu:22.04"
        assert tmpl.system_packages == []
        assert tmpl.python_packages == []
        assert tmpl.node_packages == []
        assert tmpl.commands == []
        assert tmpl.env == {}
        assert tmpl.copy_files == {}

    def test_full_template(self) -> None:
        tmpl = SandboxTemplate(
            name="data-science",
            version="2.0.0",
            description="Data science template",
            base="python:3.11",
            system_packages=["git", "curl"],
            python_packages=["pandas", "numpy"],
            node_packages=["typescript"],
            commands=["echo hello"],
            env={"LANG": "C.UTF-8"},
            copy_files={"requirements.txt": "/app/requirements.txt"},
            cpu_count=2,
            memory_mb=4096,
            author="test-author",
            license="MIT",
            tags=["data", "python"],
        )
        assert tmpl.name == "data-science"
        assert tmpl.version == "2.0.0"
        assert tmpl.cpu_count == 2
        assert tmpl.memory_mb == 4096
        assert tmpl.tags == ["data", "python"]

    def test_to_dockerfile_minimal(self) -> None:
        tmpl = SandboxTemplate(name="test")
        dockerfile = tmpl.to_dockerfile()
        assert dockerfile == "FROM ubuntu:22.04"

    def test_to_dockerfile_system_packages(self) -> None:
        tmpl = SandboxTemplate(name="test", system_packages=["git", "curl"])
        dockerfile = tmpl.to_dockerfile()
        assert "FROM ubuntu:22.04" in dockerfile
        assert "apt-get update && apt-get install -y git curl" in dockerfile
        assert "rm -rf /var/lib/apt/lists/*" in dockerfile

    def test_to_dockerfile_python_packages(self) -> None:
        tmpl = SandboxTemplate(name="test", python_packages=["pandas", "numpy"])
        dockerfile = tmpl.to_dockerfile()
        assert "pip install --no-cache-dir pandas numpy" in dockerfile

    def test_to_dockerfile_node_packages(self) -> None:
        tmpl = SandboxTemplate(name="test", node_packages=["typescript"])
        dockerfile = tmpl.to_dockerfile()
        assert "npm install -g typescript" in dockerfile

    def test_to_dockerfile_commands(self) -> None:
        tmpl = SandboxTemplate(name="test", commands=["echo hello", "mkdir /data"])
        dockerfile = tmpl.to_dockerfile()
        assert "RUN echo hello" in dockerfile
        assert "RUN mkdir /data" in dockerfile

    def test_to_dockerfile_env(self) -> None:
        tmpl = SandboxTemplate(name="test", env={"LANG": "C.UTF-8"})
        dockerfile = tmpl.to_dockerfile()
        assert "ENV LANG=C.UTF-8" in dockerfile

    def test_to_dockerfile_copy_files(self) -> None:
        tmpl = SandboxTemplate(
            name="test",
            copy_files={"app.py": "/app/app.py"},
        )
        dockerfile = tmpl.to_dockerfile()
        assert "COPY app.py /app/app.py" in dockerfile

    def test_to_dockerfile_full(self) -> None:
        tmpl = SandboxTemplate(
            name="full-test",
            base="python:3.11",
            system_packages=["git"],
            python_packages=["flask"],
            node_packages=["prettier"],
            commands=["echo done"],
            env={"APP_ENV": "prod"},
            copy_files={"src": "/app"},
        )
        dockerfile = tmpl.to_dockerfile()
        lines = dockerfile.split("\n")
        assert lines[0] == "FROM python:3.11"
        assert any("apt-get" in l for l in lines)
        assert any("pip install" in l for l in lines)
        assert any("npm install" in l for l in lines)
        assert any("RUN echo done" in l for l in lines)
        assert any("ENV APP_ENV=prod" in l for l in lines)
        assert any("COPY src /app" in l for l in lines)


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
