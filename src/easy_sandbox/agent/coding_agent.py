"""Pluggable coding-agent backend boundary for ``ebx create "<description>"``.

The natural-language create path drives a *coding agent* on the host to
turn one free-form description into a Dockerfile + ``template.yaml`` (and,
for interactive sessions, to assess the description's completeness first).
Today that agent is Qwen Code; the future may plug in Qoder CLI, Codex,
Claude Code, or a user-defined command.

This module is the seam that keeps the create pipeline honest about that:
:mod:`easy_sandbox.cli.commands.sandbox` orchestrates the flow through the
:class:`CodingAgentBackend` protocol and never imports a concrete agent
adapter itself.  :class:`QwenCodeBackend` is the only shipped backend and
delegates to the verified Qwen Code modules
(:mod:`easy_sandbox.agent.qwen_code`, :mod:`easy_sandbox.agent.codegen`,
:mod:`easy_sandbox.agent.clarify`).

Intentionally **not** implemented here (recorded as migration points in
``.agents/notes/implemented/architecture/2026-09-29-pluggable-coding-agent-backend.md``):

* no plugin registry / entry-point discovery — the shipped set lives in a
  plain module-level mapping;
* no ``--coding-agent`` command-line selector — resolution always returns
  the default backend;
* the clarification protocol inside :mod:`easy_sandbox.agent.clarify` and
  the generation pipeline inside :mod:`easy_sandbox.agent.codegen` speak
  the Qwen headless dialect (positional prompt + ``--json-schema`` /
  ``--session-id`` / ``--resume``); a second backend implements
  :meth:`~CodingAgentBackend.research`,
  :meth:`~CodingAgentBackend.assess`, and
  :meth:`~CodingAgentBackend.generate` natively, or those protocols get
  factored into shared helpers first;
* ``ebx config init`` / ``ebx config set`` still name the Qwen keys
  explicitly (the backend class variables here are the single source for
  the create path, not for the config wizard).

Adapters import their implementation modules lazily inside each method, so
tests keep intercepting the existing patch points on the source modules
(e.g. ``easy_sandbox.agent.qwen_code.find_qwen_code_binary``,
``easy_sandbox.agent.codegen.generate_template_files``,
``easy_sandbox.agent.clarify.evaluate``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol

from easy_sandbox.models.errors import (
    QwenCodeCredentialError,
    QwenCodeNotInstalledError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from easy_sandbox.agent.clarify import ClarifyAssessment
    from easy_sandbox.agent.codegen import CodegenResult
    from easy_sandbox.models.errors import SandboxCreationError

__all__ = [
    "DEFAULT_CODING_AGENT",
    "CodingAgentBackend",
    "CodingAgentCredentials",
    "QwenCodeBackend",
    "resolve_coding_agent_backend",
]

#: Backend selected when the caller does not name one explicitly.
DEFAULT_CODING_AGENT = "qwen-code"


class CodingAgentCredentials(Protocol):
    """Minimal credential contract the create flow consumes."""

    def as_env(self) -> dict[str, str]:
        """Return the environment variables to inject into the agent run."""
        ...


class CodingAgentBackend(Protocol):
    """What ``ebx create "<description>"`` needs from a coding agent.

    The protocol covers the five phases the create pipeline runs before
    deployment: locating/installing the agent, resolving model
    credentials, researching the public facts behind the description
    (:meth:`research`), completing the description (:meth:`assess`), and
    generating the template files (:meth:`generate`).
    """

    name: ClassVar[str]
    """Stable backend identifier (e.g. ``"qwen-code"``)."""

    display_name: ClassVar[str]
    """Human-readable name used in every user-facing message."""

    config_key: ClassVar[str]
    """Configuration/credential name (e.g. ``qwen_code_api_key``)."""

    env_var: ClassVar[str]
    """Environment variable storing the credential (``EBX_QWEN_CODE_API_KEY``)."""

    base_url_config_key: ClassVar[str]
    """Config key holding the OpenAI-compatible base URL override."""

    model_config_key: ClassVar[str]
    """Config key holding the model override."""

    credential_prompt: ClassVar[str]
    """Prompt label shown when the credential must be entered interactively."""

    credential_error: ClassVar[type[SandboxCreationError]]
    """Error type raised when no usable credentials exist."""

    not_installed_error: ClassVar[type[SandboxCreationError]]
    """Error type raised when the agent executable cannot be located."""

    def quick_setup_lines(self, *, reason: str) -> list[str]:
        """Wording of the Quick Setup guide for the AI template path.

        *reason* is ``"not-installed"`` or ``"no-credentials"``; the
        returned lines are printed verbatim by the CLI.
        """
        ...

    def find_binary(self) -> Path | None:
        """Locate the agent executable; ``None`` when it is not installed."""
        ...

    def install(self, *, on_progress: Callable[[str], None] | None = None) -> Path:
        """Install the agent and return the executable path.

        Raises:
            SandboxCreationError: When installation fails (e.g. the
                backend's ``not_installed_error``).
        """
        ...

    def resolve_credentials(
        self,
        *,
        stored_api_key: str | None = None,
        llm_api_key: str | None = None,
        stored_base_url: str | None = None,
        stored_model: str | None = None,
    ) -> CodingAgentCredentials:
        """Resolve model credentials from stored/configured/environment sources.

        Raises:
            SandboxCreationError: The backend's ``credential_error`` when
                nothing usable is found.
        """
        ...

    def prepare_workdir(self, description: str) -> tuple[Path, str]:
        """Create the generation workspace; return ``(workdir, template_name)``.

        The clarification phase and the generation run share this
        directory: native agent sessions are keyed by the working
        directory, so both phases must use the same ``cwd`` for the
        session pair (``--session-id`` / ``--resume``) to line up.
        """
        ...

    def research(
        self,
        prompt: str,
        *,
        workdir: Path,
        binary: Path | str,
        env: Mapping[str, str] | None,
        session_id: str,
    ) -> bool:
        """Run the plain research round that settles public facts first.

        Runs on the native session *session_id* **without** structured
        output, so the agent's own tool loop (web fetch / shell) is free
        to run before any verdict ends the session.  Returns ``False``
        when the round is unavailable; the caller then continues straight
        to :meth:`assess` — research is an enhancement, never a gate.
        """
        ...

    def assess(
        self,
        prompt: str,
        *,
        workdir: Path,
        binary: Path | str,
        env: Mapping[str, str] | None,
        session_id: str | None = None,
        resume: str | None = None,
    ) -> ClarifyAssessment | None:
        """Run one structured completeness-assessment round.

        The caller sets exactly one of *session_id* (the session may not
        exist yet) or *resume* (continue the session created by
        :meth:`research` or a previous round).  ``None`` means the
        assessment is unavailable: the create flow degrades to direct
        generation instead of blocking — a backend without a
        structured-output protocol can implement this as ``return None``.
        """
        ...

    def generate(
        self,
        description: str,
        *,
        workdir: Path,
        template_name: str,
        resume_session: str | None = None,
        binary: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> CodegenResult:
        """Generate ``Dockerfile`` + ``template.yaml`` in *workdir*.

        *resume_session* continues the native session created by
        :meth:`assess`, so the agent keeps the clarification context in
        its own memory.

        Raises:
            SandboxCreationError: When generation fails or produces
                invalid artifacts — never a silent fallback.
        """
        ...


class QwenCodeBackend(CodingAgentBackend):
    """Qwen Code adapter (the only backend shipped today).

    Every method delegates to the verified implementation modules and
    imports them lazily at call time, so existing test patch points on
    those modules (``easy_sandbox.agent.qwen_code.*``,
    ``easy_sandbox.agent.codegen.*``, ``easy_sandbox.agent.clarify.evaluate``)
    keep working unchanged.
    """

    name = "qwen-code"
    display_name = "Qwen Code"
    config_key = "qwen_code_api_key"
    env_var = "EBX_QWEN_CODE_API_KEY"
    base_url_config_key = "qwen_code_base_url"
    model_config_key = "qwen_code_model"
    credential_prompt = "Qwen Code API key (DashScope/ModelStudio, hidden; leave empty to cancel)"
    credential_error = QwenCodeCredentialError
    not_installed_error = QwenCodeNotInstalledError

    def quick_setup_lines(self, *, reason: str) -> list[str]:
        from easy_sandbox.agent.qwen_code import official_install_command

        lines = [f"Quick Setup - AI template generation ({self.display_name}):"]
        if reason == "not-installed":
            lines += [
                f"  1. Install the {self.display_name} CLI (official standalone build):",
                f"       {official_install_command()}",
                "     or re-run 'ebx create \"<description>\"' and accept the install prompt",
                "     or bypass AI generation with:  ebx create --template base",
            ]
        else:
            lines += [
                "  1. Configure a DashScope/ModelStudio API key for Qwen Code:",
                f"       ebx config set {self.config_key} <KEY>   (stored in ~/.ebx/.env)",
                "       or run the guided wizard:  ebx config init",
                "       (exported OPENAI_API_KEY / DASHSCOPE_API_KEY also work)",
            ]
        lines.append("  2. Docs: https://github.com/QwenLM/qwen-code")
        return lines

    def find_binary(self) -> Path | None:
        from easy_sandbox.agent.qwen_code import find_qwen_code_binary

        return find_qwen_code_binary()

    def install(self, *, on_progress: Callable[[str], None] | None = None) -> Path:
        from easy_sandbox.agent.qwen_code import download_and_install_standalone

        return download_and_install_standalone(on_progress=on_progress)

    def resolve_credentials(
        self,
        *,
        stored_api_key: str | None = None,
        llm_api_key: str | None = None,
        stored_base_url: str | None = None,
        stored_model: str | None = None,
    ) -> CodingAgentCredentials:
        from easy_sandbox.agent.qwen_code import resolve_qwen_code_credentials

        return resolve_qwen_code_credentials(
            stored_api_key=stored_api_key,
            llm_api_key=llm_api_key,
            stored_base_url=stored_base_url,
            stored_model=stored_model,
        )

    def prepare_workdir(self, description: str) -> tuple[Path, str]:
        from easy_sandbox.agent.codegen import prepare_workdir

        return prepare_workdir(description)

    def research(
        self,
        prompt: str,
        *,
        workdir: Path,
        binary: Path | str,
        env: Mapping[str, str] | None,
        session_id: str,
    ) -> bool:
        from easy_sandbox.agent.clarify import run_research

        return run_research(
            prompt,
            binary=binary,
            env=env,
            cwd=workdir,
            session_id=session_id,
        )

    def assess(
        self,
        prompt: str,
        *,
        workdir: Path,
        binary: Path | str,
        env: Mapping[str, str] | None,
        session_id: str | None = None,
        resume: str | None = None,
    ) -> ClarifyAssessment | None:
        from easy_sandbox.agent.clarify import evaluate

        return evaluate(
            prompt,
            binary=binary,
            env=env,
            cwd=workdir,
            session_id=session_id,
            resume=resume,
        )

    def generate(
        self,
        description: str,
        *,
        workdir: Path,
        template_name: str,
        resume_session: str | None = None,
        binary: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> CodegenResult:
        from easy_sandbox.agent.codegen import generate_template_files

        return generate_template_files(
            description,
            workdir=workdir,
            template_name=template_name,
            resume_session=resume_session,
            binary=binary,
            env=env,
            on_progress=on_progress,
        )


#: Shipped backends: stable name -> backend class.  Deliberately a plain
#: mapping — entry-point based third-party plugins are a migration point.
_BACKENDS: dict[str, type[CodingAgentBackend]] = {QwenCodeBackend.name: QwenCodeBackend}


def resolve_coding_agent_backend(name: str | None = None) -> CodingAgentBackend:
    """Instantiate the coding-agent backend selected by *name*.

    ``None`` (the default) selects :data:`DEFAULT_CODING_AGENT`.  Unknown
    names raise :class:`ValueError` — the flow never silently falls back
    to a different agent than the caller asked for.
    """
    key = (name or DEFAULT_CODING_AGENT).strip()
    try:
        backend_class = _BACKENDS[key]
    except KeyError:
        available = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown coding agent backend {key!r}; available: {available}.") from None
    return backend_class()
