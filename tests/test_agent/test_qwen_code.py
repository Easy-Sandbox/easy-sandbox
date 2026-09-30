"""Unit tests for the host-side Qwen Code adapter.

No test performs real network access or executes the real CLI: downloads
are monkeypatched and subprocess runs are faked.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from easy_sandbox.agent import qwen_code
from easy_sandbox.agent.qwen_code import (
    detect_standalone_target,
    find_qwen_code_binary,
    official_install_command,
    resolve_qwen_code_credentials,
    run_qwen_code_headless,
    standalone_asset_name,
    standalone_download_urls,
)
from easy_sandbox.models.errors import (
    AICodegenError,
    QwenCodeCredentialError,
    QwenCodeNotInstalledError,
    QwenCodeTimeoutError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tar_gz_bytes(target: str) -> bytes:
    """Build a minimal archive matching the official tar.gz layout."""
    buf = io.BytesIO()
    entry = qwen_code._entry_relative_path(target)
    node = qwen_code._node_relative_path(target)
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, content in ((entry, b"#!/bin/sh\necho qwen\n"), (node, b"node-binary")):
            info = tarfile.TarInfo(str(rel))
            info.size = len(content)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _zip_bytes(target: str) -> bytes:
    """Build a minimal archive matching the official win-x64 zip layout."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(str(qwen_code._entry_relative_path(target)), "@echo off\r\n")
        zf.writestr(str(qwen_code._node_relative_path(target)), "node")
    return buf.getvalue()


def _patch_network(
    monkeypatch: pytest.MonkeyPatch,
    archive: bytes,
    *,
    digest: str | None = None,
    checksum_text: str | None = None,
) -> None:
    asset_digest = digest if digest is not None else _sha256(archive)
    seen: dict[str, str] = {}

    def _download(url: str, dest: Path, *, timeout: float) -> None:
        # The archive download URL ends with the release asset name; the
        # later SHA256SUMS request does not, so remember it here.
        seen["asset"] = url.rsplit("/", 1)[-1]
        dest.write_bytes(archive)

    def _get_text(url: str, *, timeout: float) -> str:
        if checksum_text is not None:
            return checksum_text
        return f"{asset_digest}  {seen['asset']}\n"

    monkeypatch.setattr(qwen_code, "_download_to_file", _download)
    monkeypatch.setattr(qwen_code, "_http_get_text", _get_text)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


class TestPlatformDetection:
    def test_darwin_variants(self) -> None:
        assert detect_standalone_target(system="Darwin", machine="arm64") == "darwin-arm64"
        assert detect_standalone_target(system="Darwin", machine="x86_64") == "darwin-x64"

    def test_linux_variants(self) -> None:
        assert detect_standalone_target(system="Linux", machine="x86_64") == "linux-x64"
        assert detect_standalone_target(system="Linux", machine="aarch64") == "linux-arm64"

    def test_windows_x64(self) -> None:
        assert detect_standalone_target(system="Windows", machine="AMD64") == "win-x64"

    def test_windows_arm64_unsupported(self) -> None:
        # Verified: the official release matrix has no win-arm64 asset.
        assert detect_standalone_target(system="Windows", machine="ARM64") is None

    def test_unknown_platform_or_arch(self) -> None:
        assert detect_standalone_target(system="FreeBSD", machine="x86_64") is None
        assert detect_standalone_target(system="Linux", machine="riscv64") is None


class TestAssetNaming:
    def test_unix_tarball(self) -> None:
        assert standalone_asset_name("darwin-arm64") == "qwen-code-darwin-arm64.tar.gz"
        assert standalone_asset_name("linux-x64") == "qwen-code-linux-x64.tar.gz"

    def test_windows_zip(self) -> None:
        assert standalone_asset_name("win-x64") == "qwen-code-win-x64.zip"

    def test_unknown_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            standalone_asset_name("win-arm64")

    def test_mirror_order_and_urls(self) -> None:
        urls = standalone_download_urls("darwin-arm64")
        labels = [label for label, _ in urls]
        assert labels == ["aliyun", "github"]
        assert urls[0][1] == (
            "https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/releases/qwen-code/"
            "latest/qwen-code-darwin-arm64.tar.gz"
        )
        assert urls[1][1] == (
            "https://github.com/QwenLM/qwen-code/releases/latest/download/"
            "qwen-code-darwin-arm64.tar.gz"
        )

    def test_official_install_command(self) -> None:
        assert "install-qwen-standalone.sh" in official_install_command(windows=False)
        assert "install-qwen-standalone.ps1" in official_install_command(windows=True)


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


