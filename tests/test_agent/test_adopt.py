"""Tests for adapting an existing project (``ebx template init --adopt``).

The agent is never executed here.  Staging, validation and promote are
deterministic; a misbehaving writer is simulated by editing the staging
directory directly.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from easy_sandbox.agent.adopt import (
    GENERATED_DOCKERIGNORE,
    RESERVED_FILES,
    AdoptPlan,
    AdoptRejectedError,
    Preflight,
    assert_adoptable,
    default_template_name,
    plan_from_staging,
    preflight,
    promote,
    stage_project,
    validate_template_name,
)
from easy_sandbox.models.errors import AICodegenError
from easy_sandbox.utils.dockerignore import DockerIgnore

COMMANDS = """\
from easy_sandbox.server import CommandRegistry, SandboxServer

registry = CommandRegistry()
registry.freeze()
SandboxServer(registry=registry).serve(port=9000)
"""

DOCKER = """\
FROM python:3.12-slim
COPY *.whl /tmp/
RUN pip install --no-cache-dir easy-sandbox
WORKDIR /app
COPY commands.py .
COPY app.py .
EXPOSE 9000
CMD ["python3", "commands.py"]
"""

YAML = """\
name: ignored
version: "1.0.0"
description: demo
capabilities: [shell, files, ports]
ports: [9000]
resources:
  cpu: 1
  memory: 512
