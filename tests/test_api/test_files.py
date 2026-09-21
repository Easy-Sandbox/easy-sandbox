"""Tests for the FilesModule API."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from easy_sandbox.api.files import FilesModule
from easy_sandbox.models.filesystem import FileInfo, FileType

from tests.test_api.conftest import TEST_ENVD_URL


class TestFilesRead:
    """Test FilesModule.read() and read_bytes()."""

    @pytest.mark.asyncio
    async def test_read_returns_text(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        result = await files_module.read("/app/main.py")
        assert result == "file content"
        mock_filesystem_protocol.read_text.assert_called_once()
        call_kwargs = mock_filesystem_protocol.read_text.call_args[1]
        assert call_kwargs["path"] == "/app/main.py"
        assert call_kwargs["encoding"] == "utf-8"

    @pytest.mark.asyncio
    async def test_read_custom_encoding(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.read("/app/data.txt", encoding="latin-1")
        call_kwargs = mock_filesystem_protocol.read_text.call_args[1]
        assert call_kwargs["encoding"] == "latin-1"

    @pytest.mark.asyncio
    async def test_read_bytes_returns_bytes(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        result = await files_module.read_bytes("/app/image.png")
        assert result == b"file bytes"
        mock_filesystem_protocol.read.assert_called_once()
        call_kwargs = mock_filesystem_protocol.read.call_args[1]
        assert call_kwargs["path"] == "/app/image.png"


class TestFilesWrite:
    """Test FilesModule.write()."""

    @pytest.mark.asyncio
    async def test_write_string(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.write("/app/test.py", "print('hello')")
        mock_filesystem_protocol.write.assert_called_once()
        call_kwargs = mock_filesystem_protocol.write.call_args[1]
        assert call_kwargs["path"] == "/app/test.py"
        assert call_kwargs["content"] == "print('hello')"

    @pytest.mark.asyncio
    async def test_write_bytes(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.write("/app/data.bin", b"\x00\x01\x02")
        call_kwargs = mock_filesystem_protocol.write.call_args[1]
        assert call_kwargs["content"] == b"\x00\x01\x02"


class TestFilesList:
    """Test FilesModule.list()."""

    @pytest.mark.asyncio
    async def test_list_returns_file_infos(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        result = await files_module.list("/app")
        assert len(result) == 2
        assert isinstance(result[0], FileInfo)
        assert result[0].name == "app.py"
        assert result[1].type == FileType.DIRECTORY

    @pytest.mark.asyncio
    async def test_list_default_path(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.list()
        call_kwargs = mock_filesystem_protocol.list_dir.call_args[1]
        assert call_kwargs["path"] == "/"


class TestFilesExists:
    """Test FilesModule.exists()."""

    @pytest.mark.asyncio
    async def test_exists_returns_true(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        result = await files_module.exists("/app/main.py")
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        mock_filesystem_protocol.exists.return_value = False
        result = await files_module.exists("/app/missing.py")
        assert result is False


class TestFilesRemove:
    """Test FilesModule.remove()."""

    @pytest.mark.asyncio
    async def test_remove_calls_protocol(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.remove("/app/old.py")
        mock_filesystem_protocol.remove.assert_called_once()
        call_kwargs = mock_filesystem_protocol.remove.call_args[1]
        assert call_kwargs["path"] == "/app/old.py"


class TestFilesMakeDir:
    """Test FilesModule.make_dir()."""

    @pytest.mark.asyncio
    async def test_make_dir_calls_protocol(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.make_dir("/app/new_dir")
        mock_filesystem_protocol.make_dir.assert_called_once()
        call_kwargs = mock_filesystem_protocol.make_dir.call_args[1]
        assert call_kwargs["path"] == "/app/new_dir"


class TestFilesUploadDownload:
    """Test upload and download methods."""

    @pytest.mark.asyncio
    async def test_upload_reads_local_writes_remote(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
        tmp_path,
    ) -> None:
        # Create a local test file
        local_file = tmp_path / "test.txt"
        local_file.write_bytes(b"local content")

        await files_module.upload(str(local_file), "/app/test.txt")
        mock_filesystem_protocol.write.assert_called_once()
        call_kwargs = mock_filesystem_protocol.write.call_args[1]
        assert call_kwargs["path"] == "/app/test.txt"
        assert call_kwargs["content"] == b"local content"

    @pytest.mark.asyncio
    async def test_download_reads_remote_writes_local(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
        tmp_path,
    ) -> None:
        local_file = tmp_path / "downloaded.bin"

        await files_module.download("/app/data.bin", str(local_file))
        mock_filesystem_protocol.read.assert_called_once()
        assert local_file.read_bytes() == b"file bytes"


class TestFilesUploadDownloadUrls:
    """Test upload_url and download_url methods."""

    @pytest.mark.asyncio
    async def test_upload_url(
        self,
        files_module: FilesModule,
    ) -> None:
        url = await files_module.upload_url("/app/test.txt")
        assert url == f"{TEST_ENVD_URL}/files?path=/app/test.txt&username=user"

    @pytest.mark.asyncio
    async def test_download_url(
        self,
        files_module: FilesModule,
    ) -> None:
        url = await files_module.download_url("/app/test.txt")
        assert url == f"{TEST_ENVD_URL}/files?path=/app/test.txt&username=user"


class TestFilesRename:
    """Test FilesModule.rename()."""

    @pytest.mark.asyncio
    async def test_rename_calls_protocol(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        await files_module.rename("/app/old.py", "/app/new.py")
        mock_filesystem_protocol.move.assert_called_once()
        call_kwargs = mock_filesystem_protocol.move.call_args[1]
        assert call_kwargs["source"] == "/app/old.py"
        assert call_kwargs["destination"] == "/app/new.py"


class TestFilesWatch:
    """Test FilesModule.watch()."""

    @pytest.mark.asyncio
    async def test_watch_calls_protocol(
        self,
        files_module: FilesModule,
        mock_filesystem_protocol: AsyncMock,
    ) -> None:
        mock_filesystem_protocol.watch_dir.return_value = "mock_reader"
        result = await files_module.watch("/app")
        assert result == "mock_reader"
        mock_filesystem_protocol.watch_dir.assert_called_once()


class TestFilesSyncVariants:
    """Test sync wrappers exist."""

    def test_read_sync_exists(self) -> None:
        assert hasattr(FilesModule, "read_sync")

    def test_write_sync_exists(self) -> None:
        assert hasattr(FilesModule, "write_sync")

    def test_list_sync_exists(self) -> None:
        assert hasattr(FilesModule, "list_sync")

    def test_exists_sync_exists(self) -> None:
        assert hasattr(FilesModule, "exists_sync")

    def test_remove_sync_exists(self) -> None:
        assert hasattr(FilesModule, "remove_sync")
