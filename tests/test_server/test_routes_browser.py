"""Tests for serverless_sandbox.server.routes_browser — browser automation endpoints.

Covers:
- BROWSER group disabled by default (endpoints return 404)
- Playwright unavailable → 503
- Mock-based handler logic (navigate, screenshot, content, click, type, evaluate, pdf, console)
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any
from unittest import mock

import pytest

# Import the browser routes so they register on the default table.
import serverless_sandbox.server.routes_browser as routes_browser_mod  # noqa: F401
from serverless_sandbox.server.app import SandboxRequestHandler
from serverless_sandbox.server.registry import CommandRegistry
from serverless_sandbox.server.router import CapabilityGroup, default_table

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int) -> ThreadingHTTPServer:
    """Create and start a no-auth server on *port* in a daemon thread."""
    registry = CommandRegistry()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), SandboxRequestHandler)
    httpd.auth_token = None  # type: ignore[attr-defined]
    httpd.registry = registry  # type: ignore[attr-defined]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    return httpd


def _request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    """Send an HTTP request and return ``(status, json_body)``."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    payload = json.dumps(body).encode() if body is not None else None
    hdrs: dict[str, str] = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    conn.request(method, path, body=payload, headers=hdrs)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    status = resp.status
    conn.close()
    return status, data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def server_port() -> Any:
    """Spin up a no-auth server on a random port and tear it down after."""
    port = _find_free_port()
    httpd = _start_server(port)
    yield port
    httpd.shutdown()


# ---------------------------------------------------------------------------
# BROWSER disabled by default
# ---------------------------------------------------------------------------


class TestBrowserDisabledByDefault:
    """When BROWSER is not explicitly enabled, endpoints should 404."""

    @pytest.fixture(autouse=True)
    def _disable_browser(self) -> Any:
        """Ensure BROWSER is disabled for every test in this class."""
        table = default_table()
        table.disable_group(CapabilityGroup.BROWSER)
        yield
        # Leave it disabled (default state).

    def test_navigate_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port, "POST", "/browser/navigate",
            body={"url": "https://example.com"},
        )
        assert status == 404

    def test_screenshot_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port, "POST", "/browser/screenshot", body={},
        )
        assert status == 404

    def test_content_404(self, server_port: int) -> None:
        status, _body = _request(server_port, "GET", "/browser/content")
        assert status == 404

    def test_click_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port, "POST", "/browser/click",
            body={"selector": "#btn"},
        )
        assert status == 404

    def test_type_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port, "POST", "/browser/type",
            body={"selector": "#input", "text": "hi"},
        )
        assert status == 404

    def test_evaluate_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port, "POST", "/browser/evaluate",
            body={"script": "1+1"},
        )
        assert status == 404

    def test_pdf_404(self, server_port: int) -> None:
        status, _body = _request(
            server_port, "POST", "/browser/pdf", body={},
        )
        assert status == 404

    def test_console_404(self, server_port: int) -> None:
        status, _body = _request(server_port, "GET", "/browser/console")
        assert status == 404


# ---------------------------------------------------------------------------
# Playwright unavailable → 503
# ---------------------------------------------------------------------------


class TestPlaywrightUnavailable:
    """With BROWSER enabled but Playwright not installed, endpoints return 503."""

    @pytest.fixture(autouse=True)
    def _enable_browser(self) -> Any:
        table = default_table()
        table.enable_group(CapabilityGroup.BROWSER)
        # Ensure the lazy singletons are reset so _get_playwright() is invoked.
        routes_browser_mod._playwright_instance = None
        routes_browser_mod._browser = None
        routes_browser_mod._page = None
        yield
        table.disable_group(CapabilityGroup.BROWSER)
        routes_browser_mod._playwright_instance = None
        routes_browser_mod._browser = None
        routes_browser_mod._page = None

    def test_navigate_503(self, server_port: int) -> None:
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            status, body = _request(
                server_port, "POST", "/browser/navigate",
                body={"url": "https://example.com"},
            )
        assert status == 503
        assert "Playwright" in body["error"]

    def test_screenshot_503(self, server_port: int) -> None:
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            status, body = _request(
                server_port, "POST", "/browser/screenshot", body={},
            )
        assert status == 503

    def test_content_503(self, server_port: int) -> None:
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            status, body = _request(server_port, "GET", "/browser/content")
        assert status == 503

    def test_click_503(self, server_port: int) -> None:
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            status, body = _request(
                server_port, "POST", "/browser/click",
                body={"selector": "#x"},
            )
        assert status == 503

    def test_evaluate_503(self, server_port: int) -> None:
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            status, body = _request(
                server_port, "POST", "/browser/evaluate",
                body={"script": "1"},
            )
        assert status == 503

    def test_console_returns_empty(self, server_port: int) -> None:
        """Console endpoint does not need Playwright — returns empty logs."""
        status, body = _request(server_port, "GET", "/browser/console")
        assert status == 200
        assert body["logs"] == []


