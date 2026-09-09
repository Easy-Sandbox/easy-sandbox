"""Local Docker build and ACR push utilities.

Provides a high-level :class:`DockerBuilder` that orchestrates:

1. Building a Docker image locally (``docker build``)
2. Logging into Alibaba Cloud ACR
3. Tagging and pushing the image to ACR
4. Creating a sandbox template via the v3/v2 Platform API

Typical usage::

    builder = DockerBuilder()
    result = await builder.build_and_push(
        template_dir="examples/templates/python-hello",
        acr_registry="registry.cn-hangzhou.aliyuncs.com",
        acr_namespace="my-ns",
        acr_repo="python-hello",
        acr_username="your-access-key-id",
        acr_password="your-access-key-secret",
    )
"""
from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import os
import shutil
import subprocess  # noqa: S404
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from serverless_sandbox.models.errors import (
    ACRLoginError,
    ACRPushError,
    DockerBuildError,
)
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("api.docker_builder")


@dataclass
class ACRConfig:
    """Alibaba Cloud ACR configuration.

    Attributes:
        registry: ACR registry host (e.g. ``registry.cn-hangzhou.aliyuncs.com``).
        namespace: ACR namespace.
        repo: ACR repository name.
        username: Login username (typically the AccessKey ID).
        password: Login password (typically the AccessKey Secret).
        acree_instance_id: ACR EE instance ID (e.g. ``cri-...``), required
            for custom template builds on FC sandbox platform.
        vpc_id: VPC ID for ACR EE network access.
        vswitch_ids: Comma-separated VSwitch IDs.
        security_group_id: Security group ID.
    """

    registry: str = "registry.cn-hangzhou.aliyuncs.com"
    namespace: str = ""
    repo: str = ""
    username: str = ""
    password: str = ""
    acree_instance_id: str = ""
    vpc_id: str = ""
    vswitch_ids: str = ""
    security_group_id: str = ""

    @property
    def full_image_ref(self) -> str:
        """Full image reference without tag (e.g. ``registry/ns/repo``)."""
        return f"{self.registry}/{self.namespace}/{self.repo}"

    def tagged_ref(self, tag: str = "latest") -> str:
        """Full image reference with tag."""
        return f"{self.full_image_ref}:{tag}"

    def vpc_registry(self) -> str:
        """VPC-internal registry address for ACR EE.

        Replaces ``registry.`` with ``-vpc.`` in the registry host and
        switches to ``.cr.aliyuncs.com`` suffix for ACR EE format.
        """
        # ACR EE VPC format: <instance>-vpc.<region>.cr.aliyuncs.com
        # For standard ACR: registry.<region>.aliyuncs.com → <region>.cr.aliyuncs.com
        return self.registry.replace("registry.", "").replace(
            ".aliyuncs.com", ".cr.aliyuncs.com"
        )

    def to_platform_headers(
        self,
        build_mode: str = "direct",
        image_tag: str = "latest",
    ) -> dict[str, str]:
        """Generate platform API headers for ACR integration.

        These headers are required by ``POST /v2/templates/{tpl}/builds/{build}``
        to tell the FC backend where the source image lives.

        Args:
            build_mode: ``"builder"`` (injects envd) or ``"direct"``
                (uses image as-is; image must already contain E2B deps).
            image_tag: Image tag for Dest-Image-Ref (FC requires a tag).
        """
        # Auto-detect registry type: acree when instance_id is set, otherwise acr
        registry_type = "acree" if self.acree_instance_id else "acr"
        headers: dict[str, str] = {
            "X-E2B-Template-Build-Mode": build_mode,
            "X-E2B-Template-Source-Registry-Type": registry_type,
        }
        if self.full_image_ref:
            # FC function creation requires image URI to have a tag
            headers["X-E2B-Template-Dest-Image-Ref"] = self.tagged_ref(image_tag)
        if self.username:
            headers["X-E2B-Template-Source-Username"] = self.username
        if self.password:
            headers["X-E2B-Template-Source-Password"] = self.password
        if self.acree_instance_id:
            headers["X-E2B-Template-Source-ACREE-Instance-ID"] = self.acree_instance_id
        if self.vpc_id:
            headers["X-E2B-Template-Source-VPC-ID"] = self.vpc_id
        if self.vswitch_ids:
            headers["X-E2B-Template-Source-VSwitch-IDs"] = self.vswitch_ids
        if self.security_group_id:
            headers["X-E2B-Template-Source-Security-Group-ID"] = self.security_group_id
        return headers


