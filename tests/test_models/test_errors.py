"""Tests for the exception hierarchy."""

from __future__ import annotations

import pytest

from easy_sandbox.models.errors import (
    AICodegenError,
    AuthenticationError,
    CodeExecutionError,
    CommandTimeoutError,
    ConnectionError_,
    EnvdRpcError,
    ExecutionError,
    FileNotFoundError_,
    FileOperationError,
    GitHubRateLimitError,
    InvalidAPIKeyError,
    InvalidCredentialsError,
    NetworkError,
    PermissionDeniedError,
    ProcessError,
    QuotaExceededError,
    QwenCodeStartupError,
    QwenCodeTimeoutError,
    RegionUnavailableError,
    SandboxCreationError,
    SandboxError,
    TemplateBuildError,
    TemplateBuildTimeoutError,
    TemplateNotFoundError,
    TokenExpiredError,
)
from easy_sandbox.models.errors import (
    __all__ as errors_all,
)

# ---- Base SandboxError ----


class TestSandboxError:
    def test_basic_instantiation(self):
        err = SandboxError("something went wrong")
        assert err.message == "something went wrong"
        assert err.code == "E0000"
        assert err.suggestion == ""
        assert err.docs_url == ""

    def test_custom_fields(self):
        err = SandboxError(
            "oops",
            code="E9999",
            suggestion="try again",
            docs_url="https://example.com",
        )
        assert err.code == "E9999"
        assert err.suggestion == "try again"
        assert err.docs_url == "https://example.com"

    def test_str_format(self):
        err = SandboxError("fail", code="E0001", suggestion="fix it")
        s = str(err)
        assert "[E0001]" in s
        assert "fail" in s
        assert "Suggestion: fix it" in s

    def test_str_no_suggestion(self):
        err = SandboxError("fail")
        s = str(err)
        assert "Suggestion" not in s

    def test_to_dict(self):
        err = SandboxError("msg", code="E0001", suggestion="tip")
        d = err.to_dict()
        assert d["code"] == "E0001"
        assert d["message"] == "msg"
        assert d["suggestion"] == "tip"
        assert "docs_url" in d

    def test_is_exception(self):
        err = SandboxError("test")
        assert isinstance(err, Exception)
        with pytest.raises(SandboxError):
            raise err


# ---- Authentication Errors ----


class TestAuthenticationErrors:
    def test_authentication_error_inherits(self):
        err = AuthenticationError("auth fail")
        assert isinstance(err, SandboxError)
        assert err.code == "E1000"

    def test_invalid_api_key(self):
        err = InvalidAPIKeyError("bad key")
        assert isinstance(err, AuthenticationError)
        assert isinstance(err, SandboxError)
        assert err.code == "E1001"
        assert "E2B_API_KEY" in err.suggestion

    def test_token_expired(self):
        err = TokenExpiredError("expired")
        assert isinstance(err, AuthenticationError)
        assert err.code == "E1002"
        assert "auto-refresh" in err.suggestion

    def test_invalid_credentials(self):
        err = InvalidCredentialsError("bad creds")
        assert isinstance(err, AuthenticationError)
        assert err.code == "E1003"
        assert "ALICLOUD" in err.suggestion


# ---- Creation Errors ----


class TestCreationErrors:
    def test_sandbox_creation_error_inherits(self):
        err = SandboxCreationError("create fail")
        assert isinstance(err, SandboxError)
        assert err.code == "E2000"

    def test_template_not_found(self):
        err = TemplateNotFoundError("no template")
        assert isinstance(err, SandboxCreationError)
        assert err.code == "E2001"
        assert "ebx template list" in err.suggestion

    def test_quota_exceeded(self):
        err = QuotaExceededError("over quota")
        assert isinstance(err, SandboxCreationError)
        assert err.code == "E2002"

    def test_region_unavailable(self):
        err = RegionUnavailableError("bad region")
        assert isinstance(err, SandboxCreationError)
        assert err.code == "E2003"


# ---- Execution Errors ----


