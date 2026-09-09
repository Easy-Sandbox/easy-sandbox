"""Alibaba Cloud ecosystem extensions.

提供阿里云生态集成扩展：VPC 网络、OSS 挂载、自定义域名等。
"""
from serverless_sandbox.extensions.vpc import VPCConfig
from serverless_sandbox.extensions.oss import OSSMount
from serverless_sandbox.extensions.domain import DomainConfig

__all__ = [
    "VPCConfig",
    "OSSMount",
    "DomainConfig",
]
