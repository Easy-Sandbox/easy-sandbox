"""GitHub / 本地目录 模板 Registry 客户端。"""
from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path

import httpx
import yaml

from easy_sandbox.models.errors import (
    NetworkError,
    SandboxError,
    TemplateNotFoundError,
)
from easy_sandbox.models.template import SandboxTemplate, TemplateRef
from easy_sandbox.utils.logging import get_logger

logger = get_logger("utils.registry")

TEMPLATE_CACHE_DIR = Path.home() / ".ebx" / "templates"

# 内置模板列表
BUILTIN_TEMPLATES = {"base", "code-interpreter-v1"}


class RegistryClient:
    """从 GitHub 拉取模板的客户端。"""

    def __init__(
        self,
        registry_url: str = "https://github.com",
        token: str | None = None,
    ) -> None:
        self._registry_url = registry_url.rstrip("/")
        self._api_url = self._registry_url.replace("github.com", "api.github.com")
        self._token = token

    async def resolve(
        self, ref: str, registry_type: str | None = None
    ) -> TemplateRef:
        """解析模板引用。

        支持格式（Terraform 双斜杠规范）：
        - "./my-template"                   → 本地目录
        - "/absolute/path/to/template"      → 本地目录
        - "base"                            → 内置模板
        - "owner/repo"                      → GitHub 整个仓库默认分支
        - "owner/repo@v1.0"                 → 整个仓库 + ref(tag/branch/sha)
        - "owner/repo//path/to/subdir"      → 子目录（默认分支）
        - "owner/repo//path/to/subdir@v1.0" → 子目录 + ref(tag/branch/sha)

        解析顺序：
        1. 检测本地路径（显式指定或自动识别）
        2. 内置模板检查
        3. 先 rsplit('@') 提取 tag
        4. 按 '//' 分割子目录路径
        5. 按 '/' 分割 owner/repo
        """
        # 1. 本地目录检测
        if (
            registry_type == "local"
            or ref.startswith("./")
            or ref.startswith("/")
            or os.path.exists(ref)
        ):
            abs_path = os.path.abspath(ref)
            if not os.path.isdir(abs_path):
                raise ValueError(
                    f"Local template directory not found: {abs_path}"
                )
            return TemplateRef(
                registry_type="local",
                local_path=abs_path,
                is_builtin=False,
            )

        # 2. 检查内置模板
        if ref in BUILTIN_TEMPLATES or "/" not in ref:
            return TemplateRef(is_builtin=True, tag=ref)

        # 1) 先提取 @tag（从最右侧拆分，避免与路径中的 @ 冲突）
        tag = None
        if "@" in ref:
            ref, tag = ref.rsplit("@", 1)

        # 2) 按 '//' 分割子目录路径
        path = None
        if "//" in ref:
            ref, path = ref.split("//", 1)
            # 规范化：去除前后 /
            path = path.strip("/") or None

        # 3. 解析 owner/repo（GitHub 格式）
        parts = ref.split("/", 1)
        if len(parts) != 2:
            return TemplateRef(is_builtin=True, tag=ref)

        owner, repo = parts
        return TemplateRef(
            owner=owner,
            repo=repo,
            tag=tag,
            path=path,
            is_builtin=False,
            registry_url=self._registry_url,
        )

    async def fetch(self, ref: TemplateRef) -> Path:
        """拉取模板到本地缓存。

        对于本地模板，直接返回本地路径（验证必要文件）。
        对于 GitHub 模板：
        1. 检查本地缓存
        2. 通过 GitHub tarball API 按 tag/branch/sha 拉取源码（无需 Release）
        3. 下载并解压到 ~/.ebx/templates/owner/repo/ref/[path/]
        4. 如果指定了 path，只提取子目录内容
        5. 返回本地路径
        """
        if ref.registry_type == "local":
            return self._fetch_local(ref)
        return await self._fetch_github(ref)

    def _fetch_local(self, ref: TemplateRef) -> Path:
        """从本地目录加载模板。"""
        local_path = Path(ref.local_path)

        # 验证必要文件存在（template.yaml 或 sandbox-template.yaml 或 sandbox.yaml 或 Dockerfile）
        yaml_path = local_path / "template.yaml"
        alt_yaml_path = local_path / "sandbox-template.yaml"
        alt2_yaml_path = local_path / "sandbox.yaml"
        dockerfile_path = local_path / "Dockerfile"

        if (
            not yaml_path.exists()
            and not alt_yaml_path.exists()
            and not alt2_yaml_path.exists()
            and not dockerfile_path.exists()
        ):
            raise ValueError(
                f"Local template at {local_path} must contain "
                f"template.yaml, sandbox-template.yaml, sandbox.yaml, or Dockerfile"
            )

        logger.info("Using local template: %s", local_path)
        return local_path

    async def _fetch_github(self, ref: TemplateRef) -> Path:
        """从 GitHub 拉取模板（按 tag/branch/sha 走 tarball API，无需 Release）。"""
        if ref.is_builtin:
            raise ValueError(
                f"Built-in template '{ref.tag}' does not need to be fetched."
            )

        if not ref.owner or not ref.repo:
            raise ValueError("TemplateRef must have owner and repo for fetching.")

        # 缓存 key：有 ref 用 ref(tag/branch/sha)，无 ref 用稳定占位符 "default"
        cache_key = ref.tag or "default"
        cached = self._check_cache(ref.owner, ref.repo, cache_key, ref.path)
        if cached is not None:
            logger.info(
                "Using cached template: %s/%s@%s", ref.owner, ref.repo, cache_key
            )
            return cached

        # 构造 tarball 下载地址（GitHub 会 302 到 codeload 的 .tar.gz）
        tarball_url = self._tarball_url(ref.owner, ref.repo, ref.tag)

        dest = self._cache_path(ref.owner, ref.repo, cache_key, ref.path)
        await self._download_and_extract(
            tarball_url,
            dest,
            subdir=ref.path,
            owner=ref.owner,
            repo=ref.repo,
            gh_ref=ref.tag,
        )

        logger.info(
            "Fetched template: %s/%s@%s → %s", ref.owner, ref.repo, cache_key, dest
        )
        return dest

    def _tarball_url(self, owner: str, repo: str, gh_ref: str | None) -> str:
        """构造 GitHub tarball API 地址。

        - 有 ref：``/repos/{owner}/{repo}/tarball/{ref}``（ref 可为 tag/branch/sha）；
        - 无 ref：``/repos/{owner}/{repo}/tarball`` → 返回默认分支的 tarball。
        """
        base = f"{self._api_url}/repos/{owner}/{repo}/tarball"
        if gh_ref:
            return f"{base}/{gh_ref}"
        return base

    @staticmethod
    def _translate_tarball_error(
        exc: httpx.HTTPStatusError,
        owner: str | None,
        repo: str | None,
        gh_ref: str | None,
    ) -> SandboxError:
        """将 GitHub tarball API 的 HTTP 错误转换为用户友好的 SDK 异常。

        tarball 端点会先命中 api.github.com，再 302 到 codeload；两阶段共用
        同一套映射（follow_redirects 后返回的最终响应）：
        - 403 且触发速率限制 → 提示配置 token 认证；
        - 403 其它 → 提示可能为私有仓库；
        - 404 → TemplateNotFoundError（提示校验 owner/repo//subdir[@ref] 与 ref 存在性）；
        - 5xx/其它 → NetworkError。
        """
        resp = exc.response
        status = resp.status_code
        if owner and repo:
            target = f"{owner}/{repo}" + (f"@{gh_ref}" if gh_ref else "")
        else:
            target = "the template archive"

        if status == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            try:
                body_text = resp.text or ""
            except Exception:  # pragma: no cover - defensive
                body_text = ""
            if remaining == "0" or "rate limit" in body_text.lower():
                return NetworkError(
                    "GitHub API rate limit exceeded (anonymous requests are "
                    "limited to 60/hour).",
                    suggestion=(
                        "Authenticate to raise the limit to 5000/hour: set the "
                        "GITHUB_TOKEN environment variable or pass --token. "
                        f"Example: ebx template install {target} --token <your-token>"
                    ),
                )
            return NetworkError(
                f"GitHub API returned 403 Forbidden for '{target}'.",
                suggestion=(
                    "The repository may be private. Pass --token <your-token> "
                    "to access private repositories."
                ),
            )

        if status == 404:
            return TemplateNotFoundError(
                f"GitHub template not found for '{target}'.",
                suggestion=(
                    "Check that owner/repo//subdir[@ref] is correct and that the "
                    "ref (tag/branch/sha) exists. Templates are fetched by "
                    "tag/branch/sha via the GitHub tarball API — no Release is "
                    "required."
                ),
            )

        return NetworkError(
            f"GitHub tarball request failed with HTTP {status} for '{target}'.",
            suggestion="Check the repository reference and your network connection.",
        )

    async def _download_and_extract(
        self,
        url: str,
        dest: Path,
        *,
        subdir: str | None = None,
        owner: str | None = None,
        repo: str | None = None,
        gh_ref: str | None = None,
    ) -> None:
        """下载并解压模板 tarball（.tar.gz）。

        GitHub tarball 顶层是单个目录（形如 ``{owner}-{repo}-{sha}/``），需要剥离；
        解压时校验成员路径不逃逸目标目录，防止路径穿越。

        Args:
            url: tarball 下载地址（GitHub 会 302 到 codeload 的 .tar.gz）
            dest: 本地目标目录
            subdir: 可选，仅提取 archive 中的指定子目录
            owner/repo/gh_ref: 可选，仅用于下载失败时构造友好错误上下文
        """
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise self._translate_tarball_error(
                    exc, owner, repo, gh_ref
                ) from exc

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = Path(tmp.name)

        try:
            dest.mkdir(parents=True, exist_ok=True)
            dest_root = dest.resolve()
            with tarfile.open(tmp_path, "r:gz") as tf:
                members = tf.getmembers()
                if members:
                    # GitHub tarball 包含一个顶层目录，需要剥离
                    prefix = members[0].name.split("/")[0] + "/"

                    # 如果指定了子目录，在前缀后追加子目录路径
                    extract_prefix = (
                        prefix + subdir.strip("/") + "/" if subdir else prefix
                    )

                    found_any = False
                    for member in members:
                        # 仅提取普通文件，跳过目录/符号链接等（安全）
                        if not member.isfile():
                            continue
                        name = member.name
                        if not name.startswith(extract_prefix):
                            continue
                        relative = name[len(extract_prefix):]
                        if not relative:
                            continue
                        target = (dest / relative).resolve()
                        # 路径穿越防护：目标必须严格位于 dest 目录内
                        if dest_root not in target.parents:
                            raise ValueError(
                                f"Unsafe path in archive rejected: {name}"
                            )
                        found_any = True
                        target.parent.mkdir(parents=True, exist_ok=True)
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        with src, open(target, "wb") as dst:
                            dst.write(src.read())

                    if subdir and not found_any:
                        raise ValueError(
                            f"Subdirectory '{subdir}' not found in the archive."
                        )
                else:
                    # 空包（无任何成员）：无论是否指定 subdir 都视为无效模板，
                    # 不静默返回空目录，避免下游误以为拉取成功。
                    raise TemplateNotFoundError(
                        "Downloaded template archive is empty (no members).",
                        suggestion=(
                            "Check that the repo/ref contains a valid template "
                            "directory (with template.yaml/Dockerfile). Templates "
                            "are fetched by tag/branch/sha via the GitHub tarball "
                            "API — no Release is required."
                        ),
                    )
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _cache_path(
        owner: str, repo: str, tag: str, path: str | None = None
    ) -> Path:
        """构建缓存路径：~/.ebx/templates/owner/repo/tag[/path]。"""
        base = TEMPLATE_CACHE_DIR / owner / repo / tag
        if path:
            return base / path
        return base

    def _check_cache(
        self, owner: str, repo: str, tag: str, path: str | None = None
    ) -> Path | None:
        """检查本地缓存。"""
        cache_path = self._cache_path(owner, repo, tag, path)
        if cache_path.exists() and (
            (cache_path / "template.yaml").exists()
            or (cache_path / "sandbox-template.yaml").exists()
            or (cache_path / "sandbox.yaml").exists()
        ):
            return cache_path
        return None

    def clear_cache(self) -> int:
        """清理本地模板缓存。返回清理的文件数。"""
        import shutil

        count = 0
        if TEMPLATE_CACHE_DIR.exists():
            for item in TEMPLATE_CACHE_DIR.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    count += 1
                else:
                    item.unlink()
                    count += 1
        return count


def load_template_from_yaml(path: Path) -> SandboxTemplate:
    """从 YAML 文件加载模板定义。"""
    with open(path) as f:
        data = yaml.safe_load(f)
    # 映射 resources 嵌套结构到扁平字段
    resources = data.pop("resources", {}) or {}
    if "cpu" in resources and "cpu_count" not in data:
        data["cpu_count"] = resources["cpu"]
    if "memory" in resources and "memory_mb" not in data:
        data["memory_mb"] = resources["memory"]
    return SandboxTemplate.model_validate(data)
