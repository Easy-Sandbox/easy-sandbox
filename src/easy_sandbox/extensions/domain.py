"""自定义域名配置扩展。

用于为沙箱服务绑定自定义域名。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DomainConfig(BaseModel):
    """自定义域名配置。

    为沙箱暴露的端口绑定自定义域名，支持 HTTPS。
    """

    domain: str = Field(description="自定义域名")
    certificate_id: str | None = Field(default=None, description="SSL 证书 ID")
    enable_https: bool = Field(default=True, description="是否启用 HTTPS")
