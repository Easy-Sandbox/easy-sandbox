"""阿里云 VPC 扩展配置。

用于沙箱访问 VPC 内部资源。注意：此功能需要阿里云 OpenAPI（控制面），非 E2B 兼容 API。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class VPCConfig(BaseModel):
    """VPC 网络配置，用于沙箱访问 VPC 内部资源。

    注意：此功能需要阿里云 OpenAPI（控制面），非 E2B 兼容 API。
    """

    vpc_id: str = Field(description="VPC 实例 ID")
    vswitch_ids: list[str] = Field(description="交换机 ID 列表")
    security_group_id: str = Field(description="安全组 ID")
