"""AI code generation for ``ebx create "<description>"``.

Orchestrates a Qwen Code headless run that produces a Dockerfile and a
minimal ``template.yaml`` inside a dedicated workspace, validates both
artifacts (the manifest is validated with the very same schema used by
:func:`easy_sandbox.api.capability.parse_template_data`), and hands the
workspace over to the existing build/deploy pipeline.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from easy_sandbox.agent.qwen_code import run_qwen_code_headless
from easy_sandbox.api.capability import parse_template_data
from easy_sandbox.models.errors import AICodegenError
from easy_sandbox.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = get_logger("agent.codegen")

#: Wall-clock budget for one code-generation run (seconds).
DEFAULT_CODEGEN_TIMEOUT = 600.0

#: Prefix for AI-generated template names (marks provenance, avoids clashes).
TEMPLATE_NAME_PREFIX = "ebx-nl"

_FROM_INSTRUCTION_RE = re.compile(r"^\s*FROM\s+\S", re.IGNORECASE | re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_CODEGEN_PROMPT_TEMPLATE = """\
你是 Easy Sandbox 的模板生成器。请根据下面的自然语言需求，在当前工作目录中生成两个文件。

用户需求：{description}

必须创建的文件：
1. `Dockerfile`：
   - 必须以 FROM 指令开始（选择官方基础镜像，例如 python:3.12-slim、node:20-slim、ubuntu:24.04）
   - 安装满足上述需求所需的系统包与依赖
   - 保持精简、可直接执行 docker build
2. `template.yaml`：
   name: {template_name}
   description: <一句话中文描述，不超过 50 字>
   resources:
     cpu: <1-8 的整数>
     memory: <512-16384 的整数，单位 MB>

限制：
- 只创建这两个文件，不要创建任何其他文件或目录
- 不要运行 docker，不要安装任何东西
- 完成后只需用一句话总结你生成了什么
"""


@dataclass
class CodegenResult:
    """Outcome of one AI code-generation run."""

    workdir: Path
    """Workspace containing the generated ``Dockerfile`` / ``template.yaml``."""

    template_name: str
    """Deterministic template name (``ebx-nl-<slug>-<token>``)."""

    dockerfile: Path
    template_yaml: Path
    description: str = ""
    raw_output: str = ""
    """Final assistant text from Qwen Code (for diagnostics)."""


def default_generated_dir() -> Path:
    """Root directory for generated workspaces: ``~/.ebx/generated``."""
    return Path.home() / ".ebx" / "generated"


def default_codegen_timeout() -> float:
    """Timeout used for code generation, overridable via environment."""
    raw = os.environ.get("EBX_QWEN_CODEGEN_TIMEOUT")
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return DEFAULT_CODEGEN_TIMEOUT
        if value > 0:
            return value
    return DEFAULT_CODEGEN_TIMEOUT


def _slugify(text: str, *, fallback: str = "sandbox") -> str:
    """Reduce *text* to a short ``[a-z0-9-]`` slug (ASCII only)."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    slug = slug[:16].strip("-")
    return slug or fallback


def make_template_name(description: str, *, token: str | None = None) -> str:
    """Build a deterministic, collision-resistant template name."""
    suffix = token if token is not None else secrets.token_hex(3)
    return f"{TEMPLATE_NAME_PREFIX}-{_slugify(description)}-{suffix}"


def build_codegen_prompt(description: str, template_name: str) -> str:
    """Build the Qwen Code prompt used for template generation.

    When the clarification loop ran, the generation run resumes the *same*
    native Qwen Code session (``--resume``), so the agent already holds
    the description and every question/answer in its own conversation
    memory — the prompt deliberately does not replay the transcript.
    """
    return _CODEGEN_PROMPT_TEMPLATE.format(
        description=description.strip(),
        template_name=template_name,
    )


def _has_from_instruction(dockerfile: Path) -> bool:
    try:
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_FROM_INSTRUCTION_RE.search(text))


