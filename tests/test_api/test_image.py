"""Tests for api.image module — Image chain builder."""
from __future__ import annotations

import pytest

from easy_sandbox.api.image import Image


class TestImageFromTemplate:
    """Test Image.from_template() constructor."""

    def test_from_template(self) -> None:
        img = Image.from_template("python-base")
        assert img._from_template == "python-base"
        assert img._base == "python-base"

    def test_from_template_dockerfile(self) -> None:
        img = Image.from_template("python-base")
        dockerfile = img.to_dockerfile()
        assert dockerfile.startswith("FROM python-base")


class TestImageFromImage:
    """Test Image.from_image() constructor."""

    def test_from_image(self) -> None:
        img = Image.from_image("python:3.11-slim")
        assert img._base == "python:3.11-slim"

    def test_from_image_dockerfile(self) -> None:
        img = Image.from_image("ubuntu:22.04")
        dockerfile = img.to_dockerfile()
        assert dockerfile == "FROM ubuntu:22.04"


class TestImageChaining:
    """Test chain method calls."""

    def test_pip_install(self) -> None:
        img = Image.from_image("python:3.11")
        result = img.pip_install("flask", "sqlalchemy")
        assert result is img  # returns self for chaining
        assert "RUN pip install --no-cache-dir flask sqlalchemy" in img._steps

    def test_pip_install_empty(self) -> None:
        img = Image.from_image("python:3.11")
        result = img.pip_install()
        assert len(img._steps) == 0

    def test_apt_install(self) -> None:
        img = Image.from_image("ubuntu:22.04")
        result = img.apt_install("curl", "git")
        assert result is img
        assert any("apt-get install -y curl git" in s for s in img._steps)

    def test_apt_install_empty(self) -> None:
        img = Image.from_image("ubuntu:22.04")
        result = img.apt_install()
        assert len(img._steps) == 0

    def test_copy_local(self) -> None:
        img = Image()
        result = img.copy_local("./src", "/app/src")
        assert result is img
        assert "COPY ./src /app/src" in img._steps

    def test_env(self) -> None:
        img = Image()
        result = img.env(APP_ENV="prod", DEBUG="0")
        assert result is img
        assert img._envs == {"APP_ENV": "prod", "DEBUG": "0"}

    def test_env_chained(self) -> None:
        img = Image()
        img.env(A="1").env(B="2")
        assert img._envs == {"A": "1", "B": "2"}

    def test_run_command(self) -> None:
        img = Image()
        result = img.run_command("echo hello")
        assert result is img
        assert "RUN echo hello" in img._steps

    def test_workdir(self) -> None:
        img = Image()
        result = img.workdir("/app")
        assert result is img
        assert img._workdir == "/app"

    def test_expose(self) -> None:
        img = Image()
        result = img.expose(3000, 8080)
        assert result is img
        assert img._exposed_ports == [3000, 8080]

    def test_entrypoint(self) -> None:
        img = Image()
        result = img.entrypoint("python app.py")
        assert result is img
        assert img._entrypoint == "python app.py"


class TestImageToDockerfile:
    """Test Image.to_dockerfile()."""

    def test_minimal(self) -> None:
        img = Image()
        dockerfile = img.to_dockerfile()
        assert dockerfile == "FROM ubuntu:22.04"

    def test_full_chain(self) -> None:
        img = (
            Image.from_image("python:3.11-slim")
            .apt_install("curl", "git")
            .pip_install("flask", "sqlalchemy")
            .copy_local("./app", "/app")
            .run_command("echo 'setup done'")
            .env(FLASK_ENV="production", PORT="5000")
            .workdir("/app")
            .expose(5000)
            .entrypoint("python main.py")
        )
        dockerfile = img.to_dockerfile()
        lines = dockerfile.split("\n")

        assert lines[0] == "FROM python:3.11-slim"
        assert any("apt-get install -y curl git" in l for l in lines)
        assert any("pip install --no-cache-dir flask sqlalchemy" in l for l in lines)
        assert any("COPY ./app /app" in l for l in lines)
        assert any("RUN echo 'setup done'" in l for l in lines)
        assert any("ENV FLASK_ENV=production" in l for l in lines)
        assert any("ENV PORT=5000" in l for l in lines)
        assert any("WORKDIR /app" in l for l in lines)
        assert any("EXPOSE 5000" in l for l in lines)
        assert any("CMD python main.py" in l for l in lines)

    def test_order_of_directives(self) -> None:
        """FROM comes first, ENV after steps, WORKDIR/EXPOSE/CMD at end."""
        img = (
            Image.from_image("alpine")
            .run_command("echo 1")
            .env(A="1")
            .workdir("/w")
            .expose(80)
            .entrypoint("sh")
        )
        lines = img.to_dockerfile().split("\n")
        assert lines[0] == "FROM alpine"
        # RUN is before ENV
        run_idx = next(i for i, l in enumerate(lines) if "RUN" in l)
        env_idx = next(i for i, l in enumerate(lines) if "ENV" in l)
        workdir_idx = next(i for i, l in enumerate(lines) if "WORKDIR" in l)
        assert run_idx < env_idx
        assert env_idx < workdir_idx


class TestImageRepr:
    """Test Image.__repr__()."""

    def test_repr(self) -> None:
        img = Image.from_image("python:3.11").pip_install("flask").env(X="1")
        r = repr(img)
        assert "python:3.11" in r
        assert "steps=1" in r
        assert "envs=1" in r
