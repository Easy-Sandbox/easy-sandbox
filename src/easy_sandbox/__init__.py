"""Easy Sandbox SDK — Create, manage, and interact with cloud sandboxes."""

from easy_sandbox._version import __version__

__all__ = [
    "__version__",
    "Sandbox",
    "SandboxError",
    "AuthenticationError",
    "SandboxCreationError",
    "ExecutionError",
    "FileOperationError",
    "NetworkError",
    "sandbox",
]


def __getattr__(name: str):
    if name == "Sandbox":
        from easy_sandbox.api.sandbox import Sandbox
        return Sandbox
    if name in (
        "SandboxError",
        "AuthenticationError",
        "SandboxCreationError",
        "ExecutionError",
        "FileOperationError",
        "NetworkError",
    ):
        from easy_sandbox.models import errors
        return getattr(errors, name)
    if name == "sandbox":
        from easy_sandbox.declarative.decorator import sandbox as _sandbox
        return _sandbox
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
