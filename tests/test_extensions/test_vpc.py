"""Tests for extensions models (VPC, OSS, Domain)."""
from __future__ import annotations

import pytest

from easy_sandbox.extensions.vpc import VPCConfig
from easy_sandbox.extensions.oss import OSSMount
from easy_sandbox.extensions.domain import DomainConfig
from easy_sandbox.extensions import VPCConfig as VPCConfigExport
from easy_sandbox.extensions import OSSMount as OSSMountExport
from easy_sandbox.extensions import DomainConfig as DomainConfigExport


class TestVPCConfig:
    """Tests for VPCConfig model."""

    def test_create(self) -> None:
        config = VPCConfig(
            vpc_id="vpc-abc123",
            vswitch_ids=["vsw-001", "vsw-002"],
            security_group_id="sg-xyz",
        )
        assert config.vpc_id == "vpc-abc123"
        assert config.vswitch_ids == ["vsw-001", "vsw-002"]
        assert config.security_group_id == "sg-xyz"

    def test_single_vswitch(self) -> None:
        config = VPCConfig(
            vpc_id="vpc-1",
            vswitch_ids=["vsw-1"],
            security_group_id="sg-1",
        )
        assert len(config.vswitch_ids) == 1

    def test_exported_from_package(self) -> None:
        assert VPCConfig is VPCConfigExport


class TestOSSMount:
    """Tests for OSSMount model."""

    def test_defaults(self) -> None:
        mount = OSSMount(bucket="my-bucket")
        assert mount.bucket == "my-bucket"
        assert mount.prefix == ""
        assert mount.mount_path == "/mnt/oss"
        assert mount.read_only is False

    def test_full_config(self) -> None:
        mount = OSSMount(
            bucket="data-bucket",
            prefix="datasets/train",
            mount_path="/data",
            read_only=True,
        )
        assert mount.bucket == "data-bucket"
        assert mount.prefix == "datasets/train"
        assert mount.mount_path == "/data"
        assert mount.read_only is True

    def test_exported_from_package(self) -> None:
        assert OSSMount is OSSMountExport


class TestDomainConfig:
    """Tests for DomainConfig model."""

    def test_defaults(self) -> None:
        config = DomainConfig(domain="sandbox.example.com")
        assert config.domain == "sandbox.example.com"
        assert config.certificate_id is None
        assert config.enable_https is True

    def test_full_config(self) -> None:
        config = DomainConfig(
            domain="app.example.com",
            certificate_id="cert-123",
            enable_https=False,
        )
        assert config.domain == "app.example.com"
        assert config.certificate_id == "cert-123"
        assert config.enable_https is False

    def test_exported_from_package(self) -> None:
        assert DomainConfig is DomainConfigExport
