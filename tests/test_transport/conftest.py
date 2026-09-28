"""Fixtures for transport tests.

Isolates :mod:`easy_sandbox.transport.config` loading so tests never read the
repository's real ``.env`` (or a developer's ``~/.ebx/config.toml``). The
production loader discovers ``.env`` via a CWD-relative ``Path(".env")``
candidate, so running the suite from the repo root would otherwise pull real
credentials into the test process — making results depend on local files and
leaking secrets into test config. We redirect discovery at an empty temp path
and strip recognised credential/config env vars inherited from the shell.

The production behaviour (explicit ``.env`` discovery from the working
directory) is intentional and left unchanged; isolation lives entirely in the
test fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easy_sandbox.transport import config as _config

if TYPE_CHECKING:
    from collections.abc import Iterator

# Every env var recognised by ``_ENV_VAR_MAP`` that could carry real
# credentials or config from the developer's shell into a test run.
_LEAKY_ENV_VARS = (
    "E2B_API_KEY",
    "E2B_API_URL",
    "E2B_DOMAIN",
    "SANDBOX_API_KEY",
    "SANDBOX_API_BASE_URL",
    "SANDBOX_REGION",
    "SANDBOX_HTTP_TIMEOUT",
    "ALICLOUD_ACCESS_KEY_ID",
    "ALICLOUD_ACCESS_KEY_SECRET",
    "AccessKey",
    "AccessSecret",
)


@pytest.fixture(autouse=True)
def isolate_transport_config(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[None]:
    """Prevent transport-config tests from reading the real ``.env``/config.toml.

    Points ``.env`` and ``config.toml`` discovery at an empty temp directory and
    clears recognised credential/config env vars, so each test starts from a
    clean, deterministic baseline regardless of the CWD or the developer's shell.
    """
    isolated_dir = tmp_path / "config_isolation"
    isolated_dir.mkdir()
    # Redirect .env discovery away from any CWD-relative real file.
    monkeypatch.setattr(_config, "_ENV_FILE_CANDIDATES", [isolated_dir / ".env"])
    # Redirect the optional ~/.ebx/config.toml extension source too.
    monkeypatch.setattr(_config, "_CONFIG_FILE", isolated_dir / "config.toml")
    for name in _LEAKY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _config.reset_config()
    yield
    _config.reset_config()
