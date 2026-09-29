"""Offline validation of the ``examples/templates/`` fixtures.

``examples/templates/`` no longer holds a publishable template collection.
The single source of truth for official & community templates — content,
the machine-readable index, releases and CI — is the dedicated repository
``Easy-Sandbox/awesome-templates``.  This repository keeps only a minimal
**fixture** (``python-hello``) so that the install / server pipelines stay
testable fully offline.

Covered contracts
-----------------
(a) ``template.yaml`` exists and parses through the *real* production
    loader (``utils.registry.load_template_from_yaml``) into a valid
    ``SandboxTemplate``.
(b) Required fields are present; every ``capabilities`` token is inside
    ``STANDARD_CAPABILITIES``; ``custom_commands`` entries are structurally
    valid and their ``{placeholder}`` tokens are all backed by an ``args``
    declaration.
(c) ``Dockerfile`` and ``README.md`` exist next to the YAML.
(d) The directory is *explicitly marked as a fixture* (README + YAML banner)
    and contains only the expected fixture folders — it must never
    silently grow back into a duplicate template collection.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml
from pydantic import ValidationError

from easy_sandbox.agent.infer import TEMPLATE_CATALOG
from easy_sandbox.models.template import (
    DEFAULT_CAPABILITIES,
    STANDARD_CAPABILITIES,
    CustomCommand,
    SandboxTemplate,
)
from easy_sandbox.utils.registry import load_template_from_yaml

from .conftest import (
    EXPECTED_FIXTURE_TEMPLATES,
    REQUIRED_TEMPLATE_FILES,
    REQUIRED_YAML_KEYS,
    SOURCE_OF_TRUTH_URL,
)

if TYPE_CHECKING:
    from pathlib import Path

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _yaml_path(template_dir: Path) -> Path:
    return template_dir / "template.yaml"


def _load(template_dir: Path) -> SandboxTemplate:
    """Load through the real loader — the same code path ``ebx install`` uses."""
    return load_template_from_yaml(_yaml_path(template_dir))


def _raw(template_dir: Path) -> dict:
    """Raw YAML mapping (pre-model), to assert on keys that the model defaults."""
    data = yaml.safe_load(_yaml_path(template_dir).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{_yaml_path(template_dir)} is not a YAML mapping"
    return data


# ---------------------------------------------------------------------------
# (c) Required files
# ---------------------------------------------------------------------------


class TestRequiredFiles:
    """Every template folder ships the three mandatory files."""

    @pytest.mark.parametrize("filename", REQUIRED_TEMPLATE_FILES)
    def test_required_file_exists(self, template_dir: Path, filename: str) -> None:
        path = template_dir / filename
        assert path.is_file(), (
            f"{template_dir.name}: required file {filename!r} is missing (expected at {path})"
        )
        assert path.stat().st_size > 0, f"{template_dir.name}: {filename} exists but is empty"

    def test_no_unexpected_required_file_names(self, template_dir: Path) -> None:
        """Guard against typos such as ``sandbox_template.yaml`` / ``dockerfile``."""
        present = {p.name for p in template_dir.iterdir()}
        for alias in ("sandbox_template.yaml", "dockerfile"):
            assert alias not in present, (
                f"{template_dir.name}: found {alias!r} — the canonical name is "
                f"{REQUIRED_TEMPLATE_FILES[0]!r} / 'Dockerfile'"
            )


# ---------------------------------------------------------------------------
# (a) + (b) YAML validity
# ---------------------------------------------------------------------------


class TestTemplateYaml:
    """``template.yaml`` parses and satisfies the model contract."""

    def test_parses_with_real_loader(self, template_dir: Path) -> None:
        tmpl = _load(template_dir)
        assert isinstance(tmpl, SandboxTemplate)
        assert tmpl.name == template_dir.name

    def test_required_keys_declared_explicitly(self, template_dir: Path) -> None:
        raw = _raw(template_dir)
        missing = [k for k in REQUIRED_YAML_KEYS if k not in raw]
        assert not missing, (
            f"{template_dir.name}: template.yaml is missing required key(s): {missing}"
        )

    def test_name_is_kebab_case(self, template_dir: Path) -> None:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", template_dir.name), (
            f"{template_dir.name}: template names must be kebab-case"
        )

    def test_version_is_semver(self, template_dir: Path) -> None:
        version = _load(template_dir).version
        assert _SEMVER_RE.match(version), (
            f"{template_dir.name}: version {version!r} is not semver-like"
        )

    def test_description_non_empty(self, template_dir: Path) -> None:
        assert _load(template_dir).description.strip(), (
            f"{template_dir.name}: description must not be blank"
        )

    def test_tags_non_empty_and_lowercase(self, template_dir: Path) -> None:
        tags = _load(template_dir).tags
        assert tags, f"{template_dir.name}: declare at least one tag"
        for tag in tags:
            assert tag == tag.strip().lower(), (
                f"{template_dir.name}: tag {tag!r} should be trimmed lowercase"
            )

    def test_resources_when_declared_are_positive(self, template_dir: Path) -> None:
        tmpl = _load(template_dir)
        if tmpl.cpu_count is not None:
            assert tmpl.cpu_count > 0
        if tmpl.memory_mb is not None:
            assert tmpl.memory_mb > 0

    def test_dockerfile_has_from_line(self, template_dir: Path) -> None:
        """The hand-written Dockerfile must have a valid FROM line."""
        dockerfile = (template_dir / "Dockerfile").read_text(encoding="utf-8")
        from_lines = [
            line.strip()
            for line in dockerfile.splitlines()
            if line.strip().upper().startswith("FROM ")
        ]
        assert from_lines, f"{template_dir.name}: Dockerfile has no FROM line"


class TestCapabilities:
    """Capability declarations stay inside the closed vocabulary."""

    def test_capabilities_are_standard(self, template_dir: Path) -> None:
        caps = _load(template_dir).capabilities
        if caps is None:
            return  # inherits DEFAULT_CAPABILITIES — legal
        unknown = [c for c in caps if c not in STANDARD_CAPABILITIES]
        assert not unknown, (
            f"{template_dir.name}: unknown capability(ies) {unknown}; "
            f"allowed: {sorted(STANDARD_CAPABILITIES)}"
        )

    def test_capabilities_declared_explicitly(self, template_dir: Path) -> None:
        """Fixture templates must spell their capability set out."""
        raw = _raw(template_dir)
        assert "capabilities" in raw, (
            f"{template_dir.name}: declare 'capabilities' explicitly instead of "
            f"relying on DEFAULT_CAPABILITIES={sorted(DEFAULT_CAPABILITIES)}"
        )
        caps = _load(template_dir).capabilities
        assert caps, f"{template_dir.name}: 'capabilities' must not be an empty list"

    def test_capabilities_are_unique(self, template_dir: Path) -> None:
        caps = _load(template_dir).capabilities or []
        assert len(caps) == len(set(caps)), (
            f"{template_dir.name}: duplicate capability tokens in {caps}"
        )

    def test_ports_capability_matches_declared_ports(self, template_dir: Path) -> None:
        """``ports`` capability and the top-level ``ports:`` list go together."""
        tmpl = _load(template_dir)
        caps = set(tmpl.capabilities or DEFAULT_CAPABILITIES)
        if tmpl.ports:
            assert "ports" in caps, (
                f"{template_dir.name}: declares ports={tmpl.ports} but the "
                f"'ports' capability is missing"
            )
        if "ports" in caps:
            assert tmpl.ports, (
                f"{template_dir.name}: declares the 'ports' capability but no "
                f"top-level 'ports:' list"
            )

    def test_model_rejects_unknown_capability(self) -> None:
        """Sanity check that the validator we rely on is actually wired up."""
        with pytest.raises(ValidationError, match="Unknown capability"):
            SandboxTemplate.model_validate({"name": "x", "capabilities": ["not-a-capability"]})


class TestCustomCommands:
    """``custom_commands`` structure and placeholder/arg consistency."""

    def test_values_are_custom_command_models(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            assert isinstance(cmd, CustomCommand), (
                f"{template_dir.name}.{name} did not parse into CustomCommand"
            )

    def test_command_names_are_identifier_like(self, template_dir: Path) -> None:
        for name in _load(template_dir).custom_commands:
            assert re.fullmatch(r"[a-z][a-z0-9_-]*", name), (
                f"{template_dir.name}: custom command name {name!r} must be "
                f"lowercase identifier-like (used as `ebx run <id> {name}`)"
            )

    def test_cmd_is_non_empty(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            assert cmd.cmd.strip(), f"{template_dir.name}.{name}: 'cmd' must not be blank"

    def test_timeout_is_positive(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            assert cmd.timeout > 0, (
                f"{template_dir.name}.{name}: timeout must be > 0, got {cmd.timeout}"
            )

    def test_cwd_is_absolute(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            assert cmd.cwd.startswith("/"), (
                f"{template_dir.name}.{name}: cwd {cmd.cwd!r} must be absolute"
            )

    def test_env_values_are_strings(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            for key, value in cmd.env.items():
                assert isinstance(key, str) and isinstance(value, str), (
                    f"{template_dir.name}.{name}: env {key!r}={value!r} must be str→str"
                )

    def test_placeholders_are_backed_by_args(self, template_dir: Path) -> None:
        """Every ``{token}`` in ``cmd`` must have a matching ``args`` entry."""
        for name, cmd in _load(template_dir).custom_commands.items():
            declared = {a.name for a in cmd.args}
            used = set(_PLACEHOLDER_RE.findall(cmd.cmd))
            assert used <= declared, (
                f"{template_dir.name}.{name}: placeholders {sorted(used - declared)} "
                f"have no matching args entry (declared: {sorted(declared)})"
            )

    def test_args_are_all_used(self, template_dir: Path) -> None:
        """No dangling arg declarations (they would silently do nothing)."""
        for name, cmd in _load(template_dir).custom_commands.items():
            used = set(_PLACEHOLDER_RE.findall(cmd.cmd))
            declared = {a.name for a in cmd.args}
            assert declared <= used, (
                f"{template_dir.name}.{name}: args {sorted(declared - used)} are "
                f"declared but never referenced in cmd={cmd.cmd!r}"
            )

    def test_arg_names_unique_and_identifier_like(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            names = [a.name for a in cmd.args]
            assert len(names) == len(set(names)), (
                f"{template_dir.name}.{name}: duplicate arg names {names}"
            )
            for arg_name in names:
                assert re.fullmatch(r"[a-z_][a-z0-9_]*", arg_name), (
                    f"{template_dir.name}.{name}: arg {arg_name!r} must be a lowercase identifier"
                )

    def test_required_args_have_no_default(self, template_dir: Path) -> None:
        """``required: true`` + ``default`` would make the requirement a no-op."""
        for name, cmd in _load(template_dir).custom_commands.items():
            for arg in cmd.args:
                if arg.required:
                    assert arg.default is None, (
                        f"{template_dir.name}.{name}: arg {arg.name!r} is required "
                        f"but also has default={arg.default!r}"
                    )
                else:
                    assert arg.default is not None, (
                        f"{template_dir.name}.{name}: optional arg {arg.name!r} "
                        f"needs a default so the command stays runnable"
                    )


# ---------------------------------------------------------------------------
# (d) Fixture boundary: marked, minimal, never a duplicate collection
# ---------------------------------------------------------------------------


class TestFixtureBoundary:
    """The directory is a *fixture* — marked as such and kept minimal.

    These tests are the guardrail for the single-source-of-truth split: if a
    full template collection ever grows back here (or the fixture notice is
    dropped), the suite fails instead of silently re-diverging from the
    catalog repository.
    """

    def test_only_expected_fixture_templates_exist(self, template_dirs: list[Path]) -> None:
        names = sorted(d.name for d in template_dirs)
        assert names == sorted(EXPECTED_FIXTURE_TEMPLATES), (
            f"examples/templates/ must only contain the offline fixtures "
            f"{sorted(EXPECTED_FIXTURE_TEMPLATES)}, found {names}. Publishable "
            f"templates belong to {SOURCE_OF_TRUTH_URL} instead."
        )

    def test_index_readme_declares_fixture_status(self, catalog_readme: Path) -> None:
        readme = catalog_readme.read_text(encoding="utf-8").lower()
        assert "fixture" in readme, (
            "examples/templates/README.md must state that this directory holds "
            "offline fixtures only"
        )
        assert "publishing source" in readme, (
            "examples/templates/README.md must state that this directory is NOT "
            "the publishing source"
        )

    def test_index_readme_links_the_source_of_truth(self, catalog_readme: Path) -> None:
        readme = catalog_readme.read_text(encoding="utf-8")
        assert SOURCE_OF_TRUTH_URL in readme, (
            f"examples/templates/README.md must point at the single source of truth "
            f"({SOURCE_OF_TRUTH_URL})"
        )

    def test_index_readme_documents_remote_install_flow(self, catalog_readme: Path) -> None:
        readme = catalog_readme.read_text(encoding="utf-8")
        assert "ebx template search" in readme
        assert "ebx template install" in readme
        assert "EBX_TEMPLATE_INDEX_URL" in readme, (
            "README must document the index override for private mirrors"
        )

    def test_fixture_yaml_carries_a_fixture_banner(self, template_dirs: list[Path]) -> None:
        for folder in template_dirs:
            text = (folder / "template.yaml").read_text(encoding="utf-8")
            assert "FIXTURE" in text, (
                f"{folder.name}/template.yaml must carry an explicit FIXTURE banner "
                f"so it is never mistaken for a publishable template"
            )

    def test_fixture_readme_carries_a_fixture_notice(self, template_dirs: list[Path]) -> None:
        for folder in template_dirs:
            text = (folder / "README.md").read_text(encoding="utf-8")
            assert "fixture" in text.lower(), (
                f"{folder.name}/README.md must carry an explicit fixture notice"
            )


# ---------------------------------------------------------------------------
# Inference catalog sanity (unrelated to the fixture boundary)
# ---------------------------------------------------------------------------


class TestInferenceCatalog:
    """Sanity checks that do not depend on the on-disk fixtures."""

    def test_catalog_entries_are_unique(self) -> None:
        """Duplicate catalog names would make inference ambiguous."""
        names = [p.name for p in TEMPLATE_CATALOG]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert not duplicates, f"duplicate TEMPLATE_CATALOG entries: {duplicates}"
