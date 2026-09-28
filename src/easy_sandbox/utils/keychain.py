"""密钥安全存储。

使用本地 JSON 文件 (~/.ebx/secrets.json) 存储密钥，用文件权限 (chmod 600) 保护。

.. warning::

    存储为 **明文 JSON** 文件，不提供加密保护。
    在生产环境中请使用其他安全的密钥管理方案。
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

SERVICE_NAME = "easy-sandbox"
SECRETS_FILE = Path.home() / ".ebx" / "secrets.json"


class SecretStore:
    """密钥存储 — 本地明文 JSON 文件 (chmod 600 保护)。

    .. warning::

        存储为明文 JSON，不提供加密。仅依靠文件系统
        权限 (chmod 600) 限制访问。仅适合本地开发环境。

    .. note::

        **并发限制**：本实现不使用文件锁，仅适合单进程使用。
        多进程并发写入可能导致数据丢失。
    """

    def __init__(self, secrets_file: Path | None = None) -> None:
        self._secrets_file = secrets_file or SECRETS_FILE

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def set(self, name: str, value: str) -> None:
        """存储密钥。"""
        self._set_file(name, value)

    def get(self, name: str) -> str | None:
        """获取密钥。"""
        return self._get_file(name)

    def delete(self, name: str) -> bool:
        """删除密钥，返回是否成功删除。"""
        return self._delete_file(name)

    def list_names(self) -> list[str]:
        """列出所有密钥名称。"""
        secrets = self._load_file()
        return sorted(secrets.keys())

    # ---------------------------------------------------------------
    # File-based storage
    # ---------------------------------------------------------------

    def _set_file(self, name: str, value: str) -> None:
        """本地文件存储（chmod 600 保护）。"""
        self._secrets_file.parent.mkdir(parents=True, exist_ok=True)
        secrets = self._load_file()
        secrets[name] = value
        # 以受限权限创建文件，避免权限窗口
        fd = os.open(
            str(self._secrets_file),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            stat.S_IRUSR | stat.S_IWUSR,  # 0o600
        )
        try:
            os.write(fd, json.dumps(secrets, indent=2).encode())
        finally:
            os.close(fd)
        try:
            self._secrets_file.chmod(0o600)
        except OSError:
            logger.warning(
                "Cannot set file permissions (chmod 600) on %s. "
                "The secrets file is NOT protected by POSIX permissions. "
                "This is expected on Windows but means secrets are readable "
                "by other users on this system.",
                self._secrets_file,
            )

    def _get_file(self, name: str) -> str | None:
        """从本地文件读取。"""
        secrets = self._load_file()
        return secrets.get(name)

    def _delete_file(self, name: str) -> bool:
        """从本地文件删除，返回是否删除了。"""
        secrets = self._load_file()
        if name in secrets:
            del secrets[name]
            # 以受限权限创建文件，避免权限窗口
            fd = os.open(
                str(self._secrets_file),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,  # 0o600
            )
            try:
                os.write(fd, json.dumps(secrets, indent=2).encode())
            finally:
                os.close(fd)
            try:
                self._secrets_file.chmod(0o600)
            except OSError:
                logger.warning(
                    "Cannot set file permissions (chmod 600) on %s. "
                    "The secrets file is NOT protected by POSIX permissions.",
                    self._secrets_file,
                )
            return True
        return False

    def _load_file(self) -> dict[str, str]:
        """加载本地文件中的所有密钥。"""
        if self._secrets_file.exists():
            try:
                return dict(json.loads(self._secrets_file.read_text()))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}
