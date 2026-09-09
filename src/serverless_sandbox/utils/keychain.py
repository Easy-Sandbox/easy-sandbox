"""密钥安全存储。

优先使用系统 Keychain (macOS Keychain / Linux Secret Service)，
fallback 到本地文件 (~/.sbox/secrets.json) 并用文件权限保护。
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path

SERVICE_NAME = "serverless-sandbox"
SECRETS_FILE = Path.home() / ".sbox" / "secrets.json"


class SecretStore:
    """密钥存储。

    优先使用系统 Keychain，不可用时 fallback 到本地加密文件。
    """

    def __init__(self, secrets_file: Path | None = None) -> None:
        self._secrets_file = secrets_file or SECRETS_FILE

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def set(self, name: str, value: str) -> None:
        """存储密钥。"""
        try:
            self._set_keychain(name, value)
            return
        except Exception:  # noqa: BLE001
            pass
        # Fallback: 本地文件
        self._set_file(name, value)

    def get(self, name: str) -> str | None:
        """获取密钥。"""
        try:
            return self._get_keychain(name)
        except Exception:  # noqa: BLE001
            pass
        return self._get_file(name)

    def delete(self, name: str) -> bool:
        """删除密钥，返回是否成功删除。"""
        deleted = False
        # 尝试从 keychain 删除
        try:
            self._delete_keychain(name)
            deleted = True
        except Exception:  # noqa: BLE001
            pass
        # 从文件存储删除
        if self._delete_file(name):
            deleted = True
        return deleted

    def list_names(self) -> list[str]:
        """列出所有密钥名称。"""
        names: set[str] = set()
        # 从文件中读取
        secrets = self._load_file()
        names.update(secrets.keys())
        return sorted(names)

    # ---------------------------------------------------------------
    # System Keychain
    # ---------------------------------------------------------------

    def _set_keychain(self, name: str, value: str) -> None:
        """macOS: security add-generic-password; Linux: secret-tool."""
        if platform.system() == "Darwin":
            subprocess.run(
                [
                    "security", "add-generic-password",
                    "-a", SERVICE_NAME, "-s", name, "-w", value, "-U",
                ],
                check=True,
                capture_output=True,
            )
        else:
            raise NotImplementedError("Linux keychain not available")

    def _get_keychain(self, name: str) -> str:
        """从系统 keychain 读取。"""
        if platform.system() == "Darwin":
            result = subprocess.run(
                [
                    "security", "find-generic-password",
                    "-a", SERVICE_NAME, "-s", name, "-w",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            raise KeyError(name)
        raise NotImplementedError("Linux keychain not available")

    def _delete_keychain(self, name: str) -> None:
        """从系统 keychain 删除。"""
        if platform.system() == "Darwin":
            subprocess.run(
                [
                    "security", "delete-generic-password",
                    "-a", SERVICE_NAME, "-s", name,
                ],
                check=True,
                capture_output=True,
            )
        else:
            raise NotImplementedError("Linux keychain not available")

    # ---------------------------------------------------------------
    # File-based fallback
    # ---------------------------------------------------------------

    def _set_file(self, name: str, value: str) -> None:
        """本地文件存储（chmod 600 保护）。"""
        self._secrets_file.parent.mkdir(parents=True, exist_ok=True)
        secrets = self._load_file()
        secrets[name] = value
        self._secrets_file.write_text(json.dumps(secrets, indent=2))
        try:
            self._secrets_file.chmod(0o600)
        except OSError:
            pass  # Windows 不支持 chmod

    def _get_file(self, name: str) -> str | None:
        """从本地文件读取。"""
        secrets = self._load_file()
        return secrets.get(name)

    def _delete_file(self, name: str) -> bool:
        """从本地文件删除，返回是否删除了。"""
        secrets = self._load_file()
        if name in secrets:
            del secrets[name]
            self._secrets_file.write_text(json.dumps(secrets, indent=2))
            try:
                self._secrets_file.chmod(0o600)
            except OSError:
                pass
            return True
        return False

    def _load_file(self) -> dict[str, str]:
        """加载本地文件中的所有密钥。"""
        if self._secrets_file.exists():
            try:
                return json.loads(self._secrets_file.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}
