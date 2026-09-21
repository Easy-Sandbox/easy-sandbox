"""Sandbox — the primary user-facing class.

Usage:
    async with await Sandbox.create(template="python-base") as sb:
        result = await sb.run_code("print('hello')")
        print(result.text)

    # Or without context manager:
    sb = await Sandbox.create(template="python-base")
    result = await sb.commands.run("echo hello")
    await sb.kill()
"""
from __future__ import annotations

import functools
import json
import re
import shlex
from typing import Any, Callable

import httpx

from easy_sandbox.api.capability import (
    ResolvedCapabilities,
    check_capability,
    resolve_capabilities,
)
from easy_sandbox.models.errors import CapabilityNotSupportedError
from easy_sandbox.models.process import CodeResult, ProcessResult
from easy_sandbox.models.sandbox import SandboxConfig, SandboxInfo, SandboxStatus
from easy_sandbox.models.template import (
    DEFAULT_CAPABILITIES,
    CustomCommand,
)
from easy_sandbox.protocol.code_interpreter import CodeInterpreterProtocol
from easy_sandbox.protocol.filesystem import FilesystemProtocol
from easy_sandbox.protocol.process import ProcessProtocol
from easy_sandbox.protocol.sandbox import SandboxProtocol
from easy_sandbox.transport.auth import (
    AuthProvider,
    EnvdTokenManager,
    create_auth_provider,
)
from easy_sandbox.transport.config import TransportConfig, load_config
from easy_sandbox.transport.http import HttpClient
from easy_sandbox.utils.async_bridge import make_sync
from easy_sandbox.utils.logging import get_logger

logger = get_logger("api.sandbox")


def _build_infra(
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    access_key_id: str | None = None,
    access_key_secret: str | None = None,
) -> tuple[TransportConfig, AuthProvider, HttpClient, SandboxProtocol]:
    """Build config, auth, http client, and sandbox protocol from credentials.

    Shared helper for class methods that need standalone infra.
    """
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
    sandbox_protocol = SandboxProtocol(http_client)
    return config, auth, http_client, sandbox_protocol


