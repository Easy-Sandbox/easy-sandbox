"""AI code generation for ``ebx create "<description>"``.

Orchestrates a Qwen Code headless run that produces a *usable* template
inside a dedicated workspace: a ``Dockerfile``, a ``commands.py`` that
starts the container-side ``easy_sandbox.server`` HTTP server (without it a
deployed sandbox has nothing to answer requests), and a ``template.yaml``.
The prompt carries the server SDK reference from
:mod:`easy_sandbox.agent.template_guide`.  All artifacts are validated (the
manifest with the very same schema used by
:func:`easy_sandbox.api.capability.parse_template_data`) and the workspace is
handed over to the existing build/deploy pipeline.
"""

from __future__ import annotations

import ast
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from easy_sandbox.agent.qwen_code import run_qwen_code_headless
from easy_sandbox.agent.template_guide import (
    REQUIRED_TEMPLATE_FILES,
    SERVER_ENTRYPOINT,
    SERVER_PORT,
    TEMPLATE_GUIDE,
)
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
_SERVE_CALL_RE = re.compile(r"\.serve\s*\(|\bstart\s*\(")

_CODEGEN_PROMPT_TEMPLATE = """\
你是 Easy Sandbox 的模板生成器。请根据下面的自然语言需求，在当前工作目录中生成一个
**部署后可以通过 HTTP(S) 直接使用**的沙箱模板（不是只有 Dockerfile 的镜像）。

用户需求：{description}

必须创建的文件：
1. `Dockerfile`：
   - 必须以 FROM 指令开始（选择官方基础镜像，例如 python:3.12-slim、node:20-slim、ubuntu:24.04）
   - 安装满足上述需求所需的系统包与依赖，并安装 easy-sandbox SDK（写法见下方规范）
   - `COPY commands.py`，`EXPOSE {server_port}`，`CMD ["python3", "commands.py"]`
   - 保持精简、可直接执行 docker build
2. `commands.py`：基于 `easy_sandbox.server` 的 HTTP 服务入口，监听 {server_port} 端口，
   注册与需求相关的命令 / 路由（至少一个有意义的命令，不要只留 hello）
3. `template.yaml`：
   name: {template_name}
   version: "1.0.0"
   description: <一句话中文描述，不超过 50 字>
   capabilities: <与 commands.py 开启的能力组一致>
   ports: <至少包含 {server_port}>
   resources:
     cpu: <1-8 的整数>
     memory: <512-16384 的整数，单位 MB>
4. `README.md`：模板用途、环境变量、调用示例

{guide}
限制：
- 只创建上述文件，以及需求确实需要的业务代码 / 依赖清单；不要创建其他无关文件或目录
- 不要运行 docker，不要安装任何东西，不要读取或输出密钥文件
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

    commands_py: Path | None = None
    """The generated ``commands.py`` server entry point."""

    files: tuple[str, ...] = ()
    """Workspace-relative paths of every deliverable file (see
    :func:`list_template_files`)."""


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
        server_port=SERVER_PORT,
        guide=TEMPLATE_GUIDE,
    )


def _has_from_instruction(dockerfile: Path) -> bool:
    try:
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_FROM_INSTRUCTION_RE.search(text))


def _default_retry_hint(workdir: Path) -> str:
    return (
        f"Inspect the generated workspace: {workdir} — then retry, "
        "or fall back to 'ebx create --template <name>'."
    )


def _load_template_yaml(template_yaml: Path, *, retry: str | None = None) -> dict[str, Any]:
    hint = retry if retry is not None else _default_retry_hint(template_yaml.parent)
    try:
        data = yaml.safe_load(template_yaml.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AICodegenError(
            f"Generated template.yaml could not be parsed: {exc}",
            suggestion=hint,
        ) from exc
    if not isinstance(data, dict):
        raise AICodegenError(
            "Generated template.yaml is not a YAML mapping.",
            suggestion=hint,
        )
    return data


#: Names never treated as template deliverables (agent scratch / build junk).
_SKIP_DIR_NAMES = frozenset({"__pycache__", "node_modules"})
_SKIP_SUFFIXES = (".pyc", ".whl", ".ebx-bak")
_LIST_MAX_FILES = 200


def list_template_files(workdir: Path) -> tuple[str, ...]:
    """Workspace-relative paths of the generated template's deliverables.

    Dot-files and dot-directories (agent state such as ``.qwen``) are left
    out, except ``.dockerignore``; so are ``__pycache__``, ``*.pyc`` and
    injected ``*.whl`` files.  The result is sorted and bounded.
    """
    found: list[str] = []
    for current, dirs, names in os.walk(workdir):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIR_NAMES)
        for name in sorted(names):
            if name.endswith(_SKIP_SUFFIXES):
                continue
            if name.startswith(".") and name != ".dockerignore":
                continue
            found.append(str((Path(current) / name).relative_to(workdir)))
            if len(found) >= _LIST_MAX_FILES:
                return tuple(sorted(found))
    return tuple(sorted(found))


def _validate_server_entrypoint(
    workdir: Path,
    dockerfile: Path,
    commands_py: Path,
    *,
    retry: str | None = None,
) -> None:
    """Check that the template actually ships a runnable SandboxServer.

    Without ``commands.py`` (or without a Dockerfile that starts it) the
    deployed sandbox has nothing to answer HTTP requests, so this fails
    closed instead of silently accepting a Dockerfile-only template.
    """
    if retry is None:
        retry = (
            f"Inspect the generated workspace: {workdir} — then retry, "
            "or fall back to 'ebx create --template <name>'."
        )
    try:
        source = commands_py.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AICodegenError(
            f"Generated {SERVER_ENTRYPOINT} could not be read: {exc}", suggestion=retry
        ) from exc
    try:
        ast.parse(source, filename=SERVER_ENTRYPOINT)
    except SyntaxError as exc:
        raise AICodegenError(
            f"Generated {SERVER_ENTRYPOINT} is not valid Python: {exc}", suggestion=retry
        ) from exc
    if "easy_sandbox.server" not in source or not _SERVE_CALL_RE.search(source):
        raise AICodegenError(
            f"Generated {SERVER_ENTRYPOINT} does not start an easy_sandbox.server "
            "SandboxServer (expected an import from easy_sandbox.server and a "
            f"serve()/start() call on port {SERVER_PORT}).",
            suggestion=retry,
        )
    try:
        docker_text = dockerfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        docker_text = ""
    if SERVER_ENTRYPOINT not in docker_text:
        raise AICodegenError(
            f"Generated Dockerfile never references {SERVER_ENTRYPOINT}, so the "
            "sandbox server would not start.",
            suggestion=retry,
        )


def validate_template_workspace(
    workdir: Path,
    template_name: str,
    *,
    retry: str | None = None,
) -> dict[str, Any]:
    """Validate a generated template workspace and return its manifest data.

    Shared by ``ebx create "<description>"`` and ``ebx template init
    --adopt``.  Checks, fail-closed: the Dockerfile has a ``FROM``;
    ``commands.py`` parses and starts ``easy_sandbox.server``; the Dockerfile
    references it; ``template.yaml`` is a mapping that passes the capability
    schema.  Nothing is written; the returned manifest carries *template_name*
    as its ``name``.

    *retry* replaces the default "inspect the workspace / fall back to
    ``ebx create --template``" suggestion on every error.

    Raises:
        AICodegenError: When any check fails.
    """
    dockerfile = workdir / "Dockerfile"
    template_yaml = workdir / "template.yaml"
    commands_py = workdir / SERVER_ENTRYPOINT
    hint = retry if retry is not None else _default_retry_hint(workdir)
    for path in (dockerfile, template_yaml, commands_py):
        if not path.is_file():
            raise AICodegenError(f"Expected file is missing: {path.name}.", suggestion=hint)

    if not _has_from_instruction(dockerfile):
        raise AICodegenError(
            f"Generated Dockerfile at {dockerfile} has no FROM instruction.",
            suggestion=hint,
        )

    _validate_server_entrypoint(workdir, dockerfile, commands_py, retry=hint)

    data = _load_template_yaml(template_yaml, retry=hint)
    data["name"] = template_name
    try:
        parse_template_data(dict(data))
    except Exception as exc:
        raise AICodegenError(
            f"Generated template.yaml failed schema validation: {exc}",
            suggestion=hint,
        ) from exc
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
    on_activity: Callable[[str], None] | None = None,
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
    extra: dict[str, Any] = {} if on_activity is None else {"on_activity": on_activity}
    result = run_qwen_code_headless(
        prompt,
        binary=binary,
        env=env,
        cwd=workdir,
        timeout=timeout if timeout is not None else default_codegen_timeout(),
        resume=resume_session,
        **extra,
    )

    dockerfile = workdir / "Dockerfile"
    template_yaml = workdir / "template.yaml"
    commands_py = workdir / SERVER_ENTRYPOINT
    missing = [name for name in REQUIRED_TEMPLATE_FILES if not (workdir / name).is_file()]
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

    data = validate_template_workspace(workdir, template_name)

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
        commands_py=commands_py,
        files=list_template_files(workdir),
    )
