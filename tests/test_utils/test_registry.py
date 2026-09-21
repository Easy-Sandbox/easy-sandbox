"""Tests for RegistryClient."""
from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_sandbox.models.template import TemplateRef
from easy_sandbox.utils.registry import (
    BUILTIN_TEMPLATES,
    RegistryClient,
)


def _make_tarball(files: dict[str, str], prefix: str = "owner-repo-abc123") -> bytes:
    """构造一个内存中的 .tar.gz，模拟 GitHub tarball（顶层单目录）。

    keys 为相对于顶层目录的路径，会自动加上 ``{prefix}/`` 前缀。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel_path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"{prefix}/{rel_path}")
            info.size = len(data)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_tarball_response(tarball: bytes) -> MagicMock:
    """模拟 tarball 下载响应（带 .content 与 raise_for_status）。"""
    resp = MagicMock()
    resp.content = tarball
    resp.raise_for_status = MagicMock()
    return resp


def _patched_async_client(resp: object) -> MagicMock:
    """构造一个作为 async context manager 的 httpx.AsyncClient mock。"""
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


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

    # --- GitHub fetch 测试（tarball API） ---

    @pytest.mark.asyncio
    async def test_fetch_subdir_extracts_correctly(self, tmp_path: Path) -> None:
        """带 path 的 fetch 应只提取子目录内容（tar.gz）。"""
        client = RegistryClient()

        # 构造一个内存中的 tar.gz，模拟 GitHub tarball
        tarball = _make_tarball(
            {
                "README.md": "root readme",
                "templates/python-data/template.yaml": "name: python-data\n",
                "templates/python-data/main.py": "print('hello')\n",
                "templates/node-web/package.json": '{"name": "node-web"}\n',
            }
        )
        mock_resp = _fake_tarball_response(tarball)

        ref = TemplateRef(
            owner="owner",
            repo="repo",
            tag="v1.0",
            path="templates/python-data",
        )

        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch(
            "httpx.AsyncClient", return_value=_patched_async_client(mock_resp)
        ):
            result = await client.fetch(ref)

        # 应只包含子目录内容
        assert (result / "template.yaml").exists()
        assert (result / "main.py").exists()
        # 不包含根目录的 README 和其他子目录
        assert not (result / "README.md").exists()
        assert not (result / "package.json").exists()
        # 缓存落盘位置：<owner>/<repo>/<ref>/<subdir>
        assert result == tmp_path / "owner" / "repo" / "v1.0" / "templates/python-data"

    @pytest.mark.asyncio
    async def test_fetch_subdir_not_found_raises(self, tmp_path: Path) -> None:
        """子目录不存在时应抛出异常。"""
        client = RegistryClient()

        tarball = _make_tarball({"README.md": "root readme"})
        mock_resp = _fake_tarball_response(tarball)

        ref = TemplateRef(
            owner="owner",
            repo="repo",
            tag="v1.0",
            path="nonexistent/dir",
        )

        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch(
            "httpx.AsyncClient", return_value=_patched_async_client(mock_resp)
        ), pytest.raises(ValueError, match="Subdirectory.*not found"):
            await client.fetch(ref)

    @pytest.mark.asyncio
    async def test_fetch_whole_repo_still_works(self, tmp_path: Path) -> None:
        """path=None 时提取整个仓库（剥离顶层目录）。"""
        client = RegistryClient()

        tarball = _make_tarball(
            {
                "template.yaml": "name: test\n",
                "src/main.py": "pass\n",
            }
        )
        mock_resp = _fake_tarball_response(tarball)

        ref = TemplateRef(owner="owner", repo="repo", tag="v2.0")

        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch(
            "httpx.AsyncClient", return_value=_patched_async_client(mock_resp)
        ):
            result = await client.fetch(ref)

        assert (result / "template.yaml").exists()
        assert (result / "src" / "main.py").exists()

    @pytest.mark.asyncio
    async def test_fetch_no_ref_uses_default_cache_key(self, tmp_path: Path) -> None:
        """无 ref 时默认分支 tarball 成功，缓存 key 为 'default'。"""
        client = RegistryClient()

        tarball = _make_tarball({"template.yaml": "name: test\n"})
        mock_resp = _fake_tarball_response(tarball)

        ref = TemplateRef(owner="owner", repo="repo", tag=None)

        patched = _patched_async_client(mock_resp)
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch("httpx.AsyncClient", return_value=patched):
            result = await client.fetch(ref)

        assert result == tmp_path / "owner" / "repo" / "default"
        assert (result / "template.yaml").exists()
        # 无 ref 时应命中不带 ref 的 tarball 端点
        called_url = patched.get.await_args.args[0]
        assert called_url.endswith("/repos/owner/repo/tarball")

    @pytest.mark.asyncio
    async def test_fetch_with_ref_hits_ref_tarball_and_cache(
        self, tmp_path: Path
    ) -> None:
        """带 ref 时命中 /tarball/{ref}；二次安装命中缓存不再下载。"""
        client = RegistryClient()

        tarball = _make_tarball({"template.yaml": "name: test\n"})
        mock_resp = _fake_tarball_response(tarball)
        ref = TemplateRef(owner="owner", repo="repo", tag="v1.1.0")

        patched = _patched_async_client(mock_resp)
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch("httpx.AsyncClient", return_value=patched):
            first = await client.fetch(ref)
            second = await client.fetch(ref)

        assert first == second == tmp_path / "owner" / "repo" / "v1.1.0"
        called_url = patched.get.await_args.args[0]
        assert called_url.endswith("/repos/owner/repo/tarball/v1.1.0")
        # 第二次命中缓存 → 只下载了一次
        assert patched.get.await_count == 1

    @pytest.mark.asyncio
    async def test_fetch_with_branch_ref_cache_key_is_branch(
        self, tmp_path: Path
    ) -> None:
        """branch 作为 ref：命中 /tarball/<branch>，cache_key 为该 branch。"""
        client = RegistryClient()

        tarball = _make_tarball({"template.yaml": "name: test\n"})
        mock_resp = _fake_tarball_response(tarball)
        ref = TemplateRef(owner="owner", repo="repo", tag="main")

        patched = _patched_async_client(mock_resp)
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch("httpx.AsyncClient", return_value=patched):
            result = await client.fetch(ref)

        assert result == tmp_path / "owner" / "repo" / "main"
        called_url = patched.get.await_args.args[0]
        assert called_url.endswith("/repos/owner/repo/tarball/main")

    @pytest.mark.asyncio
    async def test_fetch_with_sha_ref_cache_key_is_sha(
        self, tmp_path: Path
    ) -> None:
        """sha 作为 ref：命中 /tarball/<sha>，cache_key 为该 sha。"""
        client = RegistryClient()

        tarball = _make_tarball({"template.yaml": "name: test\n"})
        mock_resp = _fake_tarball_response(tarball)
        sha = "abc1234def5678"
        ref = TemplateRef(owner="owner", repo="repo", tag=sha)

        patched = _patched_async_client(mock_resp)
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch("httpx.AsyncClient", return_value=patched):
            result = await client.fetch(ref)

        assert result == tmp_path / "owner" / "repo" / sha
        called_url = patched.get.await_args.args[0]
        assert called_url.endswith(f"/repos/owner/repo/tarball/{sha}")

    @pytest.mark.asyncio
    async def test_fetch_private_repo_injects_token(self, tmp_path: Path) -> None:
        """私有仓库：--token 应以 Bearer 形式注入 Authorization 头。"""
        client = RegistryClient(token="test-placeholder-token")

        tarball = _make_tarball({"template.yaml": "name: test\n"})
        mock_resp = _fake_tarball_response(tarball)
        ref = TemplateRef(owner="owner", repo="repo", tag="v1.0")

        patched = _patched_async_client(mock_resp)
        with patch(
            "easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path
        ), patch("httpx.AsyncClient", return_value=patched):
            await client.fetch(ref)

        headers = patched.get.await_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-placeholder-token"


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

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            result = client._check_cache("owner", "repo", "v1.0")
            assert result == cache_dir

    def test_check_cache_hit_with_path(self, tmp_path: Path) -> None:
        """带 path 的缓存查找。"""
        client = RegistryClient()
        cache_dir = tmp_path / "owner" / "repo" / "v1.0" / "templates" / "py"
        cache_dir.mkdir(parents=True)
        (cache_dir / "template.yaml").write_text("name: test\n")

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            result = client._check_cache("owner", "repo", "v1.0", "templates/py")
            assert result == cache_dir

    def test_check_cache_miss_with_path(self, tmp_path: Path) -> None:
        """子目录缓存未命中。"""
        client = RegistryClient()
        # 仅创建根目录缓存，子目录未缓存
        cache_dir = tmp_path / "owner" / "repo" / "v1.0"
        cache_dir.mkdir(parents=True)
        (cache_dir / "template.yaml").write_text("name: test\n")

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            result = client._check_cache("owner", "repo", "v1.0", "templates/py")
            assert result is None

    def test_clear_cache(self, tmp_path: Path) -> None:
        # Create some cache entries
        (tmp_path / "owner1").mkdir()
        (tmp_path / "owner2").mkdir()

        with patch("easy_sandbox.utils.registry.TEMPLATE_CACHE_DIR", tmp_path):
            client = RegistryClient()
            count = client.clear_cache()
            assert count == 2


class TestTarballFetchErrors:
    """Friendly error handling for the GitHub tarball fetch (_download_and_extract)."""

    @staticmethod
    def _patched_client(resp: object) -> AsyncMock:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        return mock_http

    @pytest.mark.asyncio
    async def test_tarball_rate_limited(self, tmp_path: Path) -> None:
        """403 + X-RateLimit-Remaining:0 → friendly NetworkError (token hint)."""
        import httpx

        from easy_sandbox.models.errors import NetworkError

        client = RegistryClient()
        resp = httpx.Response(
            status_code=403,
            headers={"X-RateLimit-Remaining": "0"},
            json={"message": "API rate limit exceeded for 1.2.3.4"},
            request=httpx.Request("GET", "https://api.github.com/x"),
        )
        with patch("httpx.AsyncClient", return_value=self._patched_client(resp)), \
                pytest.raises(NetworkError) as ei:
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball",
                tmp_path,
                owner="owner",
                repo="repo",
                gh_ref=None,
            )
        assert "rate limit" in str(ei.value).lower()
        assert "--token" in ei.value.suggestion
        assert "GITHUB_TOKEN" in ei.value.suggestion

    @pytest.mark.asyncio
    async def test_tarball_403_private_repo(self, tmp_path: Path) -> None:
        """403 without rate-limit signal → private-repo hint."""
        import httpx

        from easy_sandbox.models.errors import NetworkError

        client = RegistryClient()
        resp = httpx.Response(
            status_code=403,
            json={"message": "Forbidden"},
            request=httpx.Request("GET", "https://api.github.com/x"),
        )
        with patch("httpx.AsyncClient", return_value=self._patched_client(resp)), \
                pytest.raises(NetworkError) as ei:
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball",
                tmp_path,
                owner="owner",
                repo="repo",
                gh_ref=None,
            )
        assert "403" in str(ei.value)
        assert "--token" in ei.value.suggestion

    @pytest.mark.asyncio
    async def test_tarball_not_found_is_template_not_found(
        self, tmp_path: Path
    ) -> None:
        """404 → TemplateNotFoundError 提示校验 ref，不再提 Release。"""
        import httpx

        from easy_sandbox.models.errors import TemplateNotFoundError

        client = RegistryClient()
        resp = httpx.Response(
            status_code=404,
            json={"message": "Not Found"},
            request=httpx.Request("GET", "https://api.github.com/x"),
        )
        with patch("httpx.AsyncClient", return_value=self._patched_client(resp)), \
                pytest.raises(TemplateNotFoundError) as ei:
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball/v9.9",
                tmp_path,
                owner="owner",
                repo="repo",
                gh_ref="v9.9",
            )
        assert "owner/repo@v9.9" in str(ei.value)
        # 文案应提示 ref 存在性，不再要求创建 Release
        assert "tag/branch/sha" in ei.value.suggestion
        assert "no Release is" in ei.value.suggestion

    @pytest.mark.asyncio
    async def test_tarball_server_error(self, tmp_path: Path) -> None:
        """5xx → NetworkError with status code and target."""
        import httpx

        from easy_sandbox.models.errors import NetworkError

        client = RegistryClient()
        resp = httpx.Response(
            status_code=500,
            json={"message": "boom"},
            request=httpx.Request("GET", "https://api.github.com/x"),
        )
        with patch("httpx.AsyncClient", return_value=self._patched_client(resp)), \
                pytest.raises(NetworkError) as ei:
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball/v2.0",
                tmp_path,
                owner="owner",
                repo="repo",
                gh_ref="v2.0",
            )
        assert "500" in str(ei.value)
        assert "owner/repo@v2.0" in str(ei.value)

    @pytest.mark.asyncio
    async def test_empty_tarball_is_template_not_found(
        self, tmp_path: Path
    ) -> None:
        """空包（tarball 无任何成员）→ TemplateNotFoundError，不静默返回空目录。"""
        from easy_sandbox.models.errors import TemplateNotFoundError

        client = RegistryClient()
        tarball = _make_tarball({})  # 没有任何成员
        mock_resp = _fake_tarball_response(tarball)
        dest = tmp_path / "owner" / "repo" / "default"

        with patch(
            "httpx.AsyncClient", return_value=_patched_async_client(mock_resp)
        ), pytest.raises(TemplateNotFoundError) as ei:
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball",
                dest,
                owner="owner",
                repo="repo",
                gh_ref=None,
            )
        assert "empty" in str(ei.value).lower()
        assert "template.yaml/Dockerfile" in ei.value.suggestion
        # 不应静默落盘任何文件
        assert not any(dest.glob("*")) if dest.exists() else True

    @pytest.mark.asyncio
    async def test_empty_tarball_with_subdir_is_template_not_found(
        self, tmp_path: Path
    ) -> None:
        """空包：即使指定 subdir 也应抛 TemplateNotFoundError（而非 subdir not found）。"""
        from easy_sandbox.models.errors import TemplateNotFoundError

        client = RegistryClient()
        tarball = _make_tarball({})
        mock_resp = _fake_tarball_response(tarball)
        dest = tmp_path / "owner" / "repo" / "default" / "sub"

        with patch(
            "httpx.AsyncClient", return_value=_patched_async_client(mock_resp)
        ), pytest.raises(TemplateNotFoundError) as ei:
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball",
                dest,
                subdir="templates/foo",
                owner="owner",
                repo="repo",
                gh_ref=None,
            )
        assert "empty" in str(ei.value).lower()


class TestTarballUrl:
    """_tarball_url 对 tag/branch/sha 统一走 /tarball/<ref> 端点。"""

    def test_tarball_url_no_ref_is_default_branch(self) -> None:
        client = RegistryClient()
        url = client._tarball_url("owner", "repo", None)
        assert url.endswith("/repos/owner/repo/tarball")

    def test_tarball_url_branch_ref(self) -> None:
        client = RegistryClient()
        url = client._tarball_url("owner", "repo", "main")
        assert url.endswith("/repos/owner/repo/tarball/main")

    def test_tarball_url_sha_ref(self) -> None:
        client = RegistryClient()
        sha = "abc1234def5678"
        url = client._tarball_url("owner", "repo", sha)
        assert url.endswith(f"/repos/owner/repo/tarball/{sha}")


class TestTarballPathTraversal:
    """解压时必须拒绝逃逸目标目录的成员路径。"""

    @pytest.mark.asyncio
    async def test_path_traversal_member_rejected(self, tmp_path: Path) -> None:
        """tarball 内含 ../ 逃逸路径时应报错，且不写出目标目录外。"""
        client = RegistryClient()

        # 顶层目录内嵌入一个 "../evil.txt" 成员（仍以顶层前缀开头）
        tarball = _make_tarball(
            {
                "template.yaml": "name: test\n",
                "../evil.txt": "pwned",
            }
        )
        mock_resp = _fake_tarball_response(tarball)
        dest = tmp_path / "cache" / "dest"

        with patch(
            "httpx.AsyncClient",
            return_value=_patched_async_client(mock_resp),
        ), pytest.raises(ValueError, match="Unsafe path"):
            await client._download_and_extract(
                "https://api.github.com/repos/owner/repo/tarball",
                dest,
                owner="owner",
                repo="repo",
                gh_ref=None,
            )

        # evil.txt 不应写到 dest 的父目录
        assert not (tmp_path / "cache" / "evil.txt").exists()


class TestBuiltinTemplates:
    """Verify built-in template set."""

    def test_base_in_builtins(self) -> None:
        assert "base" in BUILTIN_TEMPLATES

    def test_code_interpreter_in_builtins(self) -> None:
        assert "code-interpreter-v1" in BUILTIN_TEMPLATES