class TestFindBinary:
    def test_env_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = tmp_path / "custom-qwen"
        exe.write_text("#!/bin/sh\n")
        monkeypatch.setenv("EBX_QWEN_CODE_BIN", str(exe))
        assert find_qwen_code_binary(bin_dir=tmp_path / "empty") == exe

    def test_env_override_missing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EBX_QWEN_CODE_BIN", str(tmp_path / "missing"))
        assert find_qwen_code_binary(bin_dir=tmp_path / "empty") is None

    def test_managed_dir_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EBX_QWEN_CODE_BIN", raising=False)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        managed = bin_dir / "qwen"
        managed.write_text("#!/bin/sh\n")
        managed.chmod(0o755)
        with patch("easy_sandbox.agent.qwen_code.shutil.which", return_value=None):
            assert find_qwen_code_binary(bin_dir=bin_dir) == managed

    def test_managed_dir_skips_non_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EBX_QWEN_CODE_BIN", raising=False)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "qwen").write_text("not executable")
        with patch("easy_sandbox.agent.qwen_code.shutil.which", return_value=None):
            assert find_qwen_code_binary(bin_dir=bin_dir) is None

    def test_windows_cmd_name(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EBX_QWEN_CODE_BIN", raising=False)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "qwen.cmd").write_text("@echo off\n")
        assert find_qwen_code_binary(bin_dir=bin_dir, windows=True) == bin_dir / "qwen.cmd"

    def test_path_lookup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EBX_QWEN_CODE_BIN", raising=False)
        found = tmp_path / "usr-bin-qwen"
        with patch("easy_sandbox.agent.qwen_code.shutil.which", return_value=str(found)):
            assert find_qwen_code_binary(bin_dir=tmp_path / "empty") == found


# ---------------------------------------------------------------------------
# Checksum parsing
# ---------------------------------------------------------------------------


class TestChecksumParsing:
    def test_parses_star_prefix_and_ignores_junk(self) -> None:
        text = (
            f"{'a' * 64}  qwen-code-linux-x64.tar.gz\n"
            f"{'b' * 64} *qwen-code-win-x64.zip\n"
            "not-a-checksum-line\n"
            f"{'z' * 64}  invalid-hex\n"
        )
        sums = qwen_code._parse_sha256sums(text)
        assert sums["qwen-code-linux-x64.tar.gz"] == "a" * 64
        assert sums["qwen-code-win-x64.zip"] == "b" * 64
        assert len(sums) == 2


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


class TestDownloadAndInstall:
    def test_installs_verified_unix_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = tmp_path / "bin"
        archive = _tar_gz_bytes("darwin-arm64")
        _patch_network(monkeypatch, archive)

        wrapper = qwen_code.download_and_install_standalone(target="darwin-arm64", bin_dir=bin_dir)

        assert wrapper == bin_dir / "qwen"
        assert wrapper.is_file()
        assert os.access(wrapper, os.X_OK)
        content = wrapper.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env sh")
        assert "qwen-code/bin/qwen" in content
        entry = bin_dir / "qwen-code" / "bin" / "qwen"
        assert entry.is_file()
        assert os.access(entry, os.X_OK)
        # Staging leftovers are cleaned up.
        assert not (bin_dir / ".qwen-code-staging").exists()

    def test_installs_windows_zip_with_cmd_wrapper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = tmp_path / "bin"
        archive = _zip_bytes("win-x64")
        _patch_network(monkeypatch, archive)

        wrapper = qwen_code.download_and_install_standalone(target="win-x64", bin_dir=bin_dir)

        assert wrapper.name == "qwen.cmd"
        assert wrapper.read_text(encoding="utf-8").lower().startswith("@echo off")
        assert "call" in wrapper.read_text(encoding="utf-8").lower()

    def test_checksum_mismatch_aborts_without_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bin_dir = tmp_path / "bin"
        archive = _tar_gz_bytes("linux-x64")
        asset = standalone_asset_name("linux-x64")
        downloads: list[str] = []

        def _download(url: str, dest: Path, *, timeout: float) -> None:
            downloads.append(url)
            dest.write_bytes(archive)

        monkeypatch.setattr(qwen_code, "_download_to_file", _download)
        monkeypatch.setattr(
            qwen_code,
            "_http_get_text",
            lambda url, *, timeout: f"{'0' * 64}  {asset}\n",
        )

        with pytest.raises(QwenCodeNotInstalledError, match="integrity"):
            qwen_code.download_and_install_standalone(target="linux-x64", bin_dir=bin_dir)

        # The mismatch must not trigger a silent retry with the second mirror.
        assert len(downloads) == 1
        assert not (bin_dir / "qwen").exists()

    def test_aliyun_failure_falls_back_to_github(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _tar_gz_bytes("linux-x64")
        digest = _sha256(archive)
        asset = standalone_asset_name("linux-x64")
        downloads: list[str] = []

        def _download(url: str, dest: Path, *, timeout: float) -> None:
            downloads.append(url)
            if "aliyuncs.com" in url:
                raise OSError("network down")
            dest.write_bytes(archive)

        monkeypatch.setattr(qwen_code, "_download_to_file", _download)
        monkeypatch.setattr(
            qwen_code,
            "_http_get_text",
            lambda url, *, timeout: f"{digest}  {asset}\n",
        )

        wrapper = qwen_code.download_and_install_standalone(
            target="linux-x64", bin_dir=tmp_path / "bin"
        )

        assert "github.com" in downloads[-1]
        assert wrapper.is_file()

    def test_all_mirrors_failing_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(url: str, dest: Path, *, timeout: float) -> None:
            raise OSError("no network")

        monkeypatch.setattr(qwen_code, "_download_to_file", _boom)

        with pytest.raises(QwenCodeNotInstalledError, match="all official mirrors"):
            qwen_code.download_and_install_standalone(target="linux-x64", bin_dir=tmp_path / "bin")

    def test_missing_checksum_entry_never_installs_unverified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _tar_gz_bytes("linux-x64")
        _patch_network(monkeypatch, archive, checksum_text="deadbeef  other-file\n")

        with pytest.raises(QwenCodeNotInstalledError, match="all official mirrors"):
            qwen_code.download_and_install_standalone(target="linux-x64", bin_dir=tmp_path / "bin")

    def test_rejects_path_traversal_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            payload = b"x"
            info = tarfile.TarInfo("../evil.txt")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        archive = buf.getvalue()
        _patch_network(monkeypatch, archive)

        bin_dir = tmp_path / "bin"
        with pytest.raises(QwenCodeNotInstalledError):
            qwen_code.download_and_install_standalone(target="linux-x64", bin_dir=bin_dir)

        assert not (tmp_path / "evil.txt").exists()

    def test_unexpected_layout_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            payload = b"hi"
            info = tarfile.TarInfo("qwen-code/README.md")
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        archive = buf.getvalue()
        _patch_network(monkeypatch, archive)

        with pytest.raises(QwenCodeNotInstalledError, match="all official mirrors"):
            qwen_code.download_and_install_standalone(target="linux-x64", bin_dir=tmp_path / "bin")

    def test_unsupported_platform_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "detect_standalone_target", lambda **kw: None)
        with pytest.raises(QwenCodeNotInstalledError, match="No official"):
            qwen_code.download_and_install_standalone(bin_dir=tmp_path / "bin")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_stored_key_wins_over_llm_key(self, tmp_path: Path) -> None:
        creds = resolve_qwen_code_credentials(
            stored_api_key="sk-stored",
            llm_api_key="sk-llm",
            environ={},
            settings_path=tmp_path / "absent.json",
        )
        assert creds.source == "qwen-stored"
        env = creds.as_env()
        assert env["OPENAI_API_KEY"] == "sk-stored"
        assert env["OPENAI_BASE_URL"] == qwen_code._DEFAULT_OPENAI_BASE_URL
        assert env["OPENAI_MODEL"] == qwen_code._DEFAULT_OPENAI_MODEL

    def test_llm_api_key_fallback_is_compatible(self, tmp_path: Path) -> None:
        creds = resolve_qwen_code_credentials(
            stored_api_key=None,
            llm_api_key="sk-llm",
            environ={},
            settings_path=tmp_path / "absent.json",
        )
        assert creds.source == "llm-stored"
        assert creds.as_env()["OPENAI_API_KEY"] == "sk-llm"

    def test_custom_base_url_and_model(self, tmp_path: Path) -> None:
        creds = resolve_qwen_code_credentials(
            stored_api_key="sk",
            stored_base_url="https://example.test/v1",
            stored_model="my-model",
            environ={},
            settings_path=tmp_path / "absent.json",
        )
        assert creds.as_env() == {
            "OPENAI_API_KEY": "sk",
            "OPENAI_BASE_URL": "https://example.test/v1",
            "OPENAI_MODEL": "my-model",
        }

    def test_environment_key_needs_no_injection(self, tmp_path: Path) -> None:
        creds = resolve_qwen_code_credentials(
            environ={"OPENAI_API_KEY": "sk-env"},
            settings_path=tmp_path / "absent.json",
        )
        assert creds.source == "environment"
        assert creds.as_env() == {}

    def test_dashscope_env_recognized(self, tmp_path: Path) -> None:
        creds = resolve_qwen_code_credentials(
            environ={"DASHSCOPE_API_KEY": "sk-dash"},
            settings_path=tmp_path / "absent.json",
        )
        assert creds.source == "environment"
        assert creds.as_env() == {}

    def test_qwen_settings_file_recognized(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"modelProviders": {"openai": {}}}), encoding="utf-8")
        creds = resolve_qwen_code_credentials(environ={}, settings_path=settings)
        assert creds.source == "qwen-settings"
        assert creds.as_env() == {}

    def test_missing_credentials_raise(self, tmp_path: Path) -> None:
        with pytest.raises(QwenCodeCredentialError, match="no model credentials"):
            resolve_qwen_code_credentials(environ={}, settings_path=tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# Headless command + execution
# ---------------------------------------------------------------------------


class TestHeadlessCommand:
    def test_posix_argv_uses_list_not_shell(self) -> None:
        argv = qwen_code._build_headless_command(Path("/usr/local/bin/qwen"), "hi", windows=False)
        assert argv == ["/usr/local/bin/qwen", "hi", "--output-format", "json", "--yolo"]

    def test_prompt_travels_as_positional_not_deprecated_flag(self) -> None:
        """The prompt is positional; the deprecated ``-p`` flag must not appear."""
        argv = qwen_code._build_headless_command(Path("/usr/local/bin/qwen"), "hi", windows=False)
        assert argv[1] == "hi"
        assert "-p" not in argv

    def test_windows_cmd_wrapped_with_comspec(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COMSPEC", "cmd.exe")
        argv = qwen_code._build_headless_command(Path("qwen.cmd"), "hi", windows=True)
        assert argv[0] == "cmd.exe"
        assert argv[1] == "/c"
        assert argv[2] == "qwen.cmd"

    def test_max_session_turns_default_adds_no_flag(self) -> None:
        """Without a turn budget the argv keeps the minimal headless flags."""
        argv = qwen_code._build_headless_command(Path("/usr/local/bin/qwen"), "hi", windows=False)
        assert argv == ["/usr/local/bin/qwen", "hi", "--output-format", "json", "--yolo"]

    def test_max_session_turns_forwarded_as_official_flag(self) -> None:
        """A turn budget travels as the official ``--max-session-turns`` flag."""
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"), "hi", max_session_turns=30, windows=False
        )
        assert argv == [
            "/usr/local/bin/qwen",
            "hi",
            "--output-format",
            "json",
            "--yolo",
            "--max-session-turns",
            "30",
        ]

    def test_session_id_flag_forwarded(self) -> None:
        """The first clarification round pins the native session via --session-id."""
        session = "6f0f8e9a-1b2c-4d5e-8f90-123456789abc"
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"), "hi", session_id=session, windows=False
        )
        assert argv == [
            "/usr/local/bin/qwen",
            "hi",
            "--output-format",
            "json",
            "--yolo",
            "--session-id",
            session,
        ]

    def test_resume_wins_over_session_id(self) -> None:
        """The CLI rejects both session flags; --resume takes precedence."""
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"),
            "hi",
            session_id="6f0f8e9a-1b2c-4d5e-8f90-123456789abc",
            resume="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            windows=False,
        )
        assert "--session-id" not in argv
        assert argv[-2:] == ["--resume", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]

    def test_json_schema_mapping_dumped_as_json_literal(self) -> None:
        schema = {"type": "object", "properties": {"completeness": {"type": "number"}}}
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"), "hi", json_schema=schema, windows=False
        )
        assert argv[-2] == "--json-schema"
        assert json.loads(argv[-1]) == schema

    def test_json_schema_string_passed_through(self) -> None:
        """The CLI also accepts an @path reference; strings are not re-encoded."""
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"), "hi", json_schema="@/tmp/schema.json", windows=False
        )
        assert argv[-2:] == ["--json-schema", "@/tmp/schema.json"]

    def test_native_session_flags_combine_with_turn_budget(self) -> None:
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"),
            "hi",
            max_session_turns=3,
            resume="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            json_schema={"type": "object"},
            windows=False,
        )
        assert argv[-2:] == ["--max-session-turns", "3"]
        assert argv[-4:-2] == ["--resume", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
        assert argv[-6] == "--json-schema"
        assert json.loads(argv[-5]) == {"type": "object"}


class _FakeProc:
    """Minimal ``Popen`` stand-in for the blocking (json) path."""

    def __init__(
        self,
        completed: subprocess.CompletedProcess[str] | None,
        *,
        timeout_on_communicate: bool = False,
    ) -> None:
        self.completed = completed
        self.pid = 4242
        self.returncode = completed.returncode if completed is not None else -9
        self.communicate_timeout: float | None = None
        self._timeout_once = timeout_on_communicate

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_timeout = timeout
        if self._timeout_once:
            self._timeout_once = False
            raise subprocess.TimeoutExpired(cmd="qwen", timeout=timeout or 0.0)
        if self.completed is None:
            return "", ""
        return self.completed.stdout, self.completed.stderr


def _fake_spawn(completed: subprocess.CompletedProcess[str]):  # type: ignore[no-untyped-def]
    def _spawn(argv: list[str], **kwargs: object) -> _FakeProc:
        return _FakeProc(completed)

    return _spawn


class TestRunHeadless:
    def test_parses_result_message_and_passes_bounded_options(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        stdout = json.dumps(
            [
                {"type": "assistant", "content": "working"},
                {"type": "result", "result": "all done", "is_error": False},
            ]
        )
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        captured: dict[str, object] = {}
        procs: list[_FakeProc] = []

        def _fake_run(argv: list[str], **kwargs: object) -> _FakeProc:
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            proc = _FakeProc(completed)
            procs.append(proc)
            return proc

        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_run)

        result = run_qwen_code_headless("hello", cwd=tmp_path, timeout=12.0)

        assert result.exit_code == 0
        assert result.is_error is False
        assert result.text == "all done"
        argv = captured["argv"]
        assert isinstance(argv, list)
        assert argv[:2] == ["/fake/qwen", "hello"]
        assert "-p" not in argv
        assert "--output-format" in argv
        assert "--yolo" in argv
        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
        assert kwargs["cwd"] == tmp_path
        assert procs[0].communicate_timeout == 12.0

    def test_max_session_turns_forwarded_to_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``run_qwen_code_headless`` forwards the turn budget to the CLI argv."""
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        stdout = json.dumps([{"type": "result", "result": "ok", "is_error": False}])
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        captured: dict[str, object] = {}

        def _fake_run(argv: list[str], **kwargs: object) -> _FakeProc:
            captured["argv"] = argv
            return _FakeProc(completed)

        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_run)

        run_qwen_code_headless("hello", cwd=tmp_path, max_session_turns=42)

        argv = captured["argv"]
        assert isinstance(argv, list)
        assert argv[-2:] == ["--max-session-turns", "42"]

    def test_structured_result_and_session_id_parsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A --json-schema run exposes structured_result + session_id."""
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        payload = {"completeness": 0.9, "question": "", "missing": [], "example": "x"}
        stdout = json.dumps(
            [
                {"type": "assistant", "content": "thinking"},
                {
                    "type": "result",
                    "result": json.dumps(payload),
                    "is_error": False,
                    "structured_result": payload,
                    "session_id": "6f0f8e9a-1b2c-4d5e-8f90-123456789abc",
                },
            ]
        )
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_spawn(completed))

        result = run_qwen_code_headless("hello", cwd=tmp_path, json_schema={"type": "object"})

        assert result.structured == payload
        assert result.session_id == "6f0f8e9a-1b2c-4d5e-8f90-123456789abc"

    def test_structured_result_falls_back_to_result_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without structured_result the JSON-object result string is parsed."""
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        payload = {"completeness": 0.5}
        stdout = json.dumps([{"type": "result", "result": json.dumps(payload), "is_error": False}])
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_spawn(completed))

        result = run_qwen_code_headless("hello", cwd=tmp_path)

        assert result.structured == payload
        assert result.session_id == ""

    def test_plain_text_result_keeps_structured_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        stdout = json.dumps([{"type": "result", "result": "all done", "is_error": False}])
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_spawn(completed))

        result = run_qwen_code_headless("hello", cwd=tmp_path)

        assert result.structured is None
        assert result.session_id == ""

    def test_session_flags_reach_the_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        stdout = json.dumps([{"type": "result", "result": "ok", "is_error": False}])
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        captured: dict[str, object] = {}

        def _fake_run(argv: list[str], **kwargs: object) -> _FakeProc:
            captured["argv"] = argv
            return _FakeProc(completed)

        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_run)

        run_qwen_code_headless(
            "assess",
            cwd=tmp_path,
            session_id="6f0f8e9a-1b2c-4d5e-8f90-123456789abc",
            json_schema={"type": "object"},
        )

        argv = captured["argv"]
        assert isinstance(argv, list)
        assert "--session-id" in argv
        assert argv[argv.index("--session-id") + 1] == "6f0f8e9a-1b2c-4d5e-8f90-123456789abc"
        assert "--json-schema" in argv

    def test_error_result_flagged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        stdout = json.dumps([{"type": "result", "result": "boom", "is_error": True}])
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=1, stdout=stdout, stderr="err"
        )
        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_spawn(completed))

        result = run_qwen_code_headless("hello", cwd=tmp_path)

        assert result.is_error is True
        assert result.exit_code == 1
        assert result.raw_stderr == "err"

    def test_missing_result_message_marks_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        stdout = json.dumps([{"type": "assistant", "content": "hi"}])
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout=stdout, stderr=""
        )
        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_spawn(completed))

        result = run_qwen_code_headless("hello", cwd=tmp_path)

        assert result.is_error is True
        assert result.text == ""

    def test_non_json_stdout_marks_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        completed = subprocess.CompletedProcess(
            args=["qwen"], returncode=0, stdout="plain text", stderr=""
        )
        monkeypatch.setattr(qwen_code, "_spawn_headless", _fake_spawn(completed))

        result = run_qwen_code_headless("hello", cwd=tmp_path)

        assert result.is_error is True

    def test_timeout_raises_codegen_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        proc = _FakeProc(None, timeout_on_communicate=True)
        killed: list[object] = []
        monkeypatch.setattr(qwen_code, "_spawn_headless", lambda argv, **kw: proc)
        monkeypatch.setattr(qwen_code, "_kill_process_tree", killed.append)

        with pytest.raises(AICodegenError, match="did not finish"):
            run_qwen_code_headless("hello", cwd=tmp_path, timeout=1.0)

        assert killed == [proc]  # the whole tree is reaped, not just the parent

    def test_missing_binary_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: None)
        with pytest.raises(QwenCodeNotInstalledError):
            run_qwen_code_headless("hello", cwd=tmp_path)

    def test_missing_cwd_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(qwen_code, "find_qwen_code_binary", lambda **kw: Path("/fake/qwen"))
        with pytest.raises(AICodegenError, match="Working directory"):
            run_qwen_code_headless("hello", cwd=tmp_path / "missing")


# ---------------------------------------------------------------------------
# Real-subprocess tests: process tree, streaming, activity callback
# ---------------------------------------------------------------------------

_FAKE_QWEN = """#!{python}
import json, os, sys, time