"""


def _project(tmp_path: Path, name: str = "app") -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (project / "README.md").write_text("hello\n", encoding="utf-8")
    return project


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode())
        if path.is_symlink():
            digest.update(b"link")
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_agent_output(staging: Path) -> None:
    (staging / "Dockerfile").write_text(DOCKER, encoding="utf-8")
    (staging / "commands.py").write_text(COMMANDS, encoding="utf-8")
    (staging / "template.yaml").write_text(YAML, encoding="utf-8")


def _hashes(project: Path) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for name in RESERVED_FILES:
        path = project / name
        found[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return found


class TestGuards:
    def test_rejects_home_root_and_ebx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(AdoptRejectedError, match="home"):
            assert_adoptable(Path.home())
        with pytest.raises(AdoptRejectedError, match="root"):
            assert_adoptable(Path("/"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        secret = tmp_path / ".ebx" / "generated"
        secret.mkdir(parents=True)
        with pytest.raises(AdoptRejectedError, match="credentials"):
            assert_adoptable(secret)

    def test_chinese_directory_requires_an_explicit_name(self, tmp_path: Path) -> None:
        project = tmp_path / "沙箱"
        project.mkdir()
        with pytest.raises(AdoptRejectedError, match="--name"):
            default_template_name(project)

    def test_name_pattern(self) -> None:
        assert validate_template_name("my-app") == "my-app"
        with pytest.raises(AdoptRejectedError):
            validate_template_name("My App")


class TestStaging:
    def test_excludes_secrets_symlinks_binaries_and_keeps_examples(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / ".env").write_text("TOKEN=real-value-here\n", encoding="utf-8")
        (project / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        (project / "key.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n", encoding="utf-8")
        (project / "settings.py").write_text('password = "placeholder-value"\n', encoding="utf-8")
        (project / "blob.bin").write_bytes(b"\x00\x01")
        (project / "link.py").symlink_to(project / "app.py")
        (project / "node_modules").mkdir()
        (project / "node_modules" / "left.txt").write_text("nope\n", encoding="utf-8")

        staged = stage_project(project, staging_root=tmp_path / "stage")
        try:
            assert "app.py" in staged.copied
            assert ".env.example" in staged.copied
            assert ".env" not in staged.copied
            assert "key.pem" not in staged.copied
            assert "settings.py" not in staged.copied
            assert "blob.bin" not in staged.copied
            assert "link.py" not in staged.copied
            assert "node_modules/left.txt" not in staged.copied
            assert ".env" in staged.excluded["secret-name"]
            assert "settings.py" in staged.excluded["secret-content"]
            assert (staged.staging_dir / "app.py").read_text(encoding="utf-8") == "print('hi')\n"
            assert staged.manifest["app.py"] == hashlib.sha256(b"print('hi')\n").hexdigest()
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)

    def test_budget_is_a_usage_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = _project(tmp_path)
        monkeypatch.setattr("easy_sandbox.agent.adopt.MAX_FILES", 1)
        with pytest.raises(AdoptRejectedError, match="limit") as caught:
            stage_project(project, staging_root=tmp_path / "stage")
        assert caught.value.usage is True


class TestPreflight:
    def test_existing_template_yaml_needs_force(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / "template.yaml").write_text("name: x\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match="already has template.yaml"):
            preflight(project, force=False, needs_confirm=True)

    def test_user_commands_py_needs_force_even_interactively(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / "commands.py").write_text("print(1)\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match="not an Easy Sandbox"):
            preflight(project, force=False, needs_confirm=True)

    def test_dockerfile_without_a_preview_needs_force(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match="without a preview"):
            preflight(project, force=False, needs_confirm=False)
        preflight(project, force=False, needs_confirm=True)

    def test_secret_left_in_the_build_context_fails_before_any_agent(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / ".env").write_text("A=B\n", encoding="utf-8")
        (project / ".dockerignore").write_text("*.md\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match=r"\*\*/\.env"):
            preflight(project, force=False, needs_confirm=True)

    def test_reinclude_and_dockerfile_dockerignore_are_both_checked(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / ".env").write_text("A=B\n", encoding="utf-8")
        (project / ".dockerignore").write_text("**/.env\n!.env\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match=".env"):
            preflight(project, force=False, needs_confirm=True)

        (project / ".dockerignore").write_text("**/.env\n", encoding="utf-8")
        (project / "Dockerfile.dockerignore").write_text("# nothing\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match="Dockerfile.dockerignore"):
            preflight(project, force=False, needs_confirm=True)

    def test_ignoring_wheels_is_rejected(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / ".dockerignore").write_text("*.whl\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match="whl"):
            preflight(project, force=False, needs_confirm=True)

    def test_generated_ignore_covers_secrets_and_keeps_the_wheel(self) -> None:
        compiled = DockerIgnore.from_text(GENERATED_DOCKERIGNORE)
        for path in (".env", "sub/.env", "keys/id_rsa", "a/node_modules/x"):
            assert compiled.excludes(path) is True
        assert compiled.excludes(".env.example") is False
        assert compiled.excludes("easy_sandbox-0.0.0-py3-none-any.whl") is False


class TestPlan:
    def _staged(self, project: Path, staging_root: Path) -> object:
        return stage_project(project, staging_root=staging_root)

    def test_accepts_whl_glob_and_forces_the_name(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        staged = stage_project(project, staging_root=tmp_path / "stage")
        try:
            _write_agent_output(staged.staging_dir)
            plan = plan_from_staging(project, staged, template_name="my-app", raw_output="done")
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
        assert plan.template_name == "my-app"
        assert "name: my-app" in plan.files["template.yaml"]
        assert "*.whl" in plan.files["Dockerfile"]
        assert plan.files[".dockerignore"] == GENERATED_DOCKERIGNORE
        assert plan.replaces == ()

    def test_missing_copy_source_is_rejected(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        staged = stage_project(project, staging_root=tmp_path / "stage")
        try:
            _write_agent_output(staged.staging_dir)
            docker = (staged.staging_dir / "Dockerfile").read_text(encoding="utf-8")
            (staged.staging_dir / "Dockerfile").write_text(
                docker.replace("COPY app.py .", "COPY missing.py ."), encoding="utf-8"
            )
            with pytest.raises(AICodegenError, match="missing.py"):
                plan_from_staging(project, staged, template_name="my-app", raw_output="")
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)

    def test_port_9000_must_be_exposed(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        staged = stage_project(project, staging_root=tmp_path / "stage")
        try:
            _write_agent_output(staged.staging_dir)
            yaml_text = YAML.replace("9000", "8080")
            (staged.staging_dir / "template.yaml").write_text(yaml_text, encoding="utf-8")
            with pytest.raises(AICodegenError, match="9000"):
                plan_from_staging(project, staged, template_name="my-app", raw_output="")
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)

    def test_symlink_staged_dockerfile_is_refused(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        staged = stage_project(project, staging_root=tmp_path / "stage")
        try:
            _write_agent_output(staged.staging_dir)
            docker = staged.staging_dir / "Dockerfile"
            docker.unlink()
            docker.symlink_to(staged.staging_dir / "app.py")
            before = _tree_hash(project)
            with pytest.raises(AICodegenError, match="symlink"):
                plan_from_staging(project, staged, template_name="my-app", raw_output="")
            assert _tree_hash(project) == before
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)

    def test_edits_outside_the_whitelist_are_not_applied(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        staged = stage_project(project, staging_root=tmp_path / "stage")
        try:
            _write_agent_output(staged.staging_dir)
            (staged.staging_dir / "app.py").write_text("hacked\n", encoding="utf-8")
            (staged.staging_dir / "extra.txt").write_text("nope\n", encoding="utf-8")
            plan = plan_from_staging(project, staged, template_name="my-app", raw_output="")
            assert "app.py" in plan.not_applied
            assert "extra.txt" in plan.not_applied
            promote(project, plan, Preflight(_hashes(project)))
        finally:
            shutil.rmtree(staged.staging_dir, ignore_errors=True)
        assert (project / "app.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert not (project / "extra.txt").exists()
        assert (project / "Dockerfile").is_file()
        assert (project / ".dockerignore").is_file()


class TestPromote:
    def test_backup_is_never_overwritten_and_drift_aborts(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        (project / "Dockerfile.ebx-bak").write_text("older\n", encoding="utf-8")
        state = Preflight(_hashes(project))
        plan = AdoptPlan(
            template_name="app",
            files={"Dockerfile": "FROM python:3.12-slim\n"},
            replaces=("Dockerfile",),
            not_applied=(),
            warnings=(),
        )
        result = promote(project, plan, state)
        assert (project / "Dockerfile").read_text(encoding="utf-8") == "FROM python:3.12-slim\n"
        assert (project / "Dockerfile.ebx-bak").read_text(encoding="utf-8") == "older\n"
        assert "Dockerfile.ebx-bak.1" in result.backed_up

        (project / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        fresh = Preflight(_hashes(project))
        (project / "Dockerfile").write_text("meanwhile\n", encoding="utf-8")
        with pytest.raises(AdoptRejectedError, match="changed"):
            promote(project, plan, fresh)
        assert (project / "Dockerfile").read_text(encoding="utf-8") == "meanwhile\n"

    def test_symlink_target_aborts_with_nothing_written(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        outside = tmp_path / "outside.txt"
        outside.write_text("safe\n", encoding="utf-8")
        (project / "Dockerfile").symlink_to(outside)
        plan = AdoptPlan(
            template_name="app",
            files={"Dockerfile": "FROM scratch\n"},
            replaces=(),
            not_applied=(),
            warnings=(),
        )
        with pytest.raises(AdoptRejectedError, match="symlink"):
            promote(project, plan, Preflight(_hashes(project)))
        assert outside.read_text(encoding="utf-8") == "safe\n"

    def test_failed_write_rolls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = _project(tmp_path)
        plan = AdoptPlan(
            template_name="app",
            files={"Dockerfile": "FROM scratch\n", "commands.py": COMMANDS},
            replaces=(),
            not_applied=(),
            warnings=(),
        )
        real = Path.write_text

        def _boom(self: Path, text: str, *args: object, **kwargs: object) -> int:
            if self.name == "commands.py.ebx-tmp":
                raise OSError("disk full")
            return real(self, text, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", _boom)
        before = _tree_hash(project)
        with pytest.raises(OSError, match="disk full"):
            promote(project, plan, Preflight(_hashes(project)))
        assert _tree_hash(project) == before