@dataclass
class BuildResult:
    """Result of a local Docker build + ACR push + template creation."""

    local_tag: str = ""
    acr_ref: str = ""
    template_id: str = ""
    build_id: str = ""
    build_status: str = "unknown"
    logs: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.build_status in ("ready", "building", "pushed")


class DockerBuilder:
    """Orchestrates local Docker build → ACR push → template registration.

    All Docker operations are synchronous subprocess calls; the template
    registration step is async (uses the platform HTTP API).
    """

    def __init__(self, docker_cmd: str = "docker") -> None:
        self._docker = docker_cmd

    # ------------------------------------------------------------------ #
    # Docker operations (synchronous subprocess)
    # ------------------------------------------------------------------ #

    def check_docker(self) -> bool:
        """Verify Docker daemon is reachable.

        Returns:
            ``True`` if ``docker info`` exits successfully.
        """
        try:
            result = subprocess.run(
                [self._docker, "info"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def build(
        self,
        context_dir: str | Path,
        tag: str,
        *,
        dockerfile: str | Path | None = None,
        platform: str = "linux/amd64",
        build_args: dict[str, str] | None = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Build a Docker image locally.

        Args:
            context_dir: Build context directory.
            tag: Image tag (e.g. ``my-image:latest``).
            dockerfile: Path to Dockerfile (defaults to ``context_dir/Dockerfile``).
            platform: Target platform (default ``linux/amd64``).
            build_args: Docker build arguments.
            on_output: Optional callback for build output lines.

        Returns:
            The image tag.

        Raises:
            DockerBuildError: If the build fails.
        """
        context = Path(context_dir).resolve()
        cmd = [
            self._docker, "build",
            "--platform", platform,
            "-t", tag,
        ]
        if dockerfile:
            cmd.extend(["-f", str(dockerfile)])
        if build_args:
            for k, v in build_args.items():
                cmd.extend(["--build-arg", f"{k}={v}"])
        cmd.append(str(context))

        logger.info("Building Docker image: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output_lines: list[str] = []
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                if on_output:
                    on_output(line)
                logger.debug("docker build: %s", line)
            proc.wait()

            if proc.returncode != 0:
                raise DockerBuildError(
                    f"Docker build failed (exit {proc.returncode}):\n"
                    + "\n".join(output_lines[-20:]),
                )
            logger.info("Docker build succeeded: %s", tag)
            return tag
        except FileNotFoundError:
            raise DockerBuildError(
                f"Docker command not found: {self._docker}",
                suggestion="Install Docker or ensure it is in PATH.",
            )

    def login_acr(
        self,
        registry: str,
        username: str,
        password: str,
    ) -> None:
        """Login to Alibaba Cloud ACR.

        Args:
            registry: ACR registry host.
            username: Login username.
            password: Login password.

        Raises:
            ACRLoginError: If login fails.
        """
        cmd = [
            self._docker, "login",
            "--username", username,
            "--password-stdin",
            registry,
        ]
        logger.info("Logging into ACR: %s", registry)
        try:
            proc = subprocess.run(
                cmd,
                input=password,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise ACRLoginError(
                    f"ACR login failed: {proc.stderr.strip()}",
                )
            logger.info("ACR login succeeded: %s", registry)
        except FileNotFoundError:
            raise ACRLoginError(
                f"Docker command not found: {self._docker}",
                suggestion="Install Docker or ensure it is in PATH.",
            )
        except subprocess.TimeoutExpired:
            raise ACRLoginError("ACR login timed out after 30s.")

    def login_acr_with_aksk(
        self,
        registry: str,
        access_key_id: str,
        access_key_secret: str,
        region: str = "cn-hangzhou",
        instance_id: str | None = None,
    ) -> None:
        """Login to ACR using AK/SK → temporary credentials via GetAuthorizationToken API.

        Retrieves a temporary docker-login token from the Alibaba Cloud
        Container Registry API and uses it for ``docker login``.

        Attempts the GetAuthorizationToken API first. If the API call
        fails (e.g. no CR permission), falls back to using AK/SK
        directly as docker login credentials.

        Args:
            registry: ACR registry host.
            access_key_id: Alibaba Cloud AccessKey ID.
            access_key_secret: Alibaba Cloud AccessKey Secret.
            region: Region ID (default ``cn-hangzhou``).
            instance_id: ACR EE instance ID (optional).

        Raises:
            ACRLoginError: If all login attempts fail.
        """
        logger.info("Attempting ACR login via GetAuthorizationToken for %s", registry)
        try:
            token_data = _get_acr_auth_token(
                access_key_id, access_key_secret, region,
                instance_id=instance_id,
            )
            temp_username = token_data.get("tempUserName", "")
            auth_token = token_data.get("authorizationToken", "")
            if not temp_username or not auth_token:
                raise ACRLoginError(
                    f"ACR API returned incomplete credentials: {list(token_data.keys())}",
                )
            logger.info(
                "ACR temp credentials obtained (user=%s, expires=%s)",
                temp_username, token_data.get("expireTime", "?"),
            )
            self.login_acr(registry, temp_username, auth_token)
            return
        except ACRLoginError as exc:
            logger.warning(
                "GetAuthorizationToken failed: %s — falling back to direct AK/SK login", exc
            )
        except Exception as exc:
            logger.warning(
                "GetAuthorizationToken error: %s — falling back to direct AK/SK login", exc
            )

        # Fallback: use AK as username, SK as password directly
        logger.info("Attempting direct AK/SK docker login for %s", registry)
        self.login_acr(registry, access_key_id, access_key_secret)

    def tag(self, source: str, target: str) -> None:
        """Tag a local image for a remote registry.

        Args:
            source: Source image tag.
            target: Target image tag (full ACR reference).
        """
        logger.info("Tagging: %s → %s", source, target)
        result = subprocess.run(
            [self._docker, "tag", source, target],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise DockerBuildError(
                f"Docker tag failed: {result.stderr.strip()}"
            )

    def push(
        self,
        image_ref: str,
        *,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Push an image to a remote registry.

        Args:
            image_ref: Full image reference to push.
            on_output: Optional callback for push output lines.

        Raises:
            ACRPushError: If the push fails.
        """
        logger.info("Pushing image: %s", image_ref)
        try:
            proc = subprocess.Popen(
                [self._docker, "push", image_ref],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output_lines: list[str] = []
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                if on_output:
                    on_output(line)
                logger.debug("docker push: %s", line)
            proc.wait()

            if proc.returncode != 0:
                raise ACRPushError(
                    f"Docker push failed (exit {proc.returncode}):\n"
                    + "\n".join(output_lines[-10:]),
                )
            logger.info("Docker push succeeded: %s", image_ref)
        except FileNotFoundError:
            raise ACRPushError(
                f"Docker command not found: {self._docker}",
                suggestion="Install Docker or ensure it is in PATH.",
            )

    # ------------------------------------------------------------------ #
    # SDK wheel helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def inject_sdk_wheel(
        context_dir: Path,
        project_root: Path | None = None,
    ) -> list[Path]:
        """Build an SDK wheel and copy it into the Docker build context.

        This allows templates to ``COPY *.whl /tmp/`` in their Dockerfile
        and ``pip install /tmp/*.whl`` to get the local SDK version.

        Args:
            context_dir: Docker build context directory.
            project_root: SDK project root (auto-detected from this file
                location if not given).

        Returns:
            List of wheel file paths copied into the context.
        """
        if project_root is None:
            # Navigate from api/docker_builder.py → src/serverless_sandbox/api/
            # → src/serverless_sandbox → src → project root
            project_root = Path(__file__).resolve().parent.parent.parent.parent

        pyproject = project_root / "pyproject.toml"
        if not pyproject.exists():
            logger.warning("pyproject.toml not found at %s; skipping wheel injection", project_root)
            return []

        # Build wheel in a temp directory
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info("Building SDK wheel from %s", project_root)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", str(project_root),
                 "--no-deps", "-w", tmpdir],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning("Failed to build SDK wheel: %s", result.stderr[:300])
                return []

            # Copy .whl files to context_dir
            wheels: list[Path] = []
            for whl in Path(tmpdir).glob("*.whl"):
                dest = context_dir / whl.name
                shutil.copy2(whl, dest)
                wheels.append(dest)
                logger.info("Injected SDK wheel: %s", dest.name)
            return wheels

    # ------------------------------------------------------------------ #
    # Full chain: build → push → register template
    # ------------------------------------------------------------------ #

    async def build_and_register(
        self,
        template_dir: str | Path,
        acr: ACRConfig,
        *,
        name: str | None = None,
        tag: str = "latest",
        platform: str = "linux/amd64",
        dockerfile: str | Path | None = None,
        cpu_count: int = 2,
        memory_mb: int = 2048,
        start_cmd: str | None = None,
        ready_cmd: str | None = None,
        on_progress: Optional[Callable[[str], None]] = None,
        api_key: str | None = None,
        api_url: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
        timeout: int = 600,
    ) -> BuildResult:
        """Full chain: local Docker build → ACR push → platform template creation.

        Args:
            template_dir: Path to the template directory (must contain a Dockerfile).
            acr: ACR configuration.
            name: Template name (defaults to acr.repo or directory name).
            tag: Image tag (default ``latest``).
            platform: Target platform (default ``linux/amd64``).
            dockerfile: Custom Dockerfile path.
            cpu_count: CPU cores for the template.
            memory_mb: Memory in MB for the template.
            start_cmd: Start command.
            ready_cmd: Readiness check command.
            on_progress: Progress callback.
            api_key: Platform API key override.
            api_url: Platform API URL override.
            access_key_id: AK override.
            access_key_secret: SK override.
            timeout: Build wait timeout.

        Returns:
            :class:`BuildResult` with template_id and build status.
        """
        result = BuildResult()
        tdir = Path(template_dir).resolve()
        template_name = name or acr.repo or tdir.name

        def _progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)
            logger.info(msg)

        # Step 1: Check Docker
        _progress("[1/5] Checking Docker daemon...")
        if not self.check_docker():
            raise DockerBuildError(
                "Docker daemon is not running or not accessible.",
                suggestion="Start Docker Desktop or the Docker daemon.",
            )

        # Step 1.5: Inject SDK wheel into docker context
        _progress("[1.5/5] Injecting SDK wheel into build context...")
        injected_wheels = self.inject_sdk_wheel(tdir)
        if injected_wheels:
            _progress(f"  Injected {len(injected_wheels)} wheel(s)")
        else:
            _progress("  No SDK wheel injected (may install from PyPI)")

        # Step 2: Build locally
        local_tag = f"{template_name}:{tag}"
        result.local_tag = local_tag
        _progress(f"[2/5] Building Docker image locally: {local_tag}")
        try:
            self.build(
                context_dir=tdir,
                tag=local_tag,
                platform=platform,
                dockerfile=dockerfile,
                on_output=lambda line: logger.debug("  %s", line),
            )
        finally:
            # Clean up injected wheels regardless of build outcome
            for whl in injected_wheels:
                try:
                    whl.unlink(missing_ok=True)
                except OSError:
                    pass

        # Step 3: Login + tag + push to ACR
        acr_ref = acr.tagged_ref(tag)
        result.acr_ref = acr_ref
        _progress(f"[3/5] Pushing to ACR: {acr_ref}")
        self.login_acr(acr.registry, acr.username, acr.password)
        self.tag(local_tag, acr_ref)
        self.push(acr_ref, on_output=lambda line: logger.debug("  %s", line))
        result.build_status = "pushed"

        # Step 4: Create template via v3 API
        _progress(f"[4/5] Creating template on platform: {template_name}")
        from serverless_sandbox.transport.config import load_config
        from serverless_sandbox.transport.auth import create_auth_provider
        from serverless_sandbox.transport.http import HttpClient
        from serverless_sandbox.protocol.template import TemplateProtocol

        config_overrides: dict[str, Any] = {}
        if api_key:
            config_overrides["api_key"] = api_key
        if api_url:
            config_overrides["api_url"] = api_url
        if access_key_id:
            config_overrides["access_key_id"] = access_key_id
        if access_key_secret:
            config_overrides["access_key_secret"] = access_key_secret

        config = load_config(**config_overrides)
        auth = create_auth_provider(
            api_key=config.api_key,
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
        )
        http_client = HttpClient(config, auth)

        try:
            protocol = TemplateProtocol(http_client)

            # Create metadata via v3
            v3_data = await protocol.create_v3(
                template_name,
                cpu_count=cpu_count,
                memory_mb=memory_mb,
            )
            result.template_id = v3_data.get("templateID", "")
            result.build_id = v3_data.get("buildID", "")

            # Trigger build via v2
            _progress(
                f"[5/5] Triggering build: templateID={result.template_id}, "
                f"image={acr_ref}"
            )
            acr_headers = acr.to_platform_headers()
            await protocol.trigger_build_v2(
                result.template_id,
                result.build_id,
                from_image=acr_ref,
                start_cmd=start_cmd,
                ready_cmd=ready_cmd,
                acr_headers=acr_headers,
            )

            # Wait for build
            _progress("Waiting for build to complete...")
            try:
                await protocol.wait_for_build(
                    result.template_id,
                    result.build_id,
                    timeout=timeout,
                )
                result.build_status = "ready"
                _progress(f"Template ready: {result.template_id}")
            except Exception as exc:
                result.build_status = "error"
                result.logs.append(str(exc))
                _progress(f"Build failed: {exc}")

        finally:
            await http_client.close()

        return result


# ── Alibaba Cloud API signature helpers ──


def _percent_encode(s: str) -> str:
    """RFC 3986 percent-encoding (Alibaba Cloud signature convention)."""
    return urllib.parse.quote(s, safe="").replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def _sign_rpc(params: dict[str, str], secret: str, method: str = "GET") -> str:
    """Compute Alibaba Cloud RPC (POP) V1 HMAC-SHA1 signature."""
    sorted_params = sorted(params.items())
    canonical = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params
    )
    sts = f"{method}&{_percent_encode('/')}&{_percent_encode(canonical)}"
    key = (secret + "&").encode("utf-8")
    return base64.b64encode(
        hmac_mod.new(key, sts.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")


def _sign_roa(
    method: str,
    path: str,
    headers: dict[str, str],
    secret: str,
    accept: str = "application/json",
    content_type: str = "application/json",
) -> str:
    """Compute Alibaba Cloud ROA-style HMAC-SHA1 signature.

    StringToSign = VERB + '\\n' + Accept + '\\n' + Content-MD5 + '\\n'
                 + Content-Type + '\\n' + Date + '\\n'
                 + CanonicalizedHeaders + CanonicalizedResource
    """
    # Canonicalize x-acs-* headers
    acs_headers = sorted(
        (k.lower(), v.strip())
        for k, v in headers.items()
        if k.lower().startswith("x-acs-")
    )
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in acs_headers)
    date_str = headers.get("Date", "")
    content_md5 = headers.get("Content-MD5", "")

    sts = (
        f"{method}\n"
        f"{accept}\n"
        f"{content_md5}\n"
        f"{content_type}\n"
        f"{date_str}\n"
        f"{canonical_headers}"
        f"{path}"
    )
    return base64.b64encode(
        hmac_mod.new(secret.encode("utf-8"), sts.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")


def _get_acr_auth_token_personal(
    access_key_id: str,
    access_key_secret: str,
    region: str = "cn-hangzhou",
) -> dict[str, Any]:
    """Call ACR personal-edition ``GET /tokens`` (ROA-style, Version 2016-06-07)."""
    from email.utils import formatdate

    endpoint = f"https://cr.{region}.aliyuncs.com"
    path = "/tokens"
    nonce = str(uuid.uuid4())
    date_str = formatdate(usegmt=True)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Date": date_str,
        "x-acs-signature-method": "HMAC-SHA1",
        "x-acs-signature-nonce": nonce,
        "x-acs-signature-version": "1.0",
        "x-acs-version": "2016-06-07",
    }

    sig = _sign_roa(
        "GET", path, headers, access_key_secret,
        accept="application/json", content_type="application/json",
    )
    headers["Authorization"] = f"acs {access_key_id}:{sig}"

    logger.info("Calling ACR GetAuthorizationToken (ROA, personal, region=%s)", region)
    with httpx.Client() as client:
        resp = client.get(f"{endpoint}{path}", headers=headers, timeout=15)
    data = resp.json()
    logger.debug(
        "ACR personal GetAuthorizationToken response: status=%s body=%s",
        resp.status_code, str(data)[:300],
    )

    if resp.status_code != 200:
        msg = data.get("message", data.get("Message", str(data)))
        raise ACRLoginError(
            f"ACR personal GetAuthorizationToken failed (HTTP {resp.status_code}): {msg}",
            suggestion="Check AK/SK and region. Ensure CR API is accessible.",
        )

    # Response: {"data": {"tempUserName": ..., "authorizationToken": ..., "expireTime": ...}}
    auth_data = data.get("data", data)
    return auth_data


def _get_acr_auth_token_ee(
    access_key_id: str,
    access_key_secret: str,
    region: str = "cn-hangzhou",
    instance_id: str = "",
) -> dict[str, Any]:
    """Call ACR EE ``GetAuthorizationToken`` (RPC/POP-style, Version 2018-12-01)."""
    endpoint = f"https://cr.{region}.aliyuncs.com"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    params: dict[str, str] = {
        "Action": "GetAuthorizationToken",
        "Format": "JSON",
        "Version": "2018-12-01",
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": ts,
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "InstanceId": instance_id,
    }
    params["Signature"] = _sign_rpc(params, access_key_secret)

    logger.info("Calling ACR GetAuthorizationToken (RPC, EE, region=%s, instance=%s)", region, instance_id)
    with httpx.Client() as client:
        resp = client.get(endpoint, params=params, timeout=15)
    data = resp.json()
    logger.debug(
        "ACR EE GetAuthorizationToken response: status=%s body=%s",
        resp.status_code, str(data)[:300],
    )

    if resp.status_code != 200:
        msg = data.get("Message", data.get("message", str(data)))
        raise ACRLoginError(
            f"ACR EE GetAuthorizationToken failed (HTTP {resp.status_code}): {msg}",
            suggestion="Check AK/SK, region, and InstanceId.",
        )

    auth_data = data.get("data", data)
    return auth_data


def _get_acr_auth_token(
    access_key_id: str,
    access_key_secret: str,
    region: str = "cn-hangzhou",
    *,
    instance_id: str | None = None,
) -> dict[str, Any]:
    """Get ACR temporary credentials by trying available API editions.

    - Personal edition (ROA, ``GET /tokens``, Version 2016-06-07)
    - Enterprise edition (RPC/POP, ``GetAuthorizationToken``, Version 2018-12-01)
      — only attempted when *instance_id* is provided.

    Returns:
        dict with ``tempUserName`` and ``authorizationToken``.
    """
    errors: list[str] = []

    # 1. Try personal edition (ROA)
    try:
        auth = _get_acr_auth_token_personal(access_key_id, access_key_secret, region)
        token = auth.get("authorizationToken", "")
        user = auth.get("tempUserName", "")
        if token and user:
            return auth
        errors.append(f"personal: incomplete credentials {list(auth.keys())}")
    except Exception as exc:
        errors.append(f"personal: {exc}")
        logger.debug("ACR personal-edition token failed: %s", exc)

    # 2. Try EE edition (RPC) if instance_id provided
    if instance_id:
        try:
            auth = _get_acr_auth_token_ee(
                access_key_id, access_key_secret, region, instance_id,
            )
            token = auth.get("authorizationToken", "")
            user = auth.get("tempUserName", "")
            if token and user:
                return auth
            errors.append(f"EE: incomplete credentials {list(auth.keys())}")
        except Exception as exc:
            errors.append(f"EE: {exc}")
            logger.debug("ACR EE-edition token failed: %s", exc)

    raise ACRLoginError(
        f"All ACR GetAuthorizationToken attempts failed: {'; '.join(errors)}",
        suggestion="Check AK/SK and region. For personal ACR ensure CR API is enabled.",
    )
