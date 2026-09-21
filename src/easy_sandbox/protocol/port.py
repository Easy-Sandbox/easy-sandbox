"""Protocol layer — 端口 URL 本地计算。

端口 URL 为客户端本地计算，不需要服务端 API 调用。
已实测验证：端口 URL 格式为 https://{port}-{sandbox_id}.{domain}
其中 sandbox_id 已包含 "sbx-" 前缀（如 "sbx-xxxx"）。
"""
from __future__ import annotations

from easy_sandbox.utils.logging import get_logger

logger = get_logger("protocol.port")


class PortClient:
    """端口 URL 本地计算客户端。

    端口 URL 为客户端本地计算，不需要服务端 API 调用。
    所有方法均为纯本地计算，不涉及任何网络请求。

    已实测验证：URL 格式为 {port}-{sandbox_id}.{domain}，
    其中 sandbox_id 已包含 "sbx-" 前缀。
    """

    @staticmethod
    def get_host(sandbox_id: str, port: int, domain: str) -> str:
        """获取端口访问的 host 地址（已实测验证）。

        Args:
            sandbox_id: Sandbox ID（已包含 "sbx-" 前缀，如 "sbx-xxxx"）。
            port: 端口号。
            domain: 平台域名。

        Returns:
            格式为 ``{port}-{sandbox_id}.{domain}`` 的 host 字符串。
        """
        return f"{port}-{sandbox_id}.{domain}"

    @staticmethod
    def get_port_url(
        sandbox_id: str,
        port: int,
        domain: str,
        secure: bool = True,
    ) -> str:
        """获取端口访问的完整 URL（已实测验证）。

        Args:
            sandbox_id: Sandbox ID（已包含 "sbx-" 前缀）。
            port: 端口号。
            domain: 平台域名。
            secure: 是否使用 HTTPS（默认 True）。

        Returns:
            完整 URL，格式为 ``https://{port}-{sandbox_id}.{domain}``。
        """
        scheme = "https" if secure else "http"
        host = PortClient.get_host(sandbox_id, port, domain)
        return f"{scheme}://{host}"
