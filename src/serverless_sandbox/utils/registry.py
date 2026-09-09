"""GitHub / 本地目录 模板 Registry 客户端。"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
import yaml

from serverless_sandbox.models.template import SandboxTemplate, TemplateRef
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("utils.registry")

TEMPLATE_CACHE_DIR = Path.home() / ".sbox" / "templates"

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
        - "owner/repo"                      → GitHub 整个仓库 latest
        - "owner/repo@v1.0"                 → 整个仓库 + 版本
        - "owner/repo//path/to/subdir"      → 子目录 latest
        - "owner/repo//path/to/subdir@v1.0" → 子目录 + 版本

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
        2. 调用 GitHub API 获取 release
        3. 下载并解压到 ~/.sbox/templates/owner/repo/tag/[path/]
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
        """从 GitHub 拉取模板。"""
        if ref.is_builtin:
            raise ValueError(
                f"Built-in template '{ref.tag}' does not need to be fetched."
            )

        if not ref.owner or not ref.repo:
            raise ValueError("TemplateRef must have owner and repo for fetching.")

        # 检查缓存
        tag = ref.tag or "latest"
        cached = self._check_cache(ref.owner, ref.repo, tag, ref.path)
        if cached is not None:
            logger.info("Using cached template: %s/%s@%s", ref.owner, ref.repo, tag)
            return cached

        # 获取 release 信息
        release = await self._get_release(ref.owner, ref.repo, ref.tag)
        actual_tag = release.get("tag_name", tag)

        # 再次检查缓存（用实际 tag）
        if actual_tag != tag:
            cached = self._check_cache(ref.owner, ref.repo, actual_tag, ref.path)
            if cached is not None:
                return cached

        # 下载源码包
        zipball_url = release.get("zipball_url", "")
        if not zipball_url:
            raise ValueError(f"No zipball_url found in release for {ref.owner}/{ref.repo}")

        dest = self._cache_path(ref.owner, ref.repo, actual_tag, ref.path)
        await self._download_and_extract(zipball_url, dest, subdir=ref.path)

        logger.info("Fetched template: %s/%s@%s → %s", ref.owner, ref.repo, actual_tag, dest)
        return dest

    async def _get_release(
        self, owner: str, repo: str, tag: str | None = None
    ) -> dict[str, Any]:
        """获取 GitHub Release 信息。"""
        if tag:
            url = f"{self._api_url}/repos/{owner}/{repo}/releases/tags/{tag}"
        else:
            url = f"{self._api_url}/repos/{owner}/{repo}/releases/latest"

        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _download_and_extract(
        self, url: str, dest: Path, *, subdir: str | None = None
    ) -> None:
        """下载并解压模板包。

        Args:
            url: zipball 下载地址
            dest: 本地目标目录
            subdir: 可选，仅提取 archive 中的指定子目录
        """
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = Path(tmp.name)

        try:
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp_path) as zf:
                # GitHub zipball 包含一个顶层目录，需要剥离
                members = zf.namelist()
                if members:
                    # 找到公共前缀（顶层目录）
                    prefix = members[0].split("/")[0] + "/"

                    # 如果指定了子目录，在前缀后追加子目录路径
                    if subdir:
                        extract_prefix = prefix + subdir.rstrip("/") + "/"
                    else:
                        extract_prefix = prefix

                    found_any = False
                    for member in members:
                        if member.startswith(extract_prefix) and not member.endswith("/"):
                            relative = member[len(extract_prefix):]
                            if relative:
                                found_any = True
                                target = dest / relative
                                target.parent.mkdir(parents=True, exist_ok=True)
                                with zf.open(member) as src, open(target, "wb") as dst:
                                    dst.write(src.read())

                    if subdir and not found_any:
                        raise ValueError(
                            f"Subdirectory '{subdir}' not found in the archive."
                        )
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _cache_path(
        owner: str, repo: str, tag: str, path: str | None = None
    ) -> Path:
        """构建缓存路径：~/.sbox/templates/owner/repo/tag[/path]。"""
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
