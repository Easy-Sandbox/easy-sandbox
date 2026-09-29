"""Structured error hierarchy for Easy Sandbox SDK.

注意：错误码（如 E1001、E2001 等）为 SDK 内部定义，不是阿里云官方 API 返回的错误码。

Every exception carries: code (str), message (str), suggestion (str), docs_url (str).
Error codes follow the pattern E{category}{sequence}:
  E1xxx = Authentication errors
  E2xxx = Sandbox creation errors
  E3xxx = Execution errors
  E4xxx = Filesystem errors
  E5xxx = Network errors
  E6xxx = Session errors
  E7xxx = Deploy, build, and Docker errors
"""

from __future__ import annotations

from typing import Any


class SandboxError(Exception):
    """Base exception for all Easy Sandbox errors."""

    code: str = "E0000"
    suggestion: str = ""
    docs_url: str = ""  # TODO: 待补充正式文档 URL

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        suggestion: str | None = None,
        docs_url: str | None = None,
    ) -> None:
        self.message = message
        if code is not None:
            self.code = code
        if suggestion is not None:
            self.suggestion = suggestion
        if docs_url is not None:
            self.docs_url = docs_url
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [f"[{self.code}] {self.message}"]
        if self.suggestion:
            parts.append(f"  Suggestion: {self.suggestion}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
            "docs_url": self.docs_url,
        }


# --- Authentication Errors (E1xxx) ---


class AuthenticationError(SandboxError):
    """Base for all authentication failures."""

    code = "E1000"


class InvalidAPIKeyError(AuthenticationError):
    """API Key is invalid or missing."""

    code = "E1001"
    suggestion = "Check your E2B_API_KEY environment variable or pass api_key parameter."


class TokenExpiredError(AuthenticationError):
    """Authentication token has expired."""

    code = "E1002"
    suggestion = (
        "The SDK should auto-refresh tokens. If this persists, check system clock synchronization."
    )


class InvalidCredentialsError(AuthenticationError):
    """AK/SK credentials are invalid."""

    code = "E1003"
    suggestion = (
        "Check ALICLOUD_ACCESS_KEY_ID and ALICLOUD_ACCESS_KEY_SECRET environment variables."
    )


class TokenExchangeError(AuthenticationError):
    """AK/SK to API Key token exchange failed."""

    code = "E1004"
    suggestion = (
        "Token exchange from AK/SK to Platform API key failed. "
        "Use E2B_API_KEY directly, or check AK/SK credentials and network connectivity."
    )


# --- Creation Errors (E2xxx) ---


class SandboxCreationError(SandboxError):
    """Base for sandbox creation failures."""

    code = "E2000"


class TemplateNotFoundError(SandboxCreationError):
    """Specified template does not exist."""

    code = "E2001"
    suggestion = "Run 'ebx template list' to see available templates."


class QuotaExceededError(SandboxCreationError):
    """Sandbox quota has been exceeded."""

    code = "E2002"
    suggestion = "Destroy idle sandboxes or request a quota increase."


class RegionUnavailableError(SandboxCreationError):
    """Requested region is not available."""

    code = "E2003"
    suggestion = "Try a different region or check service availability."


class TemplateParseError(SandboxCreationError):
    """A matching template was found but its definition is malformed.

    Raised fail-closed by the capability resolver: when a template that
    *matches* the requested id fails model validation, we refuse to fall
    back to :data:`DEFAULT_CAPABILITIES` (which would silently widen the
    granted permissions).
    """

    code = "E2004"
    suggestion = (
        "Fix the template.yaml (see the validation error above); "
        "capabilities are NOT granted until the template parses cleanly."
    )


class QwenCodeNotInstalledError(SandboxCreationError):
    """Qwen Code executable was not found on PATH or in ~/.ebx/bin."""

    code = "E2005"
    suggestion = (
        "Install Qwen Code, then retry. Interactive install prompt: run the "
        "command again in a terminal. Or install manually via the official "
        "installer (see 'ebx create --help'), or bypass AI generation with "
        "'ebx create --template <name>'."
    )


class QwenCodeCredentialError(SandboxCreationError):
    """Qwen Code is installed but no usable model credentials were found."""

    code = "E2006"
    suggestion = (
        "Configure a DashScope/ModelStudio API key for Qwen Code: "
        "'ebx config set qwen_code_api_key <KEY>' (interactive: 'ebx config init'), "
        "or export DASHSCOPE_API_KEY / OPENAI_API_KEY."
    )


class AICodegenError(SandboxCreationError):
    """Qwen Code failed to generate a valid Dockerfile / template.yaml."""

    code = "E2007"
    suggestion = (
        "The AI generation step failed or produced incomplete files. "
        "Inspect the generated workspace (path shown above), then retry "
        "'ebx create \"<description>\"' or fall back to "
        "'ebx create --template <name>'."
    )


