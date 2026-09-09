"""Tests for RegistryClient."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serverless_sandbox.models.template import TemplateRef
from serverless_sandbox.utils.registry import (
    BUILTIN_TEMPLATES,
    RegistryClient,
    TEMPLATE_CACHE_DIR,
)


class TestRegistryClientResolve:
    """Tests for RegistryClient.resolve()."""

    @pytest.mark.asyncio
    async def test_resolve_builtin(self) -> None:
        client = RegistryClient()
        ref = await client.resolve("base")
        assert ref.is_builtin is True
        assert ref.tag == "base"

    @pytest.mark.asyncio
    async def test_resolve_builtin_code_interpreter(self) -> None:
        client = RegistryClient()
        ref = await client.resolve("code-interpreter-v1")
        assert ref.is_builtin is True
        assert ref.tag == "code-interpreter-v1"

    @pytest.mark.asyncio
    async def test_resolve_unknown_single_name(self) -> None:
        """Single name without slash → treated as builtin."""
        client = RegistryClient()
        ref = await client.resolve("my-custom")
        assert ref.is_builtin is True
        assert ref.tag == "my-custom"

    @pytest.mark.asyncio
    async def test_resolve_github_latest(self) -> None:
        client = RegistryClient()
        ref = await client.resolve("owner/repo")
        assert ref.is_builtin is False
        assert ref.owner == "owner"
        assert ref.repo == "repo"
        assert ref.tag is None

    @pytest.mark.asyncio
    async def test_resolve_github_tagged(self) -> None:
        client = RegistryClient()
        ref = await client.resolve("owner/repo@v1.0")
        assert ref.is_builtin is False
        assert ref.owner == "owner"
        assert ref.repo == "repo"
        assert ref.tag == "v1.0"

    @pytest.mark.asyncio
    async def test_resolve_custom_registry(self) -> None:
        client = RegistryClient(registry_url="https://git.example.com")
        ref = await client.resolve("org/templates")
        assert ref.registry_url == "https://git.example.com"

    @pytest.mark.asyncio
    async def test_resolve_subdir_latest(self) -> None:
        """owner/repo//subdir → 子目录 latest"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo//path/to/subdir")
        assert ref.is_builtin is False
        assert ref.owner == "owner"
        assert ref.repo == "repo"
        assert ref.path == "path/to/subdir"
        assert ref.tag is None

    @pytest.mark.asyncio
    async def test_resolve_subdir_tagged(self) -> None:
        """owner/repo//subdir@v1.0 → 子目录 + 版本"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo//templates/python@v2.0")
        assert ref.is_builtin is False
        assert ref.owner == "owner"
        assert ref.repo == "repo"
        assert ref.path == "templates/python"
        assert ref.tag == "v2.0"

    @pytest.mark.asyncio
    async def test_resolve_subdir_single_level(self) -> None:
        """owner/repo//subdir → 单层子目录"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo//vpc")
        assert ref.is_builtin is False
        assert ref.owner == "owner"
        assert ref.repo == "repo"
        assert ref.path == "vpc"
        assert ref.tag is None

    @pytest.mark.asyncio
    async def test_resolve_subdir_trailing_slash_stripped(self) -> None:
        """子目录路径尾部斜杠应被清理。"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo//subdir/")
        assert ref.path == "subdir"

    @pytest.mark.asyncio
    async def test_resolve_no_path_without_double_slash(self) -> None:
        """普通 owner/repo 不应解析出 path。"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo")
        assert ref.path is None

    @pytest.mark.asyncio
    async def test_resolve_no_path_with_tag_only(self) -> None:
        """owner/repo@v1.0 不应解析出 path。"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo@v1.0")
        assert ref.path is None

    @pytest.mark.asyncio
    async def test_resolve_subdir(self) -> None:
        """解析 owner/repo//subdir 格式。"""
        client = RegistryClient()
        ref = await client.resolve("demo/demo//templates/python-data")
        assert ref.is_builtin is False
        assert ref.owner == "demo"
        assert ref.repo == "demo"
        assert ref.path == "templates/python-data"
        assert ref.tag is None

    @pytest.mark.asyncio
    async def test_resolve_subdir_with_tag(self) -> None:
        """解析 owner/repo//subdir@v1.0 格式。"""
        client = RegistryClient()
        ref = await client.resolve("demo/demo//templates/node-web@v1.0")
        assert ref.is_builtin is False
        assert ref.owner == "demo"
        assert ref.repo == "demo"
        assert ref.path == "templates/node-web"
        assert ref.tag == "v1.0"

    @pytest.mark.asyncio
    async def test_resolve_subdir_trailing_slash(self) -> None:
        """子目录尾部 / 应被移除。"""
        client = RegistryClient()
        ref = await client.resolve("demo/demo//templates/python-data/")
        assert ref.path == "templates/python-data"

    @pytest.mark.asyncio
    async def test_resolve_no_subdir_has_none_path(self) -> None:
        """不包含子目录时 path 为 None。"""
        client = RegistryClient()
        ref = await client.resolve("owner/repo@v2.0")
        assert ref.path is None
        assert ref.tag == "v2.0"

    # --- 本地路径解析测试 ---

    @pytest.mark.asyncio
    async def test_resolve_local_relative_path(self, tmp_path: Path) -> None:
        """相对路径 ./ 开头应解析为本地模板。"""
        # 创建临时目录并 chdir 到它的父目录
        local_dir = tmp_path / "my-template"
        local_dir.mkdir()
        (local_dir / "template.yaml").write_text("name: test\n")

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            client = RegistryClient()
            ref = await client.resolve("./my-template")
            assert ref.registry_type == "local"
            assert ref.local_path == str(local_dir)
            assert ref.is_builtin is False
        finally:
            os.chdir(old_cwd)

    @pytest.mark.asyncio
    async def test_resolve_local_absolute_path(self, tmp_path: Path) -> None:
        """绝对路径应解析为本地模板。"""
        local_dir = tmp_path / "abs-template"
        local_dir.mkdir()
        (local_dir / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        client = RegistryClient()
        ref = await client.resolve(str(local_dir))
        assert ref.registry_type == "local"
        assert ref.local_path == str(local_dir)
        assert ref.is_builtin is False

    @pytest.mark.asyncio
    async def test_resolve_local_explicit_registry_type(self, tmp_path: Path) -> None:
        """显式指定 registry_type='local' 应强制本地解析。"""
        local_dir = tmp_path / "explicit-local"
        local_dir.mkdir()

        client = RegistryClient()
        ref = await client.resolve(str(local_dir), registry_type="local")
        assert ref.registry_type == "local"
        assert ref.local_path == str(local_dir)

    @pytest.mark.asyncio
    async def test_resolve_local_nonexistent_raises(self) -> None:
        """本地路径不存在时应报错。"""
        client = RegistryClient()
        with pytest.raises(ValueError, match="Local template directory not found"):
            await client.resolve("/nonexistent/path/to/template")

    @pytest.mark.asyncio
    async def test_resolve_local_relative_nonexistent_raises(self) -> None:
        """不存在的相对路径应报错。"""
        client = RegistryClient()
        with pytest.raises(ValueError, match="Local template directory not found"):
            await client.resolve("./nonexistent-template-dir-xyz")

    @pytest.mark.asyncio
    async def test_resolve_github_still_works_after_local_support(self) -> None:
        """回归测试：添加本地支持后 GitHub 格式仍正常工作。"""
        client = RegistryClient()
        ref = await client.resolve("myorg/myrepo//templates/node@v3.0")
        assert ref.is_builtin is False
        assert ref.owner == "myorg"
        assert ref.repo == "myrepo"
        assert ref.path == "templates/node"
        assert ref.tag == "v3.0"
        assert ref.registry_type == "github"


class TestRegistryClientFetch:
    """Tests for RegistryClient.fetch()."""

    @pytest.mark.asyncio
    async def test_fetch_builtin_raises(self) -> None:
        client = RegistryClient()
        ref = TemplateRef(is_builtin=True, tag="base")
        with pytest.raises(ValueError, match="Built-in template"):
            await client.fetch(ref)

    @pytest.mark.asyncio
    async def test_fetch_no_owner_raises(self) -> None:
        client = RegistryClient()
        ref = TemplateRef(is_builtin=False, owner=None, repo="test")
        with pytest.raises(ValueError, match="must have owner and repo"):
            await client.fetch(ref)

    # --- 本地 fetch 测试 ---

    @pytest.mark.asyncio
    async def test_fetch_local_with_yaml(self, tmp_path: Path) -> None:
        """本地目录包含 template.yaml 应成功返回。"""
        client = RegistryClient()
        (tmp_path / "template.yaml").write_text("name: test\n")

        ref = TemplateRef(
            registry_type="local",
            local_path=str(tmp_path),
            is_builtin=False,
        )
        result = await client.fetch(ref)
        assert result == tmp_path

    @pytest.mark.asyncio
    async def test_fetch_local_with_dockerfile(self, tmp_path: Path) -> None:
        """本地目录仅包含 Dockerfile 也应成功。"""
        client = RegistryClient()
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        ref = TemplateRef(
            registry_type="local",
            local_path=str(tmp_path),
            is_builtin=False,
        )
        result = await client.fetch(ref)
        assert result == tmp_path

    @pytest.mark.asyncio
    async def test_fetch_local_with_both_files(self, tmp_path: Path) -> None:
        """本地目录包含两个文件都应成功。"""
        client = RegistryClient()
        (tmp_path / "template.yaml").write_text("name: test\n")
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:22.04\n")

        ref = TemplateRef(
            registry_type="local",
            local_path=str(tmp_path),
            is_builtin=False,
        )
        result = await client.fetch(ref)
        assert result == tmp_path

    @pytest.mark.asyncio
    async def test_fetch_local_missing_required_files_raises(self, tmp_path: Path) -> None:
        """本地目录缺少必要文件应报错。"""
        client = RegistryClient()
        # 空目录，没有 yaml 也没有 Dockerfile
        ref = TemplateRef(
            registry_type="local",
            local_path=str(tmp_path),
            is_builtin=False,
        )
        with pytest.raises(ValueError, match="must contain"):
            await client.fetch(ref)

    # --- GitHub fetch 测试（原有） ---

    @pytest.mark.asyncio
    async def test_fetch_subdir_extracts_correctly(self, tmp_path: Path) -> None:
        """带 path 的 fetch 应只提取子目录内容。"""
        client = RegistryClient()

        # 构建一个内存中的 zip，模拟 GitHub zipball
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("owner-repo-abc123/README.md", "root readme")
            zf.writestr(
                "owner-repo-abc123/templates/python-data/template.yaml",
                "name: python-data\n",
            )
            zf.writestr(
                "owner-repo-abc123/templates/python-data/main.py",
                "print('hello')\n",
            )
            zf.writestr(
                "owner-repo-abc123/templates/node-web/package.json",
                '{"name": "node-web"}\n',
            )
        zip_bytes = buf.getvalue()

        # mock _get_release 和 httpx
        mock_release = {
            "tag_name": "v1.0",
            "zipball_url": "https://fake/zipball",
        }

        mock_resp = MagicMock()
        mock_resp.content = zip_bytes
        mock_resp.raise_for_status = MagicMock()

        ref = TemplateRef(
            owner="owner",
            repo="repo",
            tag="v1.0",
            path="templates/python-data",
        )

        with patch.object(
            client, "_get_release", new_callable=AsyncMock, return_value=mock_release
        ), patch(
            "serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch(
            "httpx.AsyncClient"
        ) as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http_cls.return_value = mock_http

            result = await client.fetch(ref)

        # 应只包含子目录内容
        assert (result / "template.yaml").exists()
        assert (result / "main.py").exists()
        # 不包含根目录的 README 和其他子目录
        assert not (result / "README.md").exists()
        assert not (result / "package.json").exists()

    @pytest.mark.asyncio
    async def test_fetch_subdir_not_found_raises(self, tmp_path: Path) -> None:
        """子目录不存在时应抛出异常。"""
        client = RegistryClient()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("owner-repo-abc123/README.md", "root readme")
        zip_bytes = buf.getvalue()

        mock_release = {
            "tag_name": "v1.0",
            "zipball_url": "https://fake/zipball",
        }

        mock_resp = MagicMock()
        mock_resp.content = zip_bytes
        mock_resp.raise_for_status = MagicMock()

        ref = TemplateRef(
            owner="owner",
            repo="repo",
            tag="v1.0",
            path="nonexistent/dir",
        )

        with patch.object(
            client, "_get_release", new_callable=AsyncMock, return_value=mock_release
        ), patch(
            "serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch(
            "httpx.AsyncClient"
        ) as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http_cls.return_value = mock_http

            with pytest.raises(ValueError, match="Subdirectory.*not found"):
                await client.fetch(ref)

    @pytest.mark.asyncio
    async def test_fetch_whole_repo_still_works(self, tmp_path: Path) -> None:
        """path=None 时行为不变（向后兼容）。"""
        client = RegistryClient()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("owner-repo-abc123/template.yaml", "name: test\n")
            zf.writestr("owner-repo-abc123/src/main.py", "pass\n")
        zip_bytes = buf.getvalue()

        mock_release = {
            "tag_name": "v2.0",
            "zipball_url": "https://fake/zipball",
        }

        mock_resp = MagicMock()
        mock_resp.content = zip_bytes
        mock_resp.raise_for_status = MagicMock()

        ref = TemplateRef(owner="owner", repo="repo", tag="v2.0")

        with patch.object(
            client, "_get_release", new_callable=AsyncMock, return_value=mock_release
        ), patch(
            "serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch(
            "httpx.AsyncClient"
        ) as mock_http_cls:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http_cls.return_value = mock_http

            result = await client.fetch(ref)

        assert (result / "template.yaml").exists()
        assert (result / "src" / "main.py").exists()


class TestRegistryClientCache:
    """Tests for cache-related methods."""

    def test_check_cache_miss(self) -> None:
        client = RegistryClient()
        result = client._check_cache("nonexistent-owner", "nonexistent-repo", "v999")
        assert result is None

    def test_check_cache_hit(self, tmp_path: Path) -> None:
        client = RegistryClient()
        # Patch TEMPLATE_CACHE_DIR to use tmp_path
        cache_dir = tmp_path / "owner" / "repo" / "v1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "template.yaml").write_text("name: test\n")

        with patch("serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            result = client._check_cache("owner", "repo", "v1.0")
            assert result == cache_dir

    def test_check_cache_hit_with_path(self, tmp_path: Path) -> None:
        """带 path 的缓存查找。"""
        client = RegistryClient()
        cache_dir = tmp_path / "owner" / "repo" / "v1.0" / "templates" / "py"
        cache_dir.mkdir(parents=True)
        (cache_dir / "template.yaml").write_text("name: test\n")

        with patch("serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            result = client._check_cache("owner", "repo", "v1.0", "templates/py")
            assert result == cache_dir

    def test_check_cache_miss_with_path(self, tmp_path: Path) -> None:
        """子目录缓存未命中。"""
        client = RegistryClient()
        # 仅创建根目录缓存，子目录未缓存
        cache_dir = tmp_path / "owner" / "repo" / "v1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "template.yaml").write_text("name: test\n")

        with patch("serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            result = client._check_cache("owner", "repo", "v1.0", "templates/py")
            assert result is None

    def test_clear_cache(self, tmp_path: Path) -> None:
        # Create some cache entries
        (tmp_path / "owner1").mkdir()
        (tmp_path / "owner2").mkdir()

        with patch("serverless_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            client = RegistryClient()
            count = client.clear_cache()
            assert count == 2


class TestBuiltinTemplates:
    """Verify built-in template set."""

    def test_base_in_builtins(self) -> None:
        assert "base" in BUILTIN_TEMPLATES

    def test_code_interpreter_in_builtins(self) -> None:
        assert "code-interpreter-v1" in BUILTIN_TEMPLATES
