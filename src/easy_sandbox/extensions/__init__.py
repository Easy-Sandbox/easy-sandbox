"""Alibaba Cloud ecosystem extensions.

提供阿里云生态集成扩展：VPC 网络、OSS 挂载、自定义域名等。
"""
from easy_sandbox.extensions.vpc import VPCConfig
from easy_sandbox.extensions.oss import OSSMount
from easy_sandbox.extensions.domain import DomainConfig

__all__ = [
    "VPCConfig",
    "OSSMount",
    "DomainConfig",
]
