"""Image — chain-style image builder (Modal-inspired).

Usage:
    from serverless_sandbox.api.image import Image

    image = (
        Image.from_template("python-base")
        .pip_install("flask", "sqlalchemy")
        .apt_install("postgresql-client")
        .env(DATABASE_URL="postgresql://localhost/mydb")
        .run_command("echo 'setup complete'")
    )
    dockerfile = image.to_dockerfile()
    template_info = await image.build(alias="my-flask-app")
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from serverless_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from serverless_sandbox.models.template import TemplateInfo

logger = get_logger("api.image")


class Image:
    """Chain-style image builder (Modal-inspired).

    Constructs a Dockerfile incrementally via fluent API calls,
    then can generate the Dockerfile text or build it as a template.
    """

    def __init__(self) -> None:
        self._steps: list[str] = []
        self._base: str = "ubuntu:22.04"
        self._envs: dict[str, str] = {}
        self._from_template: str | None = None
        self._workdir: str | None = None
        self._exposed_ports: list[int] = []
        self._entrypoint: str | None = None

    @classmethod
    def from_template(cls, template: str) -> Image:
        """Create an image based on an existing template.

        The template name is used as-is and does NOT generate a FROM
        directive; instead, the template_id is passed to the build API.

        Args:
            template: Template name or ID (e.g. "python-base").
        """
        img = cls()
        img._from_template = template
        img._base = template  # used in dockerfile as FROM base reference
        return img

    @classmethod
    def from_image(cls, image: str) -> Image:
        """Create from a Docker image.

        Args:
            image: Docker image reference (e.g. "python:3.11-slim").
        """
        img = cls()
        img._base = image
        return img

    def pip_install(self, *packages: str) -> Image:
        """Install Python packages via pip.

        Args:
            packages: Package names (e.g. "flask", "sqlalchemy>=2.0").
        """
        if packages:
            self._steps.append(
                f"RUN pip install --no-cache-dir {' '.join(packages)}"
            )
        return self

    def apt_install(self, *packages: str) -> Image:
        """Install system packages via apt.

        Args:
            packages: Package names (e.g. "curl", "git").
        """
        if packages:
            pkgs = " ".join(packages)
            self._steps.append(
                f"RUN apt-get update && apt-get install -y {pkgs}"
                " && rm -rf /var/lib/apt/lists/*"
            )
        return self

    def copy_local(self, src: str, dst: str) -> Image:
        """Copy local files into the image.

        Args:
            src: Local source path.
            dst: Destination path in the image.
        """
        self._steps.append(f"COPY {src} {dst}")
        return self

    def env(self, **kwargs: str) -> Image:
        """Set environment variables.

        Args:
            kwargs: Environment variable key-value pairs.
        """
        self._envs.update(kwargs)
        return self

    def run_command(self, cmd: str) -> Image:
        """Execute a shell command during build.

        Args:
            cmd: Shell command to run.
        """
        self._steps.append(f"RUN {cmd}")
        return self

    def workdir(self, path: str) -> Image:
        """Set the working directory.

        Args:
            path: Working directory path.
        """
        self._workdir = path
        return self

    def expose(self, *ports: int) -> Image:
        """Expose ports.

        Args:
            ports: Port numbers to expose.
        """
        self._exposed_ports.extend(ports)
        return self

    def entrypoint(self, cmd: str) -> Image:
        """Set the entrypoint command.

        Args:
            cmd: Entrypoint command string.
        """
        self._entrypoint = cmd
        return self

    def to_dockerfile(self) -> str:
        """Generate Dockerfile content from the build chain.

        Returns:
            Complete Dockerfile as string.
        """
        lines: list[str] = [f"FROM {self._base}"]

        for step in self._steps:
            lines.append(step)

        for key, val in self._envs.items():
            lines.append(f"ENV {key}={val}")

        if self._workdir:
            lines.append(f"WORKDIR {self._workdir}")

        for port in self._exposed_ports:
            lines.append(f"EXPOSE {port}")

        if self._entrypoint:
            lines.append(f"CMD {self._entrypoint}")

        return "\n".join(lines)

    async def build(
        self,
        *,
        alias: str | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
        timeout: int = 600,
        cpu_count: int | None = None,
        memory_mb: int | None = None,
        start_cmd: str | None = None,
    ) -> TemplateInfo:
        """Build the image as a template on the platform.

        Creates an HTTP client, builds the Dockerfile, and waits for completion.

        Args:
            alias: Template alias name.
            api_key: API key override.
            api_url: Platform API URL override.
            access_key_id: AK/SK access key ID.
            access_key_secret: AK/SK access key secret.
            timeout: Maximum build wait time in seconds.
            cpu_count: Default CPU count for sandboxes.
            memory_mb: Default memory in MB.
            start_cmd: Start command.

        Returns:
            TemplateInfo with build_status=ready.
        """
        from serverless_sandbox.api.template import TemplateManager
        from serverless_sandbox.transport.config import load_config
        from serverless_sandbox.transport.auth import create_auth_provider
        from serverless_sandbox.transport.http import HttpClient

        config_overrides: dict[str, Any] = {}
        if api_key is not None:
            config_overrides["api_key"] = api_key
        if api_url is not None:
            config_overrides["api_url"] = api_url
        if access_key_id is not None:
            config_overrides["access_key_id"] = access_key_id
        if access_key_secret is not None:
            config_overrides["access_key_secret"] = access_key_secret

        config = load_config(**config_overrides)
        auth = create_auth_provider(
            api_key=config.api_key,
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
        )
        http_client = HttpClient(config, auth)

        try:
            manager = TemplateManager(http_client)
            dockerfile = self.to_dockerfile()
            return await manager.build(
                dockerfile,
                alias=alias,
                timeout=timeout,
                cpu_count=cpu_count,
                memory_mb=memory_mb,
                start_cmd=start_cmd,
            )
        finally:
            await http_client.close()

    def __repr__(self) -> str:
        return (
            f"<Image base={self._base!r} "
            f"steps={len(self._steps)} "
            f"envs={len(self._envs)}>"
        )
