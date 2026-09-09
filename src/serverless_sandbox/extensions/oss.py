"""阿里云 OSS 挂载扩展。

用于将 OSS Bucket 挂载到沙箱文件系统。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class OSSMount(BaseModel):
    """OSS 挂载配置。

    将阿里云 OSS Bucket 的指定前缀挂载到沙箱内的指定路径。
    """

    bucket: str = Field(description="OSS Bucket 名称")
    prefix: str = Field(default="", description="OSS 对象前缀")
    mount_path: str = Field(default="/mnt/oss", description="沙箱内挂载路径")
    read_only: bool = Field(default=False, description="是否只读挂载")
