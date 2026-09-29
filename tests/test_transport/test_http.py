"""Tests for transport.http module."""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from easy_sandbox.models.errors import ConnectionError_, EnvdRpcError, ExecutionError
from easy_sandbox.transport.auth import PLATFORM_AUTH_HEADER, ApiKeyAuth, EnvdTokenManager
from easy_sandbox.transport.codec import CONNECT_CONTENT_TYPE
from easy_sandbox.transport.config import TransportConfig
from easy_sandbox.transport.http import HttpClient


def make_envd_frame(payload: dict, flags: int = 0x00) -> bytes:
    """Build a Connect binary envelope frame: flags(1) + length(4 BE) + JSON."""
    body = json.dumps(payload).encode()
    return struct.pack(">BI", flags, len(body)) + body


def patched_async_client_init(
    transport: httpx.MockTransport,
    *,
    captured_timeouts: list[Any] | None = None,
    created_clients: list[httpx.AsyncClient] | None = None,
):
    """Return an ``AsyncClient.__init__`` patch that injects *transport*.

    Injecting a mock transport keeps the real ``client.stream()`` code path
    under test (no network), while optionally recording the timeout passed
    by ``envd_stream`` and the client instances it creates.
    """
    original_init = httpx.AsyncClient.__init__

    def patched_init(self_client: httpx.AsyncClient, **kwargs: Any) -> None:
        if captured_timeouts is not None:
            captured_timeouts.append(kwargs.get("timeout"))
        kwargs["transport"] = transport
        original_init(self_client, **kwargs)
        if created_clients is not None:
            created_clients.append(self_client)

    return patched_init