class TestExecutionErrors:
    def test_execution_error_inherits(self):
        err = ExecutionError("exec fail")
        assert isinstance(err, SandboxError)
        assert err.code == "E3000"

    def test_command_timeout(self):
        err = CommandTimeoutError("timed out")
        assert isinstance(err, ExecutionError)
        assert err.code == "E3001"

    def test_process_error(self):
        err = ProcessError("exit 1", exit_code=1, stdout="out", stderr="err")
        assert isinstance(err, ExecutionError)
        assert err.code == "E3002"
        assert err.exit_code == 1
        assert err.stdout == "out"
        assert err.stderr == "err"

    def test_process_error_defaults(self):
        err = ProcessError("fail")
        assert err.exit_code == -1
        assert err.stdout == ""
        assert err.stderr == ""

    def test_code_execution_error(self):
        err = CodeExecutionError("bad code")
        assert isinstance(err, ExecutionError)
        assert err.code == "E3003"

    def test_envd_rpc_error_structured_fields(self):
        """EnvdRpcError carries envd error details for upper-layer mapping."""
        err = EnvdRpcError(
            "envd RPC /process.Process/Start failed (HTTP 500): exec not found",
            status_code=500,
            rpc_path="/process.Process/Start",
            envd_error={"error": {"code": "not_found", "message": "exec not found"}},
            body_text='{"error":{...}}',
        )
        assert isinstance(err, ExecutionError)
        assert isinstance(err, SandboxError)
        assert err.code == "E3006"
        assert err.status_code == 500
        assert err.rpc_path == "/process.Process/Start"
        assert err.envd_error["error"]["message"] == "exec not found"
        assert err.body_text == '{"error":{...}}'

    def test_envd_rpc_error_defaults(self):
        err = EnvdRpcError("boom")
        assert err.status_code == 0
        assert err.rpc_path == ""
        assert err.envd_error is None
        assert err.body_text == ""
        assert err.code == "E3006"
        assert err.suggestion  # actionable by default


# ---- Filesystem Errors ----


class TestFilesystemErrors:
    def test_file_operation_error_inherits(self):
        err = FileOperationError("fs fail")
        assert isinstance(err, SandboxError)
        assert err.code == "E4000"

    def test_file_not_found(self):
        err = FileNotFoundError_("not found")
        assert isinstance(err, FileOperationError)
        assert err.code == "E4001"

    def test_permission_denied(self):
        err = PermissionDeniedError("denied")
        assert isinstance(err, FileOperationError)
        assert err.code == "E4002"


# ---- Network Errors ----


class TestNetworkErrors:
    def test_network_error_inherits(self):
        err = NetworkError("net fail")
        assert isinstance(err, SandboxError)
        assert err.code == "E5000"

    def test_connection_error(self):
        err = ConnectionError_("conn fail")
        assert isinstance(err, NetworkError)
        assert err.code == "E5001"

    def test_github_rate_limit_error(self):
        err = GitHubRateLimitError("rate limited")
        assert isinstance(err, NetworkError)
        assert err.code == "E5000"


# ---- AI Generation Subtypes ----


class TestAICodegenSubtypeErrors:
    """The classified Qwen Code failures share E2007 by design.

    Like :class:`GitHubRateLimitError` above, these subtypes keep the
    user-visible code of their parent so the CLI output never changes;
    only the research round reads the type to derive a stable reason.
    """

    def test_timeout_error_shares_e2007(self):
        err = QwenCodeTimeoutError("did not finish within 240s")
        assert isinstance(err, AICodegenError)
        assert err.code == "E2007"

    def test_startup_error_shares_e2007(self):
        err = QwenCodeStartupError("Failed to start Qwen Code: boom")
        assert isinstance(err, AICodegenError)
        assert err.code == "E2007"


# ---- Unique Codes ----


class TestErrorCodeUniqueness:
    def test_all_error_codes_unique(self):
        """Every concrete error class should have a unique error code."""
        all_classes = [
            SandboxError,
            AuthenticationError,
            InvalidAPIKeyError,
            TokenExpiredError,
            InvalidCredentialsError,
            SandboxCreationError,
            TemplateNotFoundError,
            QuotaExceededError,
            RegionUnavailableError,
            ExecutionError,
            CommandTimeoutError,
            ProcessError,
            CodeExecutionError,
            FileOperationError,
            FileNotFoundError_,
            PermissionDeniedError,
            NetworkError,
            ConnectionError_,
            TemplateBuildError,
            TemplateBuildTimeoutError,
        ]
        codes = [cls.code for cls in all_classes]
        assert len(codes) == len(set(codes)), f"Duplicate codes found: {codes}"


# ---- __all__ ----


class TestErrorsAll:
    def test_all_list_contains_all_classes(self):
        expected = {
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
            "QwenCodeTimeoutError",
            "QwenCodeStartupError",
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
            "NetworkError",
            "ConnectionError_",
            "GitHubRateLimitError",
            "SessionError",
            "SessionNotFoundError",
            "SessionAlreadyExistsError",
            "TemplateBuildError",
            "TemplateBuildTimeoutError",
            "DockerBuildError",
            "ACRPushError",
            "ACRLoginError",
        }
        assert set(errors_all) == expected
