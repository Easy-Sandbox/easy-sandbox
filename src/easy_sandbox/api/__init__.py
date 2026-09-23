"""L4 High-level API — user-facing classes."""
from __future__ import annotations

from easy_sandbox.api.capability import ResolvedCapabilities, resolve_capabilities
from easy_sandbox.api.code import CodeContextModule
from easy_sandbox.api.commands import CommandsModule
from easy_sandbox.api.deploy import DeployModule, DeployResult
from easy_sandbox.api.docker_builder import ACRConfig, BuildResult, DockerBuilder
from easy_sandbox.api.fc_template import create_official_template
from easy_sandbox.api.fc_template import get_template as get_official_template
from easy_sandbox.api.files import FilesModule
from easy_sandbox.api.image import Image
from easy_sandbox.api.network import NetworkModule
from easy_sandbox.api.sandbox import Sandbox
from easy_sandbox.api.template import TemplateManager

__all__ = [
    "Sandbox",
    "CommandsModule",
    "FilesModule",
    "CodeContextModule",
    "NetworkModule",
    "TemplateManager",
    "Image",
    "ResolvedCapabilities",
    "resolve_capabilities",
    "DeployModule",
    "DeployResult",
    "DockerBuilder",
    "ACRConfig",
    "BuildResult",
    "create_official_template",
    "get_official_template",
]