class DescriptionClarificationError(SandboxCreationError):
    """The description stayed below the completeness threshold.

    Raised when the single-question clarification loop cannot be completed:
    a non-interactive session (or JSON mode) would have to ask the user, or
    the interactive user cancelled / hit EOF before reaching the threshold.
    """

    code = "E2008"
    suggestion = (
        "Add the missing details (runtime, dependencies, entry command, ports, "
        "resources, data) to DESCRIPTION, or pass --yes/-y to generate from the "
        "current description anyway, or use 'ebx create --template <name>'."
    )


# --- Execution Errors (E3xxx) ---


class ExecutionError(SandboxError):
    """Base for command/code execution failures."""

    code = "E3000"


class CommandTimeoutError(ExecutionError):
    """Command execution timed out."""

    code = "E3001"
    suggestion = "Increase the timeout parameter or check if the command is hanging."


class ProcessError(ExecutionError):
    """Process exited with non-zero code."""

    code = "E3002"

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = -1,
        stdout: str = "",
        stderr: str = "",
        **kwargs: Any,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message, **kwargs)


class CodeExecutionError(ExecutionError):
    """Code execution failed."""

    code = "E3003"
    suggestion = "Check code syntax and runtime dependencies in the sandbox template."


class CapabilityNotSupportedError(ExecutionError):
    """Requested capability is not enabled for this sandbox/template."""

    code = "E3004"

    def __init__(
        self,
        capability: str,
        *,
        message: str | None = None,
        suggestion: str | None = None,
        **kwargs: object,
    ) -> None:
        self.capability = capability
        _message = message or (
            f"Capability '{capability}' is not supported by this sandbox template."
        )
        _suggestion = suggestion or (
            f"Declare '{capability}' in the template's capabilities list "
            "(template.yaml) or use a template that supports it."
        )
        super().__init__(_message, suggestion=_suggestion, **kwargs)  # type: ignore[arg-type]


class CommandNotFoundError(ExecutionError):
    """Raised when :meth:`Sandbox.custom` cannot resolve a named command.

    ``custom()`` checks two sources in order — the template's
    ``custom_commands`` (mechanism A) and the in-sandbox SandboxServer
    registry (mechanism B).  This error is raised when neither source
    yields the command, either because it is genuinely unknown (server
    returned 404) or because the SandboxServer could not be reached.
    """

    code = "E3005"

    def __init__(
        self,
        name: str,
        *,
        checked: list[str],
        server_status: str = "",
        template_commands: list[str] | None = None,
        **kwargs: object,
    ) -> None:
        parts = [f"Command {name!r} not found."]
        parts.append(f"Checked sources: {', '.join(checked)}.")
        if template_commands is not None:
            available = ", ".join(sorted(template_commands)) or "(none)"
            parts.append(f"Available template commands: {available}.")
        if server_status:
            parts.append(f"Server: {server_status}.")
        _suggestion = kwargs.pop("suggestion", None) or (
            "Check the command name, the template's custom_commands, and "
            "whether the SandboxServer is running (sandbox.server.start())."
        )
        super().__init__(
            " ".join(parts),
            suggestion=_suggestion,  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        self.command_name = name
        self.checked_sources = checked


class EnvdRpcError(ExecutionError):
    """The sandbox envd rejected an RPC call with an HTTP error status.

    Raised by the transport layer (``HttpClient.envd_stream``) when the
    envd responds with HTTP >= 400 (e.g. a ``process.Process/Start`` 500
    for an unknown executable).  Carries the *structured* envd JSON error
    body (``envd_error``, parsed when the response body is JSON) so upper
    layers can map it to friendly messages, plus the HTTP status and RPC
    path.  The exception text deliberately avoids the full sandbox URL
    (which embeds the sandbox ID / internal host) — only the RPC path is
    included, and no separate WARNING log is emitted by default.
    """

    code = "E3006"
    suggestion = (
        "The sandbox envd rejected this RPC call. Check the command and "
        "arguments, or run with 'ebx -v' for the raw error response."
    )

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        rpc_path: str = "",
        envd_error: dict[str, Any] | None = None,
        body_text: str = "",
        **kwargs: Any,
    ) -> None:
        self.status_code = status_code
        self.rpc_path = rpc_path
        self.envd_error = envd_error
        self.body_text = body_text
        super().__init__(message, **kwargs)


# --- Filesystem Errors (E4xxx) ---


class FileOperationError(SandboxError):
    """Base for filesystem operation failures."""

    code = "E4000"


class FileNotFoundError_(FileOperationError):  # noqa: N801, N818
    """File or directory not found in sandbox."""

    code = "E4001"
    suggestion = "Use files.list() to check available files, or files.exists() to verify path."
    # Note: named with underscore to avoid shadowing builtin FileNotFoundError