mode = os.environ.get("FAKE_QWEN_MODE", "ok")
argv = sys.argv[1:]
stream = "stream-json" in argv
pidfile = os.environ.get("FAKE_QWEN_PIDFILE")
counter = os.environ.get("FAKE_QWEN_COUNTER")


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()


def finish(text="ok"):
    result = {{"type": "result", "result": text, "is_error": False, "session_id": "sid"}}
    if stream:
        emit(result)
    else:
        print(json.dumps([result]), flush=True)


if counter:
    with open(counter, "a") as fh:
        fh.write("x")

if mode == "reject-stream" and stream:
    sys.stderr.write("Unknown arguments: include-partial-messages, output-format\\n")
    sys.exit(1)

if mode == "hang":
    child = os.fork()
    if child == 0:
        time.sleep(120)
        os._exit(0)
    with open(pidfile, "w") as fh:
        fh.write(str(child))
    if stream:
        emit({{"type": "system", "subtype": "init"}})
    time.sleep(120)

if mode == "stream":
    emit({{"type": "system", "subtype": "init"}})
    for piece in ("Hel", "lo \\x1b[31mwor\\x1b[0m\\nld"):
        emit({{"type": "stream_event", "event": {{
            "type": "content_block_delta",
            "delta": {{"type": "text_delta", "text": piece}}}}}})
    emit({{"type": "stream_event", "event": {{
        "type": "content_block_delta",
        "delta": {{"type": "thinking_delta", "thinking": "private reasoning"}}}}}})
    emit({{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "run_shell_command",
          "input": {{"command": "echo sk-secret-token"}}}}]}}}})
    finish("streamed")
