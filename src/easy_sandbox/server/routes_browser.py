"""Browser automation route handlers — Playwright-backed headless browser control.

All routes in this module belong to :data:`CapabilityGroup.BROWSER`, which is
**disabled by default**.  Callers must explicitly enable it via
``default_table().enable_group(CapabilityGroup.BROWSER)`` before requests will
be dispatched.

Playwright is imported lazily on first use; if the package is not installed the
endpoints return ``503 Service Unavailable``.

Endpoints:

- ``POST /browser/navigate``   — navigate to a URL
- ``POST /browser/screenshot``  — capture a screenshot
- ``GET  /browser/content``     — retrieve page HTML or text
- ``POST /browser/click``       — click an element
- ``POST /browser/type``        — type text into an element
- ``POST /browser/evaluate``    — execute JavaScript
- ``POST /browser/pdf``         — generate a PDF
- ``GET  /browser/console``     — retrieve collected console logs
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .router import CapabilityGroup, default_table
from .types import ServerRequest, ServerResponse

__all__ = [
    "handle_browser_click",
    "handle_browser_console",
    "handle_browser_content",
    "handle_browser_evaluate",
    "handle_browser_navigate",
    "handle_browser_pdf",
    "handle_browser_screenshot",
    "handle_browser_type",
]

# ---------------------------------------------------------------------------
# Module-level singletons (lazy-initialised)
# ---------------------------------------------------------------------------

_playwright_instance: Any = None
_browser: Any = None
_page: Any = None
_console_logs: list[dict[str, Any]] = []
_MAX_CONSOLE_LOGS = 1000
_browser_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Lazy Playwright bootstrap
# ---------------------------------------------------------------------------


def _get_playwright() -> Any:
    """Return a shared Playwright *page*, creating one on first call.

    Raises:
        RuntimeError: If ``playwright`` is not installed.
    """
    global _playwright_instance, _browser, _page  # noqa: PLW0603

    if _page is not None and not _page.is_closed():
        return _page

    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(  # noqa: B904
            "Playwright is not installed. "
            "Install with: pip install playwright && playwright install chromium"
        )

    if _playwright_instance is None:
        _playwright_instance = sync_playwright().start()
        _browser = _playwright_instance.chromium.launch(headless=True)

    _page = _browser.new_page()

    # Register console-log collector.
    def _on_console(msg: Any) -> None:
        entry = {
            "type": msg.type,
            "text": msg.text,
            "timestamp": time.time(),
        }
        if len(_console_logs) < _MAX_CONSOLE_LOGS:
            _console_logs.append(entry)

    _page.on("console", _on_console)
    return _page


def _cleanup_browser() -> None:
    """Shut down the Playwright browser instance and release resources."""
    global _playwright_instance, _browser, _page  # noqa: PLW0603

    with _browser_lock:
        if _page is not None and not _page.is_closed():
            _page.close()
        _page = None
        if _browser is not None:
            _browser.close()
        _browser = None
        if _playwright_instance is not None:
            _playwright_instance.stop()
        _playwright_instance = None
        _console_logs.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_query(request: ServerRequest, key: str, default: str = "") -> str:
    """Return the first value for *key* in the query-string, or *default*."""
    values = request.query.get(key, [])
    return values[0] if values else default


# ---------------------------------------------------------------------------
# POST /browser/navigate
# ---------------------------------------------------------------------------


def handle_browser_navigate(request: ServerRequest) -> ServerResponse:
    """Navigate the browser to *url*.

    Expected JSON body::

        {"url": "https://example.com", "wait_until": "networkidle", "timeout": 30000}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``url``, ``title``, and ``status``.
    """
    body: dict[str, Any] = request.body or {}
    url = body.get("url")
    if not url or not isinstance(url, str):
        return ServerResponse.error(400, "Missing or invalid 'url'", error_type="ValueError")

    wait_until: str = str(body.get("wait_until", "networkidle"))
    raw_timeout = body.get("timeout", 30000)
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        timeout = 30000
    if timeout <= 0:
        timeout = 30000

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            resp = page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    nav_status = resp.status if resp else 0
    return ServerResponse.ok({
        "url": page.url,
        "title": page.title(),
        "status": nav_status,
    })


# ---------------------------------------------------------------------------
# POST /browser/screenshot
# ---------------------------------------------------------------------------


def handle_browser_screenshot(request: ServerRequest) -> ServerResponse:
    """Capture a screenshot of the current page.

    Expected JSON body::

        {"selector": null, "full_page": true, "format": "png"}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``image_base64``, ``width``, and ``height``.
    """
    import base64  # noqa: PLC0415

    body: dict[str, Any] = request.body or {}
    selector: str | None = body.get("selector")
    full_page: bool = bool(body.get("full_page", True))
    fmt: str = str(body.get("format", "png")).lower()
    if fmt not in {"png", "jpeg"}:
        fmt = "png"

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            if selector:
                element = page.query_selector(selector)
                if element is None:
                    return ServerResponse.error(
                        404, f"Selector not found: {selector}", error_type="ValueError",
                    )
                raw = element.screenshot(type=fmt)
                box = element.bounding_box() or {}
                width = int(box.get("width", 0))
                height = int(box.get("height", 0))
            else:
                raw = page.screenshot(full_page=full_page, type=fmt)
                viewport = page.viewport_size or {}
                width = viewport.get("width", 0)
                height = viewport.get("height", 0)
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    encoded = base64.b64encode(raw).decode("ascii")
    return ServerResponse.ok({
        "image_base64": encoded,
        "width": width,
        "height": height,
    })


# ---------------------------------------------------------------------------
# GET /browser/content
# ---------------------------------------------------------------------------


def handle_browser_content(request: ServerRequest) -> ServerResponse:
    """Return the current page's HTML or inner text.

    Query parameters:
        type: ``"html"`` (default) or ``"text"``.

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``content``, ``url``, and ``title``.
    """
    content_type = _first_query(request, "type", "html").lower()
    if content_type not in {"html", "text"}:
        content_type = "html"

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            content = page.inner_text("body") if content_type == "text" else page.content()
            url = page.url
            title = page.title()
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    return ServerResponse.ok({"content": content, "url": url, "title": title})


# ---------------------------------------------------------------------------
# POST /browser/click
# ---------------------------------------------------------------------------


def handle_browser_click(request: ServerRequest) -> ServerResponse:
    """Click an element identified by *selector*.

    Expected JSON body::

        {"selector": "#submit-btn", "timeout": 5000}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``clicked`` and ``selector``.
    """
    body: dict[str, Any] = request.body or {}
    selector = body.get("selector")
    if not selector or not isinstance(selector, str):
        return ServerResponse.error(400, "Missing or invalid 'selector'", error_type="ValueError")

    raw_timeout = body.get("timeout", 5000)
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        timeout = 5000
    if timeout <= 0:
        timeout = 5000

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            page.click(selector, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    return ServerResponse.ok({"clicked": True, "selector": selector})


# ---------------------------------------------------------------------------
# POST /browser/type
# ---------------------------------------------------------------------------


def handle_browser_type(request: ServerRequest) -> ServerResponse:
    """Type *text* into an element identified by *selector*.

    Expected JSON body::

        {"selector": "#search", "text": "hello", "delay": 50, "clear": false}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``typed``, ``selector``, and ``text``.
    """
    body: dict[str, Any] = request.body or {}
    selector = body.get("selector")
    if not selector or not isinstance(selector, str):
        return ServerResponse.error(400, "Missing or invalid 'selector'", error_type="ValueError")
    text = body.get("text")
    if text is None or not isinstance(text, str):
        return ServerResponse.error(400, "Missing or invalid 'text'", error_type="ValueError")

    raw_delay = body.get("delay", 50)
    try:
        delay = int(raw_delay)
    except (TypeError, ValueError):
        delay = 50
    if delay < 0:
        delay = 50

    clear: bool = bool(body.get("clear", False))

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            if clear:
                page.fill(selector, "")
            page.type(selector, text, delay=delay)
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    return ServerResponse.ok({"typed": True, "selector": selector, "text": text})


# ---------------------------------------------------------------------------
# POST /browser/evaluate
# ---------------------------------------------------------------------------


def handle_browser_evaluate(request: ServerRequest) -> ServerResponse:
    """Execute a JavaScript expression in the page context.

    Expected JSON body::

        {"script": "document.title", "timeout": 10000}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``result``.
    """
    body: dict[str, Any] = request.body or {}
    script = body.get("script")
    if not script or not isinstance(script, str):
        return ServerResponse.error(400, "Missing or invalid 'script'", error_type="ValueError")

    raw_timeout = body.get("timeout", 10000)
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        timeout = 10000
    if timeout <= 0:
        timeout = 10000

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            # Set a default navigation timeout that also limits evaluate.
            page.set_default_timeout(timeout)
            result = page.evaluate(script)
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    return ServerResponse.ok({"result": result})


# ---------------------------------------------------------------------------
# POST /browser/pdf
# ---------------------------------------------------------------------------


def handle_browser_pdf(request: ServerRequest) -> ServerResponse:
    """Generate a PDF of the current page.

    Expected JSON body::

        {"format": "A4", "landscape": false}

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``pdf_base64`` and ``pages``.
    """
    import base64  # noqa: PLC0415

    body: dict[str, Any] = request.body or {}
    page_format: str = str(body.get("format", "A4"))
    landscape: bool = bool(body.get("landscape", False))

    with _browser_lock:
        try:
            page = _get_playwright()
        except RuntimeError as exc:
            return ServerResponse.error(503, str(exc), error_type="RuntimeError")

        try:
            raw = page.pdf(format=page_format, landscape=landscape)
        except Exception as exc:  # noqa: BLE001
            return ServerResponse.error(500, str(exc), error_type=type(exc).__name__)

    encoded = base64.b64encode(raw).decode("ascii")
    # Rough page count: PDF pages are separated by "/Type /Page" entries.
    pages = raw.count(b"/Type /Page") or 1
    return ServerResponse.ok({"pdf_base64": encoded, "pages": pages})


# ---------------------------------------------------------------------------
# GET /browser/console
# ---------------------------------------------------------------------------


def handle_browser_console(request: ServerRequest) -> ServerResponse:
    """Return collected console log entries and clear the buffer.

    Args:
        request: The parsed :class:`ServerRequest`.

    Returns:
        A :class:`ServerResponse` with ``logs`` list.
    """
    with _browser_lock:
        logs = list(_console_logs)
        _console_logs.clear()
    return ServerResponse.ok({"logs": logs})


# ---------------------------------------------------------------------------
# Register routes on the default table (import side-effect)
# ---------------------------------------------------------------------------

_table = default_table()
_table.register(
    "POST", "/browser/navigate", handle_browser_navigate,
    group=CapabilityGroup.BROWSER, name="browser_navigate",
)
_table.register(
    "POST", "/browser/screenshot", handle_browser_screenshot,
    group=CapabilityGroup.BROWSER, name="browser_screenshot",
)
_table.register(
    "GET", "/browser/content", handle_browser_content,
    group=CapabilityGroup.BROWSER, name="browser_content",
)
_table.register(
    "POST", "/browser/click", handle_browser_click,
    group=CapabilityGroup.BROWSER, name="browser_click",
)
_table.register(
    "POST", "/browser/type", handle_browser_type,
    group=CapabilityGroup.BROWSER, name="browser_type",
)
_table.register(
    "POST", "/browser/evaluate", handle_browser_evaluate,
    group=CapabilityGroup.BROWSER, name="browser_evaluate",
)
_table.register(
    "POST", "/browser/pdf", handle_browser_pdf,
    group=CapabilityGroup.BROWSER, name="browser_pdf",
)
_table.register(
    "GET", "/browser/console", handle_browser_console,
    group=CapabilityGroup.BROWSER, name="browser_console",
)