class Sandbox:
    """Primary user-facing class for sandbox lifecycle management.

    Provides async context manager support and convenient access to
    commands, files, network, and code sub-modules.
    """

    def __init__(
        self,
        info: SandboxInfo,
        config: TransportConfig,
        http_client: HttpClient,
        auth: AuthProvider,
        envd_token: EnvdTokenManager,
        *,
        sandbox_protocol: SandboxProtocol | None = None,
        process_protocol: ProcessProtocol | None = None,
        filesystem_protocol: FilesystemProtocol | None = None,
        code_interpreter_protocol: CodeInterpreterProtocol | None = None,
        domain: str = "e2b.dev",
        secure: bool = True,
        resolved_capabilities: ResolvedCapabilities | None = None,
    ) -> None:
        self._info = info
        self._config = config

        # Derive envd URL when the platform response omits it (Bug 1 fix)
        if not self._info.envd_url and self._info.sandbox_id:
            self._info.envd_url = self._config.build_envd_url(self._info.sandbox_id)
        self._http_client = http_client
        self._auth = auth
        self._envd_token = envd_token
        self._domain = domain
        self._secure = secure
        self._sandbox_protocol = sandbox_protocol or SandboxProtocol(http_client)
        self._process_protocol = process_protocol or ProcessProtocol(http_client)
        self._filesystem_protocol = filesystem_protocol or FilesystemProtocol(http_client)
        self._code_interpreter_protocol = code_interpreter_protocol or CodeInterpreterProtocol(http_client)

        # Capability model
        if resolved_capabilities is not None:
            self._resolved = resolved_capabilities
        else:
            self._resolved = ResolvedCapabilities()
        self._capabilities: set[str] = set(self._resolved.capabilities)
        self._custom_commands: dict[str, CustomCommand] = dict(
            self._resolved.custom_commands
        )

    # ---- Properties ----

    @property
    def id(self) -> str:
        """Sandbox ID."""
        return self._info.sandbox_id

    @property
    def status(self) -> SandboxStatus:
        """Current sandbox status (cached, call refresh_info() to update)."""
        return self._info.status

    @property
    def url(self) -> str:
        """The envd URL for this sandbox."""
        return self._info.envd_url or ""

    @property
    def info(self) -> SandboxInfo:
        """Full sandbox info."""
        return self._info

    @property
    def capabilities(self) -> frozenset[str]:
        """Effective capability set for this sandbox."""
        return frozenset(self._capabilities)

    # ---- Sub-modules (lazy cached properties) ----

    @functools.cached_property
    def commands(self) -> CommandsModule:
        """Commands sub-module for running shell commands."""
        from easy_sandbox.api.commands import CommandsModule
        return CommandsModule(
            envd_url=self.url,
            envd_token=self._envd_token,
            process_protocol=self._process_protocol,
            capabilities=self._capabilities,
        )

    @functools.cached_property
    def files(self) -> FilesModule:
        """Files sub-module for filesystem operations."""
        from easy_sandbox.api.files import FilesModule
        return FilesModule(
            envd_url=self.url,
            envd_token=self._envd_token,
            filesystem_protocol=self._filesystem_protocol,
            sandbox_protocol=self._sandbox_protocol,
            sandbox_id=self.id,
            capabilities=self._capabilities,
        )

    @functools.cached_property
    def network(self) -> NetworkModule:
        """Network sub-module for port URL calculation."""
        from easy_sandbox.api.network import NetworkModule
        return NetworkModule(
            sandbox_id=self.id,
            domain=self._domain,
            secure=self._secure,
            access_token=self._envd_token.token if self._envd_token else None,
            capabilities=self._capabilities,
        )

    @functools.cached_property
    def code(self) -> CodeContextModule:
        """Code sub-module for code interpretation."""
        from easy_sandbox.api.code import CodeContextModule
        return CodeContextModule(
            sandbox_id=self.id,
            envd_url=self.url,
            envd_token=self._envd_token,
            code_interpreter_protocol=self._code_interpreter_protocol,
            capabilities=self._capabilities,
        )

    # ---- Factory classmethods ----

    @classmethod
    async def create(
        cls,
        template: str = "base",
        *,
        timeout: int = 300,
        metadata: dict[str, str] | None = None,
        envs: dict[str, str] | None = None,
        cpu: int | None = None,
        memory: int | None = None,
        disk: int | None = None,
        gpu: str | None = None,
        description: str | None = None,
        secure: bool = True,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
    ) -> Sandbox:
        """Create a new sandbox.

        Args:
            template: Sandbox template name.
            timeout: Sandbox timeout in seconds.
            metadata: Arbitrary metadata key-value pairs.
            envs: Environment variables for the sandbox.
            cpu: Number of CPU cores (optional).
            memory: Memory in MB (optional).
            disk: Disk size in MB (optional).
            gpu: GPU specification, e.g. ``'A10'`` (optional).
            description: Natural-language description for the sandbox.
                Inference only triggers when *description* is provided **and**
                *template* is left at its default value ``"base"``.  When
                triggered, the agent/infer engine resolves the best template
                and resource defaults.  Explicit *template*, *cpu*, or
                *memory* values always override any inferred values.
            secure: 是否启用安全模式（默认 True），启用后端口访问需要 access token。
            api_key: API key override.
            api_url: Platform API URL override.
            domain: 平台域名，用于端口 URL 计算。
            access_key_id: AK/SK access key ID.
            access_key_secret: AK/SK access key secret.

        Returns:
            A connected Sandbox instance.
        """
        # NL-first: infer template/resources when description is given and
        # template was not explicitly overridden (still at default value).
        effective_template = template
        effective_cpu = cpu
        effective_memory = memory
        if description and template == "base":
            from easy_sandbox.agent.infer import infer_template  # lazy import
            infer_result = await infer_template(description)
            effective_template = infer_result.template
            if effective_cpu is None:
                effective_cpu = infer_result.cpu
            if effective_memory is None:
                effective_memory = infer_result.memory

        config, auth, http_client, sandbox_protocol = _build_infra(
            api_key=api_key,
            api_url=api_url,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )

        sandbox_config = SandboxConfig(
            template=effective_template,
            timeout=timeout,
            metadata=metadata or {},
            env_vars=envs or {},
            cpu=effective_cpu,
            memory=effective_memory,
            disk=disk,
            gpu=gpu,
        )
        info = await sandbox_protocol.create(sandbox_config)

        envd_token = EnvdTokenManager(info.envd_access_token, sandbox_id=info.sandbox_id)

        logger.info("Sandbox created: %s", info.sandbox_id)

        # Resolve capabilities for the template
        resolved = await resolve_capabilities(effective_template)

        return cls(
            info=info,
            config=config,
            http_client=http_client,
            auth=auth,
            envd_token=envd_token,
            sandbox_protocol=sandbox_protocol,
            domain=domain or config.domain,
            secure=secure,
            resolved_capabilities=resolved,
        )

    @classmethod
    async def connect(
        cls,
        sandbox_id: str,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
    ) -> Sandbox:
        """Connect to an existing sandbox by ID.

        Args:
            sandbox_id: The ID of the sandbox to connect to.
            api_key: API key override.
            api_url: Platform API URL override.
            domain: 平台域名，用于端口 URL 计算。
            access_key_id: AK/SK access key ID.
            access_key_secret: AK/SK access key secret.

        Returns:
            A connected Sandbox instance.
        """
        config, auth, http_client, sandbox_protocol = _build_infra(
            api_key=api_key,
            api_url=api_url,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )

        info = await sandbox_protocol.connect(sandbox_id)
        envd_token = EnvdTokenManager(info.envd_access_token, sandbox_id=info.sandbox_id)

        logger.info("Connected to sandbox: %s", sandbox_id)

        # Resolve capabilities for the template
        resolved = await resolve_capabilities(info.template)

        return cls(
            info=info,
            config=config,
            http_client=http_client,
            auth=auth,
            envd_token=envd_token,
            sandbox_protocol=sandbox_protocol,
            domain=domain or config.domain,
            resolved_capabilities=resolved,
        )

    @classmethod
    async def list(
        cls,
        *,
        status: SandboxStatus | None = None,
        limit: int = 100,
        offset: int = 0,
        api_key: str | None = None,
        api_url: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
    ) -> list[SandboxInfo]:
        """List sandboxes (class method, no instance required).

        Args:
            status: Filter by sandbox status.
            limit: Maximum number of sandboxes to return.
            offset: Pagination offset.
            api_key: API key override.
            api_url: Platform API URL override.
            access_key_id: AK/SK access key ID.
            access_key_secret: AK/SK access key secret.

        Returns:
            List of SandboxInfo objects.
        """
        config, auth, http_client, sandbox_protocol = _build_infra(
            api_key=api_key,
            api_url=api_url,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        try:
            return await sandbox_protocol.list(status=status, limit=limit, offset=offset)
        finally:
            await http_client.close()

    @classmethod
    async def kill_by_id(
        cls,
        sandbox_id: str,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
    ) -> None:
        """Kill a sandbox by ID (class method, no instance required).

        Args:
            sandbox_id: The ID of the sandbox to kill.
            api_key: API key override.
            api_url: Platform API URL override.
            access_key_id: AK/SK access key ID.
            access_key_secret: AK/SK access key secret.
        """
        config, auth, http_client, sandbox_protocol = _build_infra(
            api_key=api_key,
            api_url=api_url,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        try:
            await sandbox_protocol.kill(sandbox_id)
            logger.info("Sandbox killed (by ID): %s", sandbox_id)
        finally:
            await http_client.close()

    # ---- Lifecycle ----

    async def kill(self) -> None:
        """Kill the sandbox and release resources."""
        try:
            await self._sandbox_protocol.kill(self.id)
            logger.info("Sandbox killed: %s", self.id)
        finally:
            await self._http_client.close()

    async def set_timeout(self, timeout: int) -> None:
        """Update sandbox timeout."""
        await self._sandbox_protocol.set_timeout(self.id, timeout)

    async def is_running(self) -> bool:
        """Check if the sandbox is currently running (makes API call).

        Fetches current info from the platform and checks status.
        """
        return await self._sandbox_protocol.is_running(self.id)

    async def pause(self) -> None:
        """Pause the sandbox.

        # 注意：REST 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        await self._sandbox_protocol.pause(self.id)
        logger.info("Sandbox paused: %s", self.id)

    async def resume(self) -> None:
        """Resume a paused sandbox.

        # 注意：REST 路径基于 E2B SDK 逆向推断，未经官方文档确认
        """
        await self._sandbox_protocol.resume(self.id)
        logger.info("Sandbox resumed: %s", self.id)

    async def refresh_info(self) -> SandboxInfo:
        """Refresh sandbox info from the platform."""
        self._info = await self._sandbox_protocol.get_info(self.id)
        # Re-derive envd URL if the platform still omits it
        if not self._info.envd_url and self._info.sandbox_id:
            self._info.envd_url = self._config.build_envd_url(self._info.sandbox_id)
        return self._info

    # ---- Convenience methods ----

    async def run_code(
        self,
        code: str,
        *,
        language: str = "python",
        timeout: int = 30,
        envs: dict[str, str] | None = None,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
        on_result: Callable[..., None] | None = None,
    ) -> CodeResult:
        """Run code in the sandbox using the code interpreter.

        Args:
            code: Source code to execute.
            language: Programming language (default: python).
            timeout: Execution timeout in seconds.
            envs: Optional environment variables for this execution.
            on_stdout: Optional callback invoked with stdout content.
            on_stderr: Optional callback invoked with stderr content.
            on_result: Optional callback invoked with the execution result dict.

        Returns:
            CodeResult with stdout, stderr, and output files.

        Raises:
            CapabilityNotSupportedError: If ``code`` capability is not enabled.
        """
        check_capability(self._capabilities, "code")
        return await self.code.run(
            code,
            language=language,
            timeout=timeout,
            envs=envs,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            on_result=on_result,
        )

    async def get_terminal(
        self,
        *,
        cols: int = 80,
        rows: int = 24,
        shell: str = "/bin/bash",
    ) -> TerminalSession:
        """Open an interactive PTY terminal session.

        Returns a :class:`TerminalSession` connected via WebSocket.

        Args:
            cols: Terminal columns (default 80).
            rows: Terminal rows (default 24).
            shell: Shell binary (default ``/bin/bash``).

        Raises:
            CapabilityNotSupportedError: If ``terminal`` capability is not enabled.
        """
        check_capability(self._capabilities, "terminal")
        from easy_sandbox.protocol.terminal import TerminalSession
        return await TerminalSession.create(
            envd_url=self.url,
            envd_token=self._envd_token,
            config=self._config,
            cols=cols,
            rows=rows,
            shell=shell,
        )

    # ---- Custom command dispatch ----

    def list_commands(self) -> list[dict[str, Any]]:
        """Return the custom command catalogue.

        Requires the ``shell`` capability and valid envd authentication.

        Each entry is a dict shaped as::

            {
                "name": str,
                "description": str,
                "args": [
                    {"name": str, "required": bool,
                     "default": str | None, "description": str,
                     "type": str},
                    ...
                ],
            }

        Raises:
            CapabilityNotSupportedError: If ``shell`` capability is missing.
            TokenExpiredError: If the sandbox is not authenticated.
        """
        check_capability(self._capabilities, "shell")
        # Verify sandbox authentication (raises TokenExpiredError if invalid)
        self._envd_token.get_headers()
        return [
            {
                "name": name,
                "description": cmd.description,
                "args": [
                    {
                        "name": arg.name,
                        "required": arg.required,
                        "default": arg.default,
                        "description": arg.description,
                        "type": arg.type,
                    }
                    for arg in cmd.args
                ],
            }
            for name, cmd in self._custom_commands.items()
        ]

    async def run(
        self,
        name: str,
        **kwargs: str,
    ) -> ProcessResult:
        """Execute a named custom command.

        Looks up *name* in the template's ``custom_commands``, fills
        ``{placeholder}`` tokens using *kwargs*, and runs the resulting
        shell command.

        Args:
            name: Custom command name.
            **kwargs: Argument values keyed by placeholder name.

        Returns:
            :class:`ProcessResult` with stdout/stderr/exit_code.

        Raises:
            ValueError: If the command name is unknown, a required arg
                is missing, an undeclared arg is passed, or a placeholder
                in the template cannot be filled.
        """
        if name not in self._custom_commands:
            available = ", ".join(sorted(self._custom_commands)) or "(none)"
            raise ValueError(
                f"Unknown custom command {name!r}; "
                f"available commands: {available}"
            )

        cmd_def = self._custom_commands[name]

        declared = {arg.name for arg in cmd_def.args}

        # Reject undeclared kwargs rather than silently dropping them,
        # so typos surface immediately instead of vanishing.
        undeclared = sorted(k for k in kwargs if k not in declared)
        if undeclared:
            raise ValueError(
                f"Unexpected argument(s) {undeclared} for custom command "
                f"{name!r}; declared args: {sorted(declared) or '(none)'}"
            )

        # Validate required args
        for arg in cmd_def.args:
            if arg.required and arg.name not in kwargs and arg.default is None:
                raise ValueError(
                    f"Required argument {arg.name!r} missing "
                    f"for custom command {name!r}"
                )

        # Build substitution map (declared args only, shlex-quoted).
        subs: dict[str, str] = {}
        for arg in cmd_def.args:
            if arg.name in kwargs:
                subs[arg.name] = shlex.quote(str(kwargs[arg.name]))
            elif arg.default is not None:
                subs[arg.name] = shlex.quote(arg.default)

        # Single-pass substitution over the ORIGINAL template only.  Because
        # ``re.sub`` never re-scans inserted text, a user value that itself
        # looks like ``{other}`` cannot be expanded a second time — this
        # closes the argv-injection hole that the previous cumulative
        # ``str.replace`` loop opened.
        def _sub(m: re.Match[str]) -> str:
            return subs.get(m.group(1), m.group(0))

        cmd_str = re.sub(r"\{(\w+)\}", _sub, cmd_def.cmd)

        # Detect unfilled placeholders against the ORIGINAL template (not the
        # substituted string), so a legitimate value like ``{id}`` is not
        # mistaken for an unfilled placeholder.
        unfilled = [
            k for k in re.findall(r"\{(\w+)\}", cmd_def.cmd) if k not in subs
        ]
        if unfilled:
            raise ValueError(
                f"Unfilled placeholders in command {name!r}: {unfilled}"
            )

        result = await self.commands.run(
            cmd_str,
            timeout=cmd_def.timeout,
            env=cmd_def.env or None,
            cwd=cmd_def.cwd,
        )
        # commands.run may return StreamReader when background=True,
        # but custom commands always run in foreground.
        return result  # type: ignore[return-value]

    # ---- Server command dispatch ----

    async def run_command(
        self,
        name: str,
        *,
        server_port: int = 9000,
        **kwargs: Any,
    ) -> Any:
        """Execute a named command on a server running inside the sandbox.

        Sends ``POST {port_url}/commands/{name}`` with *kwargs* as the
        JSON body to a server listening on *server_port* inside the
        sandbox.

        Args:
            name: Command name registered on the in-sandbox server.
            server_port: Port the server is listening on (default 9000).
            **kwargs: Keyword arguments forwarded as JSON body.

        Returns:
            The ``result`` field from the server's JSON response.

        Raises:
            CapabilityNotSupportedError: If ``ports`` capability is not
                enabled for the sandbox template.
            RuntimeError: If the server responds with a non-2xx status.
        """
        url = self.network.get_url(server_port)
        access_headers = self.network.get_access_headers()

        client = self._http_client._create_envd_client(url)
        headers = {"Content-Type": "application/json", **access_headers}

        try:
            response = await client.post(
                f"/commands/{name}",
                json=kwargs,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Request to sandbox server failed: {exc}"
            ) from exc

        try:
            body: dict[str, Any] = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Sandbox server returned non-JSON response "
                f"(status {response.status_code}): {response.text[:200]}"
            ) from exc

        if response.is_success:
            return body.get("result")

        error_msg = body.get("error", "Unknown error")
        error_type = body.get("type", "UnknownError")
        raise RuntimeError(f"{error_type}: {error_msg}")

    # ---- E2B-compatible URL stubs ----

    @classmethod
    async def deploy(
        cls,
        project_path: str,
        description: str,
        *,
        max_wall_time: str = "10m",
        max_tool_calls: int = 100,
        llm_api_key: str | None = None,
        openai_base_url: str | None = None,
        openai_model: str | None = None,
        timeout: int = 900,
        envs: dict[str, str] | None = None,
        cpu: int | None = None,
        memory: int | None = None,
        on_progress: Callable[[str], None] | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        domain: str | None = None,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
    ) -> Sandbox:
        """Deploy a project to sandbox using qwen-code agent.

        Creates a sandbox with the ``qwen-code`` template, uploads the
        project, and runs the qwen-code agent to autonomously analyse,
        install dependencies, build, and start the service.

        Args:
            project_path: Local path to the project directory.
            description: Natural-language instruction for the deployment.
            max_wall_time: Maximum wall-clock time for the agent
                (e.g. ``'10m'``, ``'600s'``).
            max_tool_calls: Maximum number of tool calls for qwen-code.
            llm_api_key: Explicit LLM API key (falls back to env vars).
            openai_base_url: OpenAI-compatible API base URL override.
            openai_model: LLM model name override.
            timeout: Sandbox timeout in seconds.
            envs: Additional environment variables for the sandbox.
            cpu: Number of CPU cores.
            memory: Memory in MB.
            on_progress: Optional callback invoked with progress messages.
            api_key: Platform API key override.
            api_url: Platform API URL override.
            domain: Platform domain override.
            access_key_id: AK/SK access key ID.
            access_key_secret: AK/SK access key secret.

        Returns:
            The Sandbox instance (still running) with the
            ``deploy_result`` attribute set. Access it via
            ``sandbox._deploy_result``.
        """
        from easy_sandbox.api.deploy import DeployModule, resolve_llm_env

        # Resolve LLM credentials
        llm_env = resolve_llm_env(
            llm_api_key=llm_api_key,
            openai_base_url=openai_base_url,
            openai_model=openai_model,
        )

        # Merge LLM env with user-supplied envs
        merged_envs = {**llm_env, **(envs or {})}

        # Create sandbox with qwen-code template
        sandbox = await cls.create(
            template="qwen-code",
            timeout=timeout,
            envs=merged_envs,
            cpu=cpu or 2,
            memory=memory or 4096,
            api_key=api_key,
            api_url=api_url,
            domain=domain,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )

        try:
            deployer = DeployModule(sandbox)
            result = await deployer.deploy_project(
                project_path,
                description,
                max_wall_time=max_wall_time,
                max_tool_calls=max_tool_calls,
                on_progress=on_progress,
            )
            sandbox._deploy_result = result  # type: ignore[attr-defined]
            logger.info(
                "Deploy completed: sandbox=%s status=%s",
                sandbox.id,
                result.status,
            )
        except Exception:
            logger.error("Deploy failed, killing sandbox %s", sandbox.id)
            try:
                await sandbox.kill()
            except Exception:
                pass
            raise

        return sandbox

    async def get_upload_url(self, path: str) -> str:
        """Return a pre-signed upload URL. E2B-compatible."""
        raise NotImplementedError(
            "get_upload_url is not yet implemented; use files.write() instead"
        )

    async def get_download_url(self, path: str) -> str:
        """Return a pre-signed download URL. E2B-compatible."""
        raise NotImplementedError(
            "get_download_url is not yet implemented; use files.read() instead"
        )

    # ---- Context manager ----

    async def __aenter__(self) -> Sandbox:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            await self.kill()
        except Exception:
            logger.warning("Error during sandbox cleanup on __aexit__", exc_info=True)

    # ---- Sync variants ----

    create_sync = staticmethod(make_sync(create.__func__))  # type: ignore[attr-defined]
    connect_sync = staticmethod(make_sync(connect.__func__))  # type: ignore[attr-defined]
    list_sync = staticmethod(make_sync(list.__func__))  # type: ignore[attr-defined]
    kill_by_id_sync = staticmethod(make_sync(kill_by_id.__func__))  # type: ignore[attr-defined]
    kill_sync = make_sync(kill)
    run_code_sync = make_sync(run_code)
    set_timeout_sync = make_sync(set_timeout)
    is_running_sync = make_sync(is_running)
    pause_sync = make_sync(pause)
    resume_sync = make_sync(resume)
    refresh_info_sync = make_sync(refresh_info)
    get_terminal_sync = make_sync(get_terminal)
    run_command_sync = make_sync(run)
    deploy_sync = staticmethod(make_sync(deploy.__func__))  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return f"<Sandbox id={self.id!r} status={self.status.value!r}>"


# Avoid circular imports — these are used only for type annotation in cached_property
from easy_sandbox.api.code import CodeContextModule as CodeContextModule  # noqa: E402
from easy_sandbox.api.commands import CommandsModule as CommandsModule  # noqa: E402
from easy_sandbox.api.files import FilesModule as FilesModule  # noqa: E402
from easy_sandbox.api.network import NetworkModule as NetworkModule  # noqa: E402
from easy_sandbox.protocol.terminal import TerminalSession as TerminalSession  # noqa: E402