# ---------------------------------------------------------------------------
# Input validation (no Playwright needed)
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Handler input validation — returns 400 without touching Playwright."""

    @pytest.fixture(autouse=True)
    def _enable_browser(self) -> Any:
        table = default_table()
        table.enable_group(CapabilityGroup.BROWSER)
        yield
        table.disable_group(CapabilityGroup.BROWSER)

    def test_navigate_missing_url(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/browser/navigate", body={},
        )
        assert status == 400
        assert "url" in body["error"].lower()

    def test_click_missing_selector(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/browser/click", body={},
        )
        assert status == 400
        assert "selector" in body["error"].lower()

    def test_type_missing_selector(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/browser/type",
            body={"text": "hello"},
        )
        assert status == 400
        assert "selector" in body["error"].lower()

    def test_type_missing_text(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/browser/type",
            body={"selector": "#x"},
        )
        assert status == 400
        assert "text" in body["error"].lower()

    def test_evaluate_missing_script(self, server_port: int) -> None:
        status, body = _request(
            server_port, "POST", "/browser/evaluate", body={},
        )
        assert status == 400
        assert "script" in body["error"].lower()


# ---------------------------------------------------------------------------
# Mock-based handler logic tests
# ---------------------------------------------------------------------------


class TestMockBrowserHandlers:
    """Test handler logic with a fully mocked Playwright page."""

    @pytest.fixture(autouse=True)
    def _enable_and_mock_browser(self) -> Any:
        """Enable BROWSER group and inject a mock page singleton."""
        table = default_table()
        table.enable_group(CapabilityGroup.BROWSER)

        mock_page = mock.MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "https://example.com"
        mock_page.title.return_value = "Example"
        mock_page.viewport_size = {"width": 1280, "height": 720}

        # Store originals so we can restore.
        orig_pw = routes_browser_mod._playwright_instance
        orig_br = routes_browser_mod._browser
        orig_pg = routes_browser_mod._page

        routes_browser_mod._playwright_instance = mock.MagicMock()
        routes_browser_mod._browser = mock.MagicMock()
        routes_browser_mod._page = mock_page
        routes_browser_mod._console_logs.clear()

        yield mock_page

        routes_browser_mod._playwright_instance = orig_pw
        routes_browser_mod._browser = orig_br
        routes_browser_mod._page = orig_pg
        routes_browser_mod._console_logs.clear()
        table.disable_group(CapabilityGroup.BROWSER)

    def test_navigate(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        page.goto.return_value = mock_resp

        status, body = _request(
            server_port, "POST", "/browser/navigate",
            body={"url": "https://example.com"},
        )
        assert status == 200
        assert body["url"] == "https://example.com"
        assert body["title"] == "Example"
        assert body["status"] == 200
        page.goto.assert_called_once()

    def test_screenshot(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        # Return fake PNG bytes (minimal valid-ish content).
        page.screenshot.return_value = b"\x89PNG\r\n\x1a\n"

        status, body = _request(
            server_port, "POST", "/browser/screenshot",
            body={"full_page": True},
        )
        assert status == 200
        assert "image_base64" in body
        assert body["width"] == 1280
        assert body["height"] == 720

    def test_screenshot_selector(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        elem = mock.MagicMock()
        elem.screenshot.return_value = b"\x89PNG"
        elem.bounding_box.return_value = {"width": 100, "height": 50}
        page.query_selector.return_value = elem

        status, body = _request(
            server_port, "POST", "/browser/screenshot",
            body={"selector": "#logo"},
        )
        assert status == 200
        assert body["width"] == 100
        assert body["height"] == 50

    def test_screenshot_selector_not_found(
        self, server_port: int, _enable_and_mock_browser: Any,
    ) -> None:
        page = _enable_and_mock_browser
        page.query_selector.return_value = None

        status, body = _request(
            server_port, "POST", "/browser/screenshot",
            body={"selector": "#nonexistent"},
        )
        assert status == 404
        assert "not found" in body["error"].lower()

    def test_content_html(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        page.content.return_value = "<html><body>Hello</body></html>"

        status, body = _request(server_port, "GET", "/browser/content?type=html")
        assert status == 200
        assert "<html>" in body["content"]

    def test_content_text(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        page.inner_text.return_value = "Hello World"

        status, body = _request(server_port, "GET", "/browser/content?type=text")
        assert status == 200
        assert body["content"] == "Hello World"

    def test_click(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser

        status, body = _request(
            server_port, "POST", "/browser/click",
            body={"selector": "#btn"},
        )
        assert status == 200
        assert body["clicked"] is True
        assert body["selector"] == "#btn"
        page.click.assert_called_once_with("#btn", timeout=5000)

    def test_type(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser

        status, body = _request(
            server_port, "POST", "/browser/type",
            body={"selector": "#search", "text": "hello", "delay": 100},
        )
        assert status == 200
        assert body["typed"] is True
        assert body["text"] == "hello"
        page.type.assert_called_once_with("#search", "hello", delay=100)

    def test_type_with_clear(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser

        status, body = _request(
            server_port, "POST", "/browser/type",
            body={"selector": "#input", "text": "new", "clear": True},
        )
        assert status == 200
        page.fill.assert_called_once_with("#input", "")
        page.type.assert_called_once()

    def test_evaluate(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        page.evaluate.return_value = 42

        status, body = _request(
            server_port, "POST", "/browser/evaluate",
            body={"script": "1 + 41"},
        )
        assert status == 200
        assert body["result"] == 42

    def test_pdf(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        # Return minimal bytes that contain the marker for page counting.
        page.pdf.return_value = b"%PDF-1.4 /Type /Page endobj"

        status, body = _request(
            server_port, "POST", "/browser/pdf",
            body={"format": "A4", "landscape": False},
        )
        assert status == 200
        assert "pdf_base64" in body
        assert body["pages"] >= 1
        page.pdf.assert_called_once_with(format="A4", landscape=False)

    def test_console_empty(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        status, body = _request(server_port, "GET", "/browser/console")
        assert status == 200
        assert body["logs"] == []

    def test_console_with_logs(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        # Inject fake console log entries.
        routes_browser_mod._console_logs.extend([
            {"type": "log", "text": "hello", "timestamp": 1234567890.0},
            {"type": "error", "text": "oops", "timestamp": 1234567891.0},
        ])

        status, body = _request(server_port, "GET", "/browser/console")
        assert status == 200
        assert len(body["logs"]) == 2
        assert body["logs"][0]["text"] == "hello"
        assert body["logs"][1]["type"] == "error"

        # Second call should return empty (buffer cleared).
        status2, body2 = _request(server_port, "GET", "/browser/console")
        assert status2 == 200
        assert body2["logs"] == []

    def test_navigate_goto_error(self, server_port: int, _enable_and_mock_browser: Any) -> None:
        page = _enable_and_mock_browser
        page.goto.side_effect = Exception("net::ERR_NAME_NOT_RESOLVED")

        status, body = _request(
            server_port, "POST", "/browser/navigate",
            body={"url": "https://nonexistent.invalid"},
        )
        assert status == 500
        assert "ERR_NAME_NOT_RESOLVED" in body["error"]