class PermissionDeniedError(FileOperationError):
    """Permission denied for file operation."""

    code = "E4002"
    suggestion = "Check file permissions in the sandbox."


# --- Session Errors (E6xxx) ---


class SessionError(SandboxError):
    """Base for session management failures."""

    code = "E6000"


class SessionNotFoundError(SessionError):
    """Session not found in the store."""

    code = "E6001"
    suggestion = (
        "Check session files in ~/.ebx/sessions/ "
        "or use LocalSessionStore().list() programmatically."
    )


class SessionAlreadyExistsError(SessionError):
    """Session with the given name already exists."""

    code = "E6002"
    suggestion = "Use a different name or stop the existing session first."


# --- Deploy Errors (E7xxx) ---


class DeployError(SandboxError):
    """Base for NL-driven deployment failures."""

    code = "E7000"


class DeployLLMKeyMissingError(DeployError):
    """No LLM API key found for the qwen-code agent."""

    code = "E7001"
    suggestion = (
        "Set BAILIAN_CODING_PLAN_API_KEY, DASHSCOPE_API_KEY, or "
        "OPENAI_API_KEY environment variable."
    )


class DeployAgentError(DeployError):
    """The qwen-code agent returned an error or unexpected output."""

    code = "E7002"
    suggestion = "Check the raw_output on DeployResult for details."


class DeployTimeoutError(DeployError):
    """Deployment exceeded the maximum wall-clock time."""

    code = "E7003"
    suggestion = "Increase max_wall_time or simplify the deployment task."


# --- Template Build Errors (E7010+) ---


class TemplateBuildError(SandboxError):
    """Template build failed."""

    code = "E7010"
    suggestion = "Check the Dockerfile and build logs for errors."


class TemplateBuildTimeoutError(SandboxError):
    """Template build timed out."""

    code = "E7011"
    suggestion = "Increase the build timeout or simplify the Dockerfile."


class DockerBuildError(SandboxError):
    """Local Docker build failed."""

    code = "E7020"
    suggestion = "Check the Dockerfile syntax and ensure Docker daemon is running."


class ACRPushError(SandboxError):
    """Failed to push image to Alibaba Cloud ACR."""

    code = "E7021"
    suggestion = (
        "Verify ACR credentials and registry URL. Ensure the namespace and repository exist."
    )


class ACRLoginError(SandboxError):
    """Failed to login to Alibaba Cloud ACR."""

    code = "E7022"
    suggestion = "Check AccessKey/AccessSecret credentials and registry URL."


# --- Network Errors (E5xxx) ---


class NetworkError(SandboxError):
    """Base for network/connection failures."""

    code = "E5000"


class ConnectionError_(NetworkError):  # noqa: N801, N818
    """Failed to connect to sandbox service."""

    code = "E5001"
    suggestion = "Check network connectivity and firewall rules."
    # Note: named with underscore to avoid shadowing builtin ConnectionError


class GitHubRateLimitError(NetworkError):
    """GitHub's anonymous API rate limit was hit while fetching templates.

    Deliberately shares the E5000 code of :class:`NetworkError`: to users
    it remains one network error, while the CLI can detect this subtype and
    offer a one-shot interactive ``github_token`` setup (task 206) before
    giving up.  The raised ``suggestion`` always carries the officially
    verified fine-grained PAT URL (see
    :mod:`easy_sandbox.utils.github_token`).
    """

    code = "E5000"


__all__ = [
    "SandboxError",
    "AuthenticationError",
    "InvalidAPIKeyError",
    "TokenExpiredError",
    "InvalidCredentialsError",
    "TokenExchangeError",
    "SandboxCreationError",
    "TemplateNotFoundError",
    "QuotaExceededError",
    "RegionUnavailableError",
    "TemplateParseError",
    "QwenCodeNotInstalledError",
    "QwenCodeCredentialError",
    "AICodegenError",
    "DescriptionClarificationError",
    "ExecutionError",
    "CommandTimeoutError",
    "ProcessError",
    "CodeExecutionError",
    "CapabilityNotSupportedError",
    "CommandNotFoundError",
    "EnvdRpcError",
    "FileOperationError",
    "FileNotFoundError_",
    "PermissionDeniedError",
    "DeployError",
    "DeployLLMKeyMissingError",
    "DeployAgentError",
    "DeployTimeoutError",
    "TemplateBuildError",
    "TemplateBuildTimeoutError",
    "DockerBuildError",
    "ACRPushError",
    "ACRLoginError",
    "NetworkError",
    "ConnectionError_",
    "GitHubRateLimitError",
    "SessionError",
    "SessionNotFoundError",
    "SessionAlreadyExistsError",
]