def mock_stream_transport(chunks_factory, status: int = 200):
    """Build an ``httpx.MockTransport`` whose responses stream *chunks_factory*().

    *chunks_factory* is a zero-arg callable returning an async iterator of
    bytes; each item is delivered as one network chunk.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=chunks_factory())

    return httpx.MockTransport(handler)


def make_stream_test_client() -> HttpClient:
    """HttpClient instance for streaming tests (mock auth, HTTP/1.1)."""
    config = TransportConfig(api_url="https://test.example.com", http2=False)
    return HttpClient(config=config, auth=MagicMock())


def patch_stream_client_init(transport: httpx.MockTransport, **kwargs: Any):
    """Context manager patching ``AsyncClient.__init__`` to inject *transport*."""
    return patch.object(
        httpx.AsyncClient,
        "__init__",
        patched_async_client_init(transport, **kwargs),
    )


@pytest.fixture
def transport_config():
    return TransportConfig(
        api_url="https://sandbox-test.example.com",
        http2=False,  # Disable HTTP/2 for test mocking
    )


@pytest.fixture
def api_key_auth():
    return ApiKeyAuth("test-api-key")


@pytest.fixture
def envd_token():
    return EnvdTokenManager("test-envd-token")


@pytest.fixture
def http_client(transport_config, api_key_auth):
    return HttpClient(config=transport_config, auth=api_key_auth)


class TestPlatformRequest:
    """Test Platform API requests."""

    async def test_sends_auth_headers(self, http_client, httpx_mock):
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/v1/sandboxes",
            json={"sandboxes": []},
        )
        response = await http_client.platform_request("GET", "/v1/sandboxes")
        assert response.status_code == 200

        request = httpx_mock.get_request()
        assert request.headers[PLATFORM_AUTH_HEADER.lower()] == "Bearer test-api-key"

    async def test_sends_json_body(self, http_client, httpx_mock):
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/v1/sandboxes",
            json={"id": "sbx-123"},
        )
        await http_client.platform_request(
            "POST",
            "/v1/sandboxes",
            json={"template": "python3"},
        )
        request = httpx_mock.get_request()
        body = json.loads(request.content)
        assert body == {"template": "python3"}

    async def test_sends_query_params(self, http_client, httpx_mock):
        httpx_mock.add_response(json={"sandboxes": []})
        await http_client.platform_request("GET", "/v1/sandboxes", params={"limit": "10"})
        request = httpx_mock.get_request()
        assert "limit=10" in str(request.url)

    async def test_custom_headers_merged(self, http_client, httpx_mock):
        httpx_mock.add_response(json={})
        await http_client.platform_request("GET", "/v1/sandboxes", headers={"X-Custom": "value"})
        request = httpx_mock.get_request()
        assert request.headers["x-custom"] == "value"

    async def test_http_status_error_propagated(self, http_client, httpx_mock):
        httpx_mock.add_response(status_code=404, json={"error": "not found"})
        with pytest.raises(httpx.HTTPStatusError):
            await http_client.platform_request("GET", "/v1/sandboxes/missing")


class TestEnvdRequest:
    """Test envd API requests."""

    async def test_sends_connect_content_type(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/Start",
            json={"pid": 123},
        )
        result = await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/Start",
            payload={"command": "ls"},
            envd_token=envd_token,
        )
        request = httpx_mock.get_request()
        assert request.headers["content-type"] == CONNECT_CONTENT_TYPE
        assert result == {"pid": 123}

    async def test_sends_envd_auth_header(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/Start",
            json={"pid": 123},
        )
        await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/Start",
            envd_token=envd_token,
        )
        request = httpx_mock.get_request()
        assert request.headers["x-access-token"] == "test-envd-token"

    async def test_decode_response(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/filesystem.Filesystem/ReadFile",
            json={"content": "hello world"},
        )
        result = await http_client.envd_request(
            "https://envd.example.com",
            "/filesystem.Filesystem/ReadFile",
            payload={"path": "/tmp/test.txt"},
            envd_token=envd_token,
        )
        assert result == {"content": "hello world"}

    async def test_empty_payload(self, http_client, envd_token, httpx_mock):
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/List",
            json={"processes": []},
        )
        result = await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/List",
            envd_token=envd_token,
        )
        assert result == {"processes": []}

    async def test_request_timeout_override(self, http_client, envd_token, httpx_mock):
        """request_timeout overrides the client-level default for a single call."""
        httpx_mock.add_response(
            url="https://envd.example.com/process.Process/List",
            json={"ok": True},
        )
        await http_client.envd_request(
            "https://envd.example.com",
            "/process.Process/List",
            envd_token=envd_token,
            request_timeout=120.0,
        )
        request = httpx_mock.get_request()
        # The request was sent successfully; the timeout was applied
        # at the httpx level (not directly visible in the request object,
        # but we verify it via monkeypatch below).
        assert request is not None

    async def test_request_timeout_none_uses_default(self, http_client, envd_token, httpx_mock):
        """When request_timeout is None, the default http_timeout is used."""
        httpx_mock.add_response(
            url="https://envd.example.com/test",
            json={"ok": True},
        )
        await http_client.envd_request(
            "https://envd.example.com",
            "/test",
            envd_token=envd_token,
            request_timeout=None,
        )
        # Should not raise — default timeout from config is used.
        assert httpx_mock.get_request() is not None


class TestClose:
    """Test client cleanup."""

    async def test_close_platform_client(self, http_client, httpx_mock):
        httpx_mock.add_response(json={})
        await http_client.platform_request("GET", "/v1/health")
        await http_client.close()
        assert http_client._platform_client is None

    async def test_close_envd_clients(self, http_client, httpx_mock):
        envd_token = EnvdTokenManager("tok")
        httpx_mock.add_response(
            url="https://envd1.example.com/test",
            json={"ok": True},
        )
        await http_client.envd_request(
            "https://envd1.example.com",
            "/test",
            envd_token=envd_token,
        )
        await http_client.close()
        assert len(http_client._envd_clients) == 0

    async def test_close_idempotent(self, http_client):
        await http_client.close()
        await http_client.close()  # Should not raise

    async def test_context_manager(self, transport_config, api_key_auth, httpx_mock):
        httpx_mock.add_response(json={})
        async with HttpClient(config=transport_config, auth=api_key_auth) as client:
            await client.platform_request("GET", "/v1/health")
        assert client._platform_client is None


class TestRequestTimeoutPropagation:
    """Verify that request_timeout is forwarded to httpx correctly."""

    async def test_envd_request_passes_timeout_to_httpx_post(
        self, transport_config, api_key_auth, envd_token, httpx_mock
    ):
        """envd_request(request_timeout=120) should pass timeout=Timeout(120) to client.post()."""
        httpx_mock.add_response(
            url="https://envd.example.com/test",
            json={"ok": True},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        envd_client = client._create_envd_client("https://envd.example.com")

        captured_kwargs: dict = {}
        original_post = envd_client.post

        async def patched_post(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_post(*args, **kwargs)

        envd_client.post = patched_post  # type: ignore[method-assign]

        await client.envd_request(
            "https://envd.example.com",
            "/test",
            envd_token=envd_token,
            request_timeout=120.0,
        )

        assert "timeout" in captured_kwargs
        assert captured_kwargs["timeout"].read == 120.0
        await client.close()

    async def test_envd_request_no_timeout_kwarg_when_none(
        self, transport_config, api_key_auth, envd_token, httpx_mock
    ):
        """envd_request(request_timeout=None) should NOT pass timeout kwarg."""
        httpx_mock.add_response(
            url="https://envd.example.com/test",
            json={"ok": True},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        envd_client = client._create_envd_client("https://envd.example.com")

        captured_kwargs: dict = {}
        original_post = envd_client.post

        async def patched_post(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_post(*args, **kwargs)

        envd_client.post = patched_post  # type: ignore[method-assign]

        await client.envd_request(
            "https://envd.example.com",
            "/test",
            envd_token=envd_token,
        )

        # No per-request timeout override — client-level default applies
        assert "timeout" not in captured_kwargs
        await client.close()

    async def test_platform_request_passes_timeout_to_httpx_request(
        self, transport_config, api_key_auth, httpx_mock
    ):
        """platform_request(request_timeout=120) forwards timeout=Timeout(120) to request()."""
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/sandboxes",
            json={"sandboxID": "sbx-1"},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        platform_client = await client._get_platform_client()

        captured_kwargs: dict = {}
        original_request = platform_client.request

        async def patched_request(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_request(*args, **kwargs)

        platform_client.request = patched_request  # type: ignore[method-assign]

        await client.platform_request(
            "POST", "/sandboxes", json={"templateID": "base"}, request_timeout=120.0
        )

        assert "timeout" in captured_kwargs
        assert isinstance(captured_kwargs["timeout"], httpx.Timeout)
        assert captured_kwargs["timeout"].read == 120.0
        await client.close()

    async def test_platform_request_no_timeout_kwarg_when_none(
        self, transport_config, api_key_auth, httpx_mock
    ):
        """platform_request(request_timeout=None) must NOT pass a timeout kwarg."""
        httpx_mock.add_response(
            url="https://sandbox-test.example.com/sandboxes",
            json={"sandboxes": []},
        )
        client = HttpClient(config=transport_config, auth=api_key_auth)
        platform_client = await client._get_platform_client()

        captured_kwargs: dict = {}
        original_request = platform_client.request

        async def patched_request(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_request(*args, **kwargs)

        platform_client.request = patched_request  # type: ignore[method-assign]

        await client.platform_request("GET", "/sandboxes")

        # Client-level default applies — no per-request override sent.
        assert "timeout" not in captured_kwargs
        await client.close()

    async def test_envd_stream_uses_override_timeout(self, envd_token):
        """envd_stream(request_timeout=180) should create httpx client with Timeout(180)."""
        captured_timeouts: list[Any] = []
        transport = mock_stream_transport(lambda: _empty_chunks())

        config = TransportConfig(
            api_url="https://test.example.com",
            http2=False,
            http_timeout=30.0,
        )
        auth = MagicMock()
        client = HttpClient(config=config, auth=auth)

        with patch_stream_client_init(transport, captured_timeouts=captured_timeouts):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
                request_timeout=180.0,
            ):
                pass

        assert any(isinstance(t, httpx.Timeout) and t.read == 180.0 for t in captured_timeouts)
        await client.close()

    async def test_envd_stream_default_timeout(self, envd_token):
        """envd_stream without request_timeout uses config.http_timeout."""
        captured_timeouts: list[Any] = []
        transport = mock_stream_transport(lambda: _empty_chunks())

        config = TransportConfig(
            api_url="https://test.example.com",
            http2=False,
            http_timeout=42.0,  # custom default
        )
        auth = MagicMock()
        client = HttpClient(config=config, auth=auth)

        with patch_stream_client_init(transport, captured_timeouts=captured_timeouts):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass

        # Should use config default, not an override
        assert any(isinstance(t, httpx.Timeout) and t.read == 42.0 for t in captured_timeouts)
        await client.close()


async def _empty_chunks():
    """Async iterator producing no chunks (empty streaming response)."""
    return
    yield  # pragma: no cover - makes this an async generator


class TestEnvdStreamStreaming:
    """True-streaming behaviour of ``envd_stream`` (task 166).

    These tests use a mock transport whose response body is produced by a
    controlled async byte-chunk iterator, so chunk arrival *timing* is
    observable and it can be proven that frames are yielded incrementally
    instead of after the full body has been buffered.
    """

    def _make_client(self) -> HttpClient:
        return make_stream_test_client()

    def _patch(self, transport, **kwargs):
        return patch_stream_client_init(transport, **kwargs)

    async def test_frames_yielded_incrementally_before_later_chunks_arrive(self, envd_token):
        """The first frame must be yielded *before* the second chunk exists.

        The second network chunk is gated on an event that is only set after
        the consumer received the first frame.  A buffered implementation
        (read the whole body first) would deadlock on the gate and trip the
        ``wait_for`` timeout instead of completing.
        """
        frame1 = make_envd_frame({"event": {"data": {"stdout": "bGluZTE="}}})
        frame2 = make_envd_frame({"event": {"data": {"stdout": "bGluZTI="}}})
        second_chunk_released = asyncio.Event()

        async def chunks():
            yield frame1
            await second_chunk_released.wait()
            yield frame2

        transport = mock_stream_transport(chunks)
        client = self._make_client()

        async def consume() -> list[dict]:
            received: list[dict] = []
            async for frame in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                received.append(frame)
                if len(received) == 1:
                    # Only reached if frame 1 was delivered while chunk 2 is
                    # still gated — i.e. truly incremental streaming.
                    second_chunk_released.set()
            return received

        with self._patch(transport):
            received = await asyncio.wait_for(consume(), timeout=5.0)

        assert received == [
            {"event": {"data": {"stdout": "bGluZTE="}}},
            {"event": {"data": {"stdout": "bGluZTI="}}},
        ]
        await client.close()

    async def test_header_split_across_chunks(self, envd_token):
        """A 5-byte frame header split 1+2+2 across network chunks."""
        raw = make_envd_frame({"event": {"data": {"stdout": "aGk="}}})

        async def chunks():
            yield raw[0:1]
            yield raw[1:3]
            yield raw[3:]

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [{"event": {"data": {"stdout": "aGk="}}}]
        await client.close()

    async def test_payload_split_across_chunks(self, envd_token):
        """A frame payload split across three network chunks."""
        raw = make_envd_frame({"event": {"data": {"stdout": "bGluZQ=="}}})
        header, payload = raw[:5], raw[5:]

        async def chunks():
            yield header
            yield payload[:2]
            yield payload[2:5]
            yield payload[5:]

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [{"event": {"data": {"stdout": "bGluZQ=="}}}]
        await client.close()

    async def test_multiple_frames_in_single_chunk(self, envd_token):
        """Several complete frames packed into one network chunk."""
        blob = (
            make_envd_frame({"event": {"start": {"pid": 7}}})
            + make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
            + make_envd_frame({"event": {"data": {"stderr": "Mg=="}}})
            + make_envd_frame({"event": {"end": {"exitCode": 0}}})
        )

        async def chunks():
            yield blob

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [
            {"event": {"start": {"pid": 7}}},
            {"event": {"data": {"stdout": "MQ=="}}},
            {"event": {"data": {"stderr": "Mg=="}}},
            {"event": {"end": {"exitCode": 0}}},
        ]
        await client.close()

    async def test_mixed_complete_and_partial_frames_across_chunks(self, envd_token):
        """Chunk 1 = whole frame + start of next; chunk 2 = rest + another frame."""
        f1 = make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
        f2 = make_envd_frame({"event": {"data": {"stdout": "Mg=="}}})
        f3 = make_envd_frame({"event": {"end": {"exitCode": 0}}})

        async def chunks():
            yield f1 + f2[:6]  # whole frame 1 + partial frame 2 (mid-header/payload)
            yield f2[6:] + f3  # rest of frame 2 + whole frame 3

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [
            {"event": {"data": {"stdout": "MQ=="}}},
            {"event": {"data": {"stdout": "Mg=="}}},
            {"event": {"end": {"exitCode": 0}}},
        ]
        await client.close()

    async def test_trailer_and_error_frames_skipped(self, envd_token):
        """End-of-stream (0x02) frames — empty or with error JSON — are skipped."""

        async def chunks():
            yield make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
            # Trailer carrying a Connect error payload must not be yielded
            # (matches parse_streaming_frames semantics).
            yield make_envd_frame({"error": {"code": "internal", "message": "boom"}}, flags=0x02)
            # Empty data frame is skipped too.
            yield make_envd_frame({}, flags=0x02)

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [{"event": {"data": {"stdout": "MQ=="}}}]
        await client.close()

    async def test_truncated_trailing_frame_dropped(self, envd_token):
        """A final incomplete frame (header + partial payload) is dropped."""
        complete = make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
        truncated = make_envd_frame({"event": {"data": {"stdout": "bG9uZw=="}}})[:-3]

        async def chunks():
            yield complete
            yield truncated

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        # The complete frame survives; the truncated tail is dropped silently.
        assert frames == [{"event": {"data": {"stdout": "MQ=="}}}]
        await client.close()

    async def test_invalid_json_payload_skipped(self, envd_token):
        """A data frame whose payload is not valid JSON is skipped."""
        bad_body = b"{not json"
        bad = struct.pack(">BI", 0x00, len(bad_body)) + bad_body
        good = make_envd_frame({"event": {"end": {"exitCode": 3}}})

        async def chunks():
            yield bad
            yield good

        transport = mock_stream_transport(chunks)
        client = self._make_client()
        with self._patch(transport):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [{"event": {"end": {"exitCode": 3}}}]
        await client.close()

    async def test_http_error_raises_envd_rpc_error_and_closes_client(self, envd_token):
        """A 4xx streaming response raises EnvdRpcError and closes resources."""

        async def chunks():
            yield b'{"error": "not found"}'

        transport = mock_stream_transport(chunks, status=404)
        created: list[httpx.AsyncClient] = []
        client = self._make_client()
        with (
            self._patch(transport, created_clients=created),
            pytest.raises(EnvdRpcError) as ei,
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        exc = ei.value
        assert exc.status_code == 404
        assert exc.rpc_path == "/process.Process/Start"
        assert exc.envd_error == {"error": "not found"}
        # No full-URL / MDN leak in the exception text (task 166)
        assert "envd.example.com" not in str(exc)
        assert "https://" not in str(exc)
        assert "mozilla.org" not in str(exc)
        # The streaming client was closed even though the error aborted iteration.
        assert created and created[0].is_closed
        await client.close()

    async def test_http_500_envd_json_error_structured(self, envd_token):
        """Command-not-found 500: envd JSON body is propagated structurally.

        Mirrors the real reproduction (``ebx connect`` + typo'd command):
        envd answers /process.Process/Start with 500 and a JSON error body
        (e.g. "exec not found").  The transport must surface that body as
        structured data for upper layers to map, instead of double-printing
        a WARNING followed by a raw httpx error with the full sandbox URL.
        """

        async def chunks():
            yield b'{"error": {"code": "not_found", "message": "exec not found"}}'

        transport = mock_stream_transport(chunks, status=500)
        client = self._make_client()
        with (
            self._patch(transport),
            pytest.raises(EnvdRpcError) as ei,
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        exc = ei.value
        assert isinstance(exc, ExecutionError)
        assert exc.code == "E3006"
        assert exc.status_code == 500
        assert exc.rpc_path == "/process.Process/Start"
        assert exc.envd_error == {"error": {"code": "not_found", "message": "exec not found"}}
        # The human-readable detail from the JSON body reaches the message
        assert "exec not found" in exc.message
        # No URL / MDN leak anywhere in the exception text
        for leaked in ("envd.example.com", "https://", "mozilla.org"):
            assert leaked not in str(exc)
            assert leaked not in exc.message
        await client.close()

    async def test_http_500_flat_json_error_variants(self, envd_token):
        """Flat / string / message-only JSON error shapes all yield a detail."""
        cases = [
            (b'{"code": "not_found", "message": "exec not found"}', "exec not found"),
            (b'{"error": "exec not found"}', "exec not found"),
            (b'{"message": "exec not found"}', "exec not found"),
        ]
        for body, expected_detail in cases:

            async def chunks(body: bytes = body):
                yield body

            transport = mock_stream_transport(chunks, status=500)
            client = self._make_client()
            with (
                self._patch(transport),
                pytest.raises(EnvdRpcError) as ei,
            ):
                async for _ in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                ):
                    pass
            assert expected_detail in ei.value.message, body
            assert ei.value.envd_error is not None
            await client.close()

    async def test_http_500_non_json_error_body(self, envd_token):
        """Non-JSON error body still raises EnvdRpcError carrying the raw text."""

        async def chunks():
            yield b"exec: not found (plain text)"

        transport = mock_stream_transport(chunks, status=500)
        client = self._make_client()
        with (
            self._patch(transport),
            pytest.raises(EnvdRpcError) as ei,
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        exc = ei.value
        assert exc.status_code == 500
        assert exc.envd_error is None  # unparseable body — no structured data
        assert "plain text" in exc.body_text
        assert "exec: not found" in exc.message  # raw text used as the detail
        assert "envd.example.com" not in str(exc)
        await client.close()

    async def test_http_500_empty_error_body(self, envd_token):
        """A 500 with an empty body still raises a clean EnvdRpcError.

        Boundary case for the bounded-body reader: ``raw`` stays empty, so
        no JSON parse is attempted, no detail is appended, and the message
        is just the RPC path + status.
        """

        async def chunks():
            yield b""

        transport = mock_stream_transport(chunks, status=500)
        client = self._make_client()
        with (
            self._patch(transport),
            pytest.raises(EnvdRpcError) as ei,
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        exc = ei.value
        assert exc.status_code == 500
        assert exc.envd_error is None
        assert exc.body_text == ""
        # No dangling detail separator when the body is empty
        assert exc.message == "envd RPC /process.Process/Start failed (HTTP 500)"
        assert "envd.example.com" not in str(exc)
        await client.close()

    async def test_http_error_no_default_warning_and_no_url_in_logs(self, envd_token, caplog):
        """Error responses emit no default WARNING; DEBUG diagnostics carry no URL.

        The old behaviour printed the error body as a standalone WARNING and
        then raised an httpx error containing the full sandbox URL.  Now the
        details live on the exception; the diagnostic log line is DEBUG-only
        and contains only the RPC path + status + body.
        """
        import logging

        async def chunks():
            yield b'{"error": {"code": "not_found", "message": "exec not found"}}'

        transport = mock_stream_transport(chunks, status=500)
        client = self._make_client()
        # 1) At INFO level (>= default WARNING visibility): zero records.
        with (
            self._patch(transport),
            caplog.at_level(logging.INFO, logger="easy_sandbox.transport.http"),
            pytest.raises(EnvdRpcError),
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        assert not [r for r in caplog.records if r.levelno >= logging.INFO]

        # 2) At DEBUG level the diagnostic line exists but has no URL.
        with (
            self._patch(transport),
            caplog.at_level(logging.DEBUG, logger="easy_sandbox.transport.http"),
            pytest.raises(EnvdRpcError),
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        error_records = [r for r in caplog.records if "failed" in r.getMessage()]
        assert error_records, "expected a DEBUG diagnostic record for the failure"
        for record in error_records:
            assert "envd.example.com" not in record.getMessage()
            assert "https://" not in record.getMessage()
            assert "/process.Process/Start" in record.getMessage()
        await client.close()

    async def test_http_error_body_bounded_and_truncated(self, envd_token):
        """An oversized error body is truncated, never buffered wholesale."""

        async def chunks():
            yield b"x" * 100_000

        transport = mock_stream_transport(chunks, status=500)
        client = self._make_client()
        with (
            self._patch(transport),
            pytest.raises(EnvdRpcError) as ei,
        ):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        assert len(ei.value.body_text) <= 500
        await client.close()

    async def test_connect_error_maps_to_connection_error(self, envd_token):
        """httpx.ConnectError is mapped to the SDK ConnectionError_."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        transport = httpx.MockTransport(handler)
        client = self._make_client()
        with self._patch(transport), pytest.raises(ConnectionError_):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                pass
        await client.close()

    async def test_early_stop_closes_stream_and_client(self, envd_token):
        """Stopping iteration early (aclose) closes the response and client.

        ``StreamReader.cancel()`` propagates ``GeneratorExit`` into the
        generator; the ``async with`` blocks must then close the streaming
        response (releasing the connection) and the httpx client.
        """
        frame1 = make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
        frame2 = make_envd_frame({"event": {"data": {"stdout": "Mg=="}}})
        responses: list[httpx.Response] = []

        async def chunks():
            yield frame1
            yield frame2

        async def handler(request: httpx.Request) -> httpx.Response:
            response = httpx.Response(200, content=chunks())
            responses.append(response)
            return response

        transport = httpx.MockTransport(handler)
        created: list[httpx.AsyncClient] = []
        client = self._make_client()
        with self._patch(transport, created_clients=created):
            gen = client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            )
            first = await gen.__anext__()
            assert first == {"event": {"data": {"stdout": "MQ=="}}}
            await gen.aclose()  # simulates StreamReader.cancel()

        # Both the streaming response and the httpx client were closed.
        assert responses and responses[0].is_closed
        assert created and created[0].is_closed
        await client.close()

    async def test_cancellation_closes_stream_and_client(self, envd_token):
        """Cancelling the consuming task closes the response and client."""
        frame1 = make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
        frame2 = make_envd_frame({"event": {"data": {"stdout": "Mg=="}}})
        responses: list[httpx.Response] = []
        gate = asyncio.Event()

        async def chunks():
            yield frame1
            await gate.wait()
            yield frame2

        async def handler(request: httpx.Request) -> httpx.Response:
            response = httpx.Response(200, content=chunks())
            responses.append(response)
            return response

        transport = httpx.MockTransport(handler)
        created: list[httpx.AsyncClient] = []
        client = self._make_client()

        async def consume() -> list[dict]:
            received: list[dict] = []
            async for frame in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                envd_token=envd_token,
            ):
                received.append(frame)
            return received

        task: asyncio.Task[list[dict]] = asyncio.ensure_future(consume())
        with self._patch(transport, created_clients=created):
            # Wait until the first frame has been consumed (chunk 2 is gated),
            # then cancel the consumer mid-stream.
            while not created:
                await asyncio.sleep(0)
            await asyncio.sleep(0.05)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert responses and responses[0].is_closed
        assert created and created[0].is_closed
        gate.set()  # let the mock byte stream settle for a clean teardown
        await client.close()

    async def test_normal_completion_closes_client(self, envd_token):
        """After the stream finishes normally the httpx client is closed."""

        async def chunks():
            yield make_envd_frame({"event": {"data": {"stdout": "MQ=="}}})
            yield make_envd_frame({"event": {"end": {"exitCode": 0}}})
            yield make_envd_frame({}, flags=0x02)

        transport = mock_stream_transport(chunks)
        created: list[httpx.AsyncClient] = []
        client = self._make_client()
        with self._patch(transport, created_clients=created):
            frames = [
                f
                async for f in client.envd_stream(
                    "https://envd.example.com",
                    "/process.Process/Start",
                    envd_token=envd_token,
                )
            ]
        assert frames == [
            {"event": {"data": {"stdout": "MQ=="}}},
            {"event": {"end": {"exitCode": 0}}},
        ]
        assert created and created[0].is_closed
        await client.close()

    async def test_sends_auth_and_content_type_headers(self, envd_token):
        """Streaming requests carry the envd token and Connect content type."""
        seen: list[httpx.Request] = []

        async def chunks():
            yield make_envd_frame({"ok": True})

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, content=chunks())

        transport = httpx.MockTransport(handler)
        client = self._make_client()
        with self._patch(transport):
            async for _ in client.envd_stream(
                "https://envd.example.com",
                "/process.Process/Start",
                payload={"process": {"cmd": "ls"}},
                envd_token=envd_token,
            ):
                pass

        assert seen, "handler was never called"
        req = seen[0]
        assert req.method == "POST"
        assert req.url.path == "/process.Process/Start"
        assert req.headers["content-type"] == CONNECT_CONTENT_TYPE
        assert req.headers["x-access-token"] == "test-envd-token"
        assert json.loads(req.content) == {"process": {"cmd": "ls"}}
        await client.close()