def _load_template_yaml(template_yaml: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(template_yaml.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AICodegenError(
            f"Generated template.yaml could not be parsed: {exc}",
            suggestion=(
                f"Inspect {template_yaml.parent} and retry, or fall back to "
                "'ebx create --template <name>'."
            ),
        ) from exc
    if not isinstance(data, dict):
        raise AICodegenError(
            "Generated template.yaml is not a YAML mapping.",
            suggestion=(
                f"Inspect {template_yaml.parent} and retry, or fall back to "
                "'ebx create --template <name>'."
            ),
        )
    return data


def prepare_workdir(
    description: str,
    *,
    base_dir: Path | None = None,
) -> tuple[Path, str]:
    """Create the generation workspace and its deterministic template name.

    Returns ``(workdir, template_name)``.  The clarification loop and the
    generation run share this workspace — Qwen Code stores sessions per
    working directory, so both phases must use the same ``cwd`` for the
    native ``--session-id`` / ``--resume`` pair to line up.
    """
    template_name = make_template_name(description)
    root = Path(base_dir) if base_dir is not None else default_generated_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    workdir = root / f"{_slugify(description)}-{stamp}-{template_name[-6:]}"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir, template_name


def generate_template_files(
    description: str,
    *,
    workdir: Path | None = None,
    template_name: str | None = None,
    resume_session: str | None = None,
    binary: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    base_dir: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CodegenResult:
    """Generate ``Dockerfile`` + ``template.yaml`` with Qwen Code.

    The files are written into a workspace: *workdir* when the caller
    already prepared one (the create command does, so the clarification
    loop and this run share one native session), otherwise a fresh
    ``~/.ebx/generated/<slug>-<timestamp>/`` directory under *base_dir*.
    The workspace is kept on failure so users can inspect what the agent
    produced.

    *resume_session* continues the native Qwen Code session created by
    the clarification loop, so the model keeps the full description and
    Q/A transcript in its own memory instead of re-reading a replay.

    Raises:
        AICodegenError: When the run fails, times out, or the produced
            files are missing / invalid.  Never silently falls back.
    """
    if not description or not description.strip():
        raise AICodegenError("Cannot generate a template from an empty description.")

    def progress(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    if workdir is None:
        workdir, template_name = prepare_workdir(description, base_dir=base_dir)
    elif template_name is None:
        template_name = make_template_name(description)

    prompt = build_codegen_prompt(description, template_name)
    progress(f"Generating template with Qwen Code in {workdir} ...")
    result = run_qwen_code_headless(
        prompt,
        binary=binary,
        env=env,
        cwd=workdir,
        timeout=timeout if timeout is not None else default_codegen_timeout(),
        resume=resume_session,
    )

    dockerfile = workdir / "Dockerfile"
    template_yaml = workdir / "template.yaml"
    missing = [p.name for p in (dockerfile, template_yaml) if not p.is_file()]
    if missing:
        stderr_tail = (result.raw_stderr or "").strip().splitlines()[-3:]
        detail = f" exit_code={result.exit_code}"
        if result.text:
            detail += f" output={result.text.strip()[:200]!r}"
        if stderr_tail:
            detail += f" stderr={' | '.join(stderr_tail)}"
        raise AICodegenError(
            f"Qwen Code did not create the expected file(s): {', '.join(missing)}.{detail}",
            suggestion=(
                f"Inspect the generated workspace: {workdir} — then retry "
                f"'ebx create \"{description}\"', or fall back to "
                "'ebx create --template <name>'."
            ),
        )

    if not _has_from_instruction(dockerfile):
        raise AICodegenError(
            f"Generated Dockerfile at {dockerfile} has no FROM instruction.",
            suggestion=(
                f"Inspect the generated workspace: {workdir} — then retry, "
                "or fall back to 'ebx create --template <name>'."
            ),
        )

    data = _load_template_yaml(template_yaml)
    data["name"] = template_name
    try:
        parse_template_data(dict(data))
    except Exception as exc:
        raise AICodegenError(
            f"Generated template.yaml failed schema validation: {exc}",
            suggestion=(
                f"Inspect the generated workspace: {workdir} — then retry, "
                "or fall back to 'ebx create --template <name>'."
            ),
        ) from exc

    template_yaml.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.debug("Generated template workspace ready: %s", workdir)

    return CodegenResult(
        workdir=workdir,
        template_name=template_name,
        dockerfile=dockerfile,
        template_yaml=template_yaml,
        description=description,
        raw_output=result.text,
    )
