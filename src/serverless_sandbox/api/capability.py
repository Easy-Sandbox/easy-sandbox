"""Capability resolver — resolves template capabilities and custom commands.

Phase 1: local-only resolution from ``~/.sbox/templates/`` cache.
Phase 2 will add online fallback via ``GET /templates/{id}`` metadata.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from serverless_sandbox.models.errors import (
    CapabilityNotSupportedError,
    TemplateParseError,
)
from serverless_sandbox.models.template import (
    DEFAULT_CAPABILITIES,
    CustomCommand,
    SandboxTemplate,
)
from serverless_sandbox.utils.logging import get_logger

logger = get_logger("api.capability")

TEMPLATE_CACHE_DIR = Path.home() / ".sbox" / "templates"


class ResolvedCapabilities(BaseModel):
    """The resolved capability set and custom commands for a sandbox."""

    capabilities: set[str] = Field(default_factory=lambda: set(DEFAULT_CAPABILITIES))
    custom_commands: dict[str, CustomCommand] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Capability gate helper
# ---------------------------------------------------------------------------

def check_capability(capabilities: set[str], required: str) -> None:
    """Raise :class:`CapabilityNotSupportedError` when *required* is missing."""
    if required not in capabilities:
        raise CapabilityNotSupportedError(required)


# ---------------------------------------------------------------------------
# Local resolution
# ---------------------------------------------------------------------------

def _template_matches(
    data: dict[str, Any],
    yaml_path: Path,
    template_id: str,
) -> bool:
    """Return True when *data* (a raw template dict at *yaml_path*) refers
    to *template_id*.

    Matching is intentionally broad: it compares against the ``name`` field,
    the ``alias`` / ``aliases`` fields, and the containing directory name —
    because a template may be referenced by any of these.  Matching too
    narrowly would silently fall back to ``DEFAULT_CAPABILITIES`` and
    wrongly gate a template that actually declares ``terminal`` / ``ports``.
    """
    if data.get("name") == template_id:
        return True

    alias = data.get("alias")
    if isinstance(alias, str) and alias == template_id:
        return True

    aliases = data.get("aliases")
    if isinstance(aliases, str) and aliases == template_id:
        return True
    if isinstance(aliases, (list, tuple)) and template_id in aliases:
        return True

    return yaml_path.parent.name == template_id


def _find_local_template(template_id: str) -> SandboxTemplate | None:
    """Scan ``~/.sbox/templates/`` for a ``template.yaml`` that
    matches *template_id* by ``name``, ``alias``/``aliases``, or directory
    name.

    Returns ``None`` when nothing matches.

    Fail-closed: when a template *matches* but fails model validation, a
    :class:`~serverless_sandbox.models.errors.TemplateParseError` is raised
    instead of skipping it — skipping would silently widen permissions by
    falling back to ``DEFAULT_CAPABILITIES``.  Only unreadable files and
    non-dict documents are skipped (they cannot have matched).
    """
    if not TEMPLATE_CACHE_DIR.exists():
        return None

    for yaml_path in TEMPLATE_CACHE_DIR.rglob("template.yaml"):
        # (a) Unreadable file / non-dict document → skip, keep scanning.
        try:
            data = yaml.safe_load(yaml_path.read_text())
        except Exception:  # noqa: BLE001
            logger.debug("Skipping unreadable template at %s", yaml_path, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue

        if not _template_matches(data, yaml_path, template_id):
            continue

        # (b) Matched but malformed → fail-closed, do NOT fall back.
        try:
            return _parse_template(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Matched template at %s failed validation; refusing to fall "
                "back to DEFAULT_CAPABILITIES (fail-closed)",
                yaml_path,
                exc_info=True,
            )
            raise TemplateParseError(
                f"Template {template_id!r} at {yaml_path} is malformed: {exc}"
            ) from exc

    return None


def _parse_template(data: dict[str, Any]) -> SandboxTemplate:
    """Parse a raw YAML dict into a :class:`SandboxTemplate`."""
    resources = data.pop("resources", {}) or {}
    if "cpu" in resources and "cpu_count" not in data:
        data["cpu_count"] = resources["cpu"]
    if "memory" in resources and "memory_mb" not in data:
        data["memory_mb"] = resources["memory"]
    return SandboxTemplate.model_validate(data)


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

async def resolve_capabilities(
    template_id: str | None = None,
    *,
    local_yaml_path: str | None = None,
) -> ResolvedCapabilities:
    """Resolve capabilities for a template.

    Resolution order:

    1. If *local_yaml_path* is given, parse it directly.
    2. Scan ``~/.sbox/templates/`` for a matching template name.
    3. **TODO(Phase2):** ``GET /templates/{id}`` metadata fallback.
    4. Fall back to :data:`DEFAULT_CAPABILITIES` with no custom commands
       and emit a warning.

    Returns:
        A :class:`ResolvedCapabilities` instance.
    """
    template: SandboxTemplate | None = None

    # 1. Explicit local path
    if local_yaml_path:
        path = Path(local_yaml_path)
        if path.exists():
            # (a) Unreadable / non-dict → skip, fall through to scan+default.
            try:
                data = yaml.safe_load(path.read_text())
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to read local template YAML at %s, using defaults",
                    local_yaml_path,
                    exc_info=True,
                )
                data = None
            if isinstance(data, dict):
                # (b) Explicitly provided + parsed as dict but malformed →
                # fail-closed rather than silently granting defaults.
                try:
                    template = _parse_template(data)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Local template YAML at %s failed validation; "
                        "refusing to fall back to DEFAULT_CAPABILITIES "
                        "(fail-closed)",
                        local_yaml_path,
                        exc_info=True,
                    )
                    raise TemplateParseError(
                        f"Template at {local_yaml_path} is malformed: {exc}"
                    ) from exc

    # 2. Scan local cache
    if template is None and template_id:
        template = _find_local_template(template_id)

    # 3. TODO(Phase2): online fallback — GET /templates/{id} metadata

    # 4. Fallback
    if template is None:
        logger.warning(
            "Could not resolve capabilities for template %r; "
            "falling back to DEFAULT_CAPABILITIES",
            template_id,
        )
        return ResolvedCapabilities()

    # Build result from the resolved template
    caps: set[str]
    if template.capabilities is not None:
        caps = set(template.capabilities)
    else:
        caps = set(DEFAULT_CAPABILITIES)

    return ResolvedCapabilities(
        capabilities=caps,
        custom_commands=dict(template.custom_commands),
    )