elif mode == "flood":
    sys.stderr.write("e" * 300000)
    sys.stderr.flush()
    finish("flooded")
elif mode == "slow":
    time.sleep(2.5)
    finish("slow")
elif mode == "stdin":
    finish("stdin=%d" % len(sys.stdin.read()))
else:
    finish("ok")
"""

_posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")


def _pid_dead(pid: int, *, wait: float = 4.0) -> bool:
    """``True`` once *pid* is gone (or only a zombie) — polled, never assumed."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            stat = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
            ).stdout.strip()
            if not stat or stat.startswith("Z"):
                return True
        except OSError:  # ps unavailable (restricted sandbox): fall back to a signal probe
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        time.sleep(0.1)
    return False


@pytest.fixture
def fake_qwen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "fake-qwen"
    script.write_text(_FAKE_QWEN.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("FAKE_QWEN_PIDFILE", str(tmp_path / "child.pid"))
    monkeypatch.setenv("FAKE_QWEN_COUNTER", str(tmp_path / "counter"))
    return script


@_posix_only
class TestRealProcess:
    def test_streaming_reports_activity_without_leaking_input(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "stream")
        seen: list[str] = []

        result = run_qwen_code_headless(
            "hi", binary=fake_qwen, cwd=tmp_path, timeout=20, on_activity=seen.append
        )

        assert result.text == "streamed"
        assert result.session_id == "sid"
        assert result.is_error is False
        # The feed scrolls by line: text lines first, the tool as its own line.
        assert seen[-1].splitlines() == ["starting", "Hello wor", "ld", "tool: run_shell_command"]
        assert any("Hello wor" in s.splitlines() for s in seen)
        joined = "\n".join(seen)
        assert "sk-secret-token" not in joined  # tool input is never surfaced
        assert "private reasoning" not in joined  # neither is thinking
        assert "\x1b" not in joined
        assert all(len(s.splitlines()) <= qwen_code._ACTIVITY_FEED_LINES for s in seen)
        assert "stream_event" not in result.raw_stdout  # per-token lines are not kept

    def test_without_callback_the_run_stays_plain_json(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "stream")
        result = run_qwen_code_headless("hi", binary=fake_qwen, cwd=tmp_path, timeout=20)
        assert result.text == "streamed"
        assert "stream-json" not in result.raw_stdout

    def test_heartbeat_while_the_agent_is_silent(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "slow")
        beats: list[str] = []
        run_qwen_code_headless(
            "hi", binary=fake_qwen, cwd=tmp_path, timeout=20, on_activity=beats.append
        )
        assert len(beats) >= 2

    def test_stderr_flood_does_not_deadlock(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "flood")
        result = run_qwen_code_headless(
            "hi", binary=fake_qwen, cwd=tmp_path, timeout=20, on_activity=lambda _s: None
        )
        assert result.text == "flooded"
        assert len(result.raw_stderr) == 300000

    def test_rejected_stream_flags_fall_back_to_json_once(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "reject-stream")
        result = run_qwen_code_headless(
            "hi", binary=fake_qwen, cwd=tmp_path, timeout=20, on_activity=lambda _s: None
        )
        assert result.text == "ok"
        assert (tmp_path / "counter").read_text() == "xx"  # stream attempt + json retry

    def test_stdin_is_not_inherited(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "stdin")
        result = run_qwen_code_headless("hi", binary=fake_qwen, cwd=tmp_path, timeout=20)
        assert result.text == "stdin=0"

    @pytest.mark.parametrize("streaming", [False, True], ids=["json", "stream-json"])
    def test_timeout_kills_the_whole_process_tree(
        self,
        tmp_path: Path,
        fake_qwen: Path,
        monkeypatch: pytest.MonkeyPatch,
        streaming: bool,
    ) -> None:
        """A timed-out run must not leave descendants running (the 13-minute leak)."""
        monkeypatch.setenv("FAKE_QWEN_MODE", "hang")
        started = time.monotonic()
        with pytest.raises(QwenCodeTimeoutError):
            run_qwen_code_headless(
                "hi",
                binary=fake_qwen,
                cwd=tmp_path,
                timeout=1.5,
                on_activity=(lambda _s: None) if streaming else None,
            )
        assert time.monotonic() - started < 15
        child = int((tmp_path / "child.pid").read_text())
        assert _pid_dead(child)

    def test_keyboard_interrupt_kills_the_whole_process_tree(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "hang")

        def interrupt(_summary: str) -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            run_qwen_code_headless(
                "hi", binary=fake_qwen, cwd=tmp_path, timeout=30, on_activity=interrupt
            )
        assert _pid_dead(int((tmp_path / "child.pid").read_text()))

    def test_callback_errors_never_fail_the_run(
        self, tmp_path: Path, fake_qwen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FAKE_QWEN_MODE", "stream")

        def broken(_summary: str) -> None:
            raise RuntimeError("renderer exploded")

        result = run_qwen_code_headless(
            "hi", binary=fake_qwen, cwd=tmp_path, timeout=20, on_activity=broken
        )
        assert result.text == "streamed"


class TestStreamHelpers:
    def test_stream_argv_uses_stream_json_and_partial_messages(self) -> None:
        argv = qwen_code._build_headless_command(
            Path("/usr/local/bin/qwen"), "hi", stream=True, windows=False
        )
        assert argv[:6] == [
            "/usr/local/bin/qwen",
            "hi",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--yolo",
        ]

    def test_default_argv_is_unchanged(self) -> None:
        argv = qwen_code._build_headless_command(Path("/usr/local/bin/qwen"), "hi", windows=False)
        assert argv == ["/usr/local/bin/qwen", "hi", "--output-format", "json", "--yolo"]

    def test_feed_ignores_thinking_and_unknown_events(self) -> None:
        feed = qwen_code._ActivityFeed()
        thinking = {
            "type": "stream_event",
            "event": {"delta": {"type": "thinking_delta", "thinking": "secret"}},
        }
        assert qwen_code._feed_stream_event(thinking, feed) is False
        assert qwen_code._feed_stream_event({"type": "wat"}, feed) is False
        assert qwen_code._feed_stream_event("not a dict", feed) is False
        assert feed.render() == ""

    @staticmethod
    def _text(feed: Any, text: str) -> None:
        qwen_code._feed_stream_event(
            {
                "type": "stream_event",
                "event": {"delta": {"type": "text_delta", "text": text}},
            },
            feed,
        )

    def test_feed_scrolls_by_line(self) -> None:
        feed = qwen_code._ActivityFeed()
        self._text(feed, "first li")
        assert feed.render() == "first li"  # the unfinished line is shown live
        self._text(feed, "ne\nsecond line\nthi")
        assert feed.render().splitlines() == ["first line", "second line", "thi"]
        self._text(feed, "rd\n")
        assert feed.render().splitlines() == ["first line", "second line", "third"]

    def test_tool_use_starts_its_own_line(self) -> None:
        feed = qwen_code._ActivityFeed()
        self._text(feed, "checking docs")
        qwen_code._feed_stream_event(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "web_fetch", "input": {"url": "u"}}]
                },
            },
            feed,
        )
        assert feed.render().splitlines() == ["checking docs", "tool: web_fetch"]
        assert "u" not in feed.render()

    def test_tool_name_shows_when_the_call_starts_and_is_not_repeated(self) -> None:
        feed = qwen_code._ActivityFeed()
        started = qwen_code._feed_stream_event(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "name": "write_file",
                        "input": {},
                    },
                },
            },
            feed,
        )
        assert started is True
        assert feed.render() == "tool: write_file"
        finished = qwen_code._feed_stream_event(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "write_file",
                            "input": {"path": "commands.py", "content": "secret"},
                        }
                    ]
                },
            },
            feed,
        )
        assert finished is False
        assert feed.render().splitlines() == ["tool: write_file"]
        assert "secret" not in feed.render()
        assert "commands.py" not in feed.render()

    def test_feed_is_bounded_and_single_line_entries_are_clean(self) -> None:
        feed = qwen_code._ActivityFeed()
        self._text(feed, "x" * 1000 + "\n\x1b[31mend")
        lines = feed.render().splitlines()
        assert lines[-1] == "end"
        assert all(len(line) <= qwen_code._ACTIVITY_SUMMARY_MAX for line in lines)
        assert "\x1b" not in feed.render()
        for n in range(50):
            self._text(feed, f"line {n}\n")
        assert len(feed.render().splitlines()) == qwen_code._ACTIVITY_FEED_LINES
        assert feed.render().splitlines()[-1] == "line 49"
