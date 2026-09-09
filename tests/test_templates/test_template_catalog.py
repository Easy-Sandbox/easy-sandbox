"""Offline validation of the ``examples/templates/`` catalog.

The catalog is deliberately minimal — one ``README.md`` index plus one folder
per template — so the guarantees have to come from tests instead of manifests.
Every test here is **parametrized over all template folders** and runs fully
offline: no network, no docker daemon, no platform API.

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
(d) ``agent.infer.TEMPLATE_CATALOG`` and the on-disk folders agree: no orphan
    folder, no missing folder.
(e) The ``README.md`` index table (the single source of truth for humans)
    matches the YAML files field by field.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml
from pydantic import ValidationError

from serverless_sandbox.agent.infer import TEMPLATE_CATALOG
from serverless_sandbox.models.template import (
    DEFAULT_CAPABILITIES,
    STANDARD_CAPABILITIES,
    CustomCommand,
    SandboxTemplate,
)
from serverless_sandbox.utils.registry import load_template_from_yaml

from .conftest import REQUIRED_TEMPLATE_FILES, REQUIRED_YAML_KEYS

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Catalog ↔ TEMPLATE_CATALOG reconciliation allow-lists
# ---------------------------------------------------------------------------

#: ``TEMPLATE_CATALOG`` entries that are served by the platform's built-in /
#: online image catalog and therefore intentionally have **no** folder here.
PLATFORM_ONLY_TEMPLATES = frozenset({
    "base",
    "code-interpreter",
    "python-data-science",
    "full-stack",
})

#: Folders that exist purely as examples / test fixtures and are deliberately
#: **not** part of the natural-language inference catalog.
EXAMPLE_ONLY_TEMPLATES = frozenset({"python-hello"})

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yaml_path(template_dir: Path) -> Path:
    return template_dir / "template.yaml"


def _load(template_dir: Path) -> SandboxTemplate:
    """Load through the real loader — the same code path ``sbox install`` uses."""
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
    def test_required_file_exists(
        self, template_dir: Path, filename: str
    ) -> None:
        path = template_dir / filename
        assert path.is_file(), (
            f"{template_dir.name}: required file {filename!r} is missing "
            f"(expected at {path})"
        )
        assert path.stat().st_size > 0, (
            f"{template_dir.name}: {filename} exists but is empty"
        )

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
            f"{template_dir.name}: template.yaml is missing required "
            f"key(s): {missing}"
        )

    def test_name_matches_directory(self, template_dir: Path) -> None:
        """Folder name == ``name`` == default install alias (cache lookup key)."""
        assert _load(template_dir).name == template_dir.name

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

    def test_base_non_empty(self, template_dir: Path) -> None:
        assert _load(template_dir).base.strip(), (
            f"{template_dir.name}: base image must not be blank"
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

    def test_dockerfile_base_matches_yaml(self, template_dir: Path) -> None:
        """The hand-written Dockerfile must agree with the YAML ``base``."""
        base = _load(template_dir).base
        dockerfile = (template_dir / "Dockerfile").read_text(encoding="utf-8")
        from_lines = [
            line.strip() for line in dockerfile.splitlines()
            if line.strip().upper().startswith("FROM ")
        ]
        assert from_lines, f"{template_dir.name}: Dockerfile has no FROM line"
        assert from_lines[0] == f"FROM {base}", (
            f"{template_dir.name}: Dockerfile starts with {from_lines[0]!r} but "
            f"template.yaml declares base={base!r}"
        )


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
        """Published templates must spell their capability set out."""
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
            SandboxTemplate.model_validate(
                {"name": "x", "capabilities": ["not-a-capability"]}
            )


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
                f"lowercase identifier-like (used as `sbox run <id> {name}`)"
            )

    def test_cmd_is_non_empty(self, template_dir: Path) -> None:
        for name, cmd in _load(template_dir).custom_commands.items():
            assert cmd.cmd.strip(), (
                f"{template_dir.name}.{name}: 'cmd' must not be blank"
            )

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
                    f"{template_dir.name}.{name}: arg {arg_name!r} must be a "
                    f"lowercase identifier"
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
# (d) TEMPLATE_CATALOG reconciliation
# ---------------------------------------------------------------------------

class TestCatalogCrossReference:
    """``agent.infer.TEMPLATE_CATALOG`` ↔ on-disk folders stay in sync."""

    def test_every_catalog_entry_is_resolvable(self, template_dirs: list[Path]) -> None:
        """No catalog entry points at a folder that does not exist (无缺失)."""
        local = {d.name for d in template_dirs}
        missing = sorted(
            p.name
            for p in TEMPLATE_CATALOG
            if p.name not in local and p.name not in PLATFORM_ONLY_TEMPLATES
        )
        assert not missing, (
            f"TEMPLATE_CATALOG references template(s) with no folder under "
            f"examples/templates/: {missing}. Either add the folder or list the "
            f"name in PLATFORM_ONLY_TEMPLATES."
        )

    def test_no_orphan_folders(self, template_dirs: list[Path]) -> None:
        """No folder is invisible to the inference catalog (无孤儿)."""
        catalog = {p.name for p in TEMPLATE_CATALOG}
        orphans = sorted(
            d.name
            for d in template_dirs
            if d.name not in catalog and d.name not in EXAMPLE_ONLY_TEMPLATES
        )
        assert not orphans, (
            f"template folder(s) not referenced by TEMPLATE_CATALOG: {orphans}. "
            f"Add a TemplateProfile in src/serverless_sandbox/agent/infer.py or "
            f"list the name in EXAMPLE_ONLY_TEMPLATES."
        )

    def test_platform_only_names_have_no_folder(self, template_dirs: list[Path]) -> None:
        """Built-in/platform names must not be shadowed by a local folder."""
        local = {d.name for d in template_dirs}
        shadowed = sorted(local & PLATFORM_ONLY_TEMPLATES)
        assert not shadowed, (
            f"folder(s) {shadowed} shadow platform-provided templates; remove "
            f"them from PLATFORM_ONLY_TEMPLATES or rename the folder"
        )

    def test_example_only_names_are_real_folders(self, template_dirs: list[Path]) -> None:
        local = {d.name for d in template_dirs}
        stale = sorted(EXAMPLE_ONLY_TEMPLATES - local)
        assert not stale, (
            f"EXAMPLE_ONLY_TEMPLATES lists {stale} but no such folder exists"
        )

    def test_mapped_catalog_entries_have_required_files(
        self, template_dirs: list[Path]
    ) -> None:
        """For every catalog entry that maps to a folder, the folder is complete."""
        local = {d.name: d for d in template_dirs}
        for profile in TEMPLATE_CATALOG:
            folder = local.get(profile.name)
            if folder is None:
                continue
            for filename in REQUIRED_TEMPLATE_FILES:
                assert (folder / filename).is_file(), (
                    f"TEMPLATE_CATALOG entry {profile.name!r} maps to {folder} "
                    f"which is missing {filename!r}"
                )

    def test_mapped_resources_match_yaml(self, template_dirs: list[Path]) -> None:
        """Catalog CPU/memory/ports defaults must equal the YAML ``resources``."""
        local = {d.name: d for d in template_dirs}
        for profile in TEMPLATE_CATALOG:
            folder = local.get(profile.name)
            if folder is None:
                continue
            tmpl = _load(folder)
            if tmpl.cpu_count is not None:
                assert tmpl.cpu_count == profile.cpu, (
                    f"{profile.name}: YAML cpu={tmpl.cpu_count} but "
                    f"TEMPLATE_CATALOG cpu={profile.cpu}"
                )
            if tmpl.memory_mb is not None:
                assert tmpl.memory_mb == profile.memory, (
                    f"{profile.name}: YAML memory={tmpl.memory_mb} but "
                    f"TEMPLATE_CATALOG memory={profile.memory}"
                )
            assert list(tmpl.ports) == list(profile.ports), (
                f"{profile.name}: YAML ports={tmpl.ports} but "
                f"TEMPLATE_CATALOG ports={profile.ports}"
            )

    def test_catalog_entries_are_unique(self) -> None:
        """Duplicate catalog names would make inference ambiguous."""
        names = [p.name for p in TEMPLATE_CATALOG]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert not duplicates, f"duplicate TEMPLATE_CATALOG entries: {duplicates}"


# ---------------------------------------------------------------------------
# (e) README index ↔ YAML consistency
# ---------------------------------------------------------------------------

_INDEX_ROW_RE = re.compile(r"^\|\s*\[`[^`]+`\]\(\./")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[`([^`]+)`\]\(\./([^)/]+)/?\)")
_RESOURCES_RE = re.compile(r"(\d+)\s*CPU\s*/\s*(\d+)\s*MB")
_PORTS_RE = re.compile(r"端口[:：]\s*([0-9]+(?:\s*,\s*[0-9]+)*)")
_COMMAND_RE = re.compile(r"`([A-Za-z0-9_-]+)\(([^)]*)\)`")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _parse_index_table(readme: str) -> dict[str, dict]:
    """Parse the 模板总览 table into ``{template_name: row_dict}``."""
    rows: dict[str, dict] = {}
    for line in readme.splitlines():
        if not _INDEX_ROW_RE.match(line):
            continue
        link = _LINK_RE.search(line)
        assert link, f"could not parse template link from row: {line!r}"
        name, href = link.group(1), link.group(2)
        assert name == href, f"row label {name!r} != link target {href!r}"

        cells = _cells(line)
        assert len(cells) == 7, (
            f"index row for {name!r} has {len(cells)} cells, expected 7: {line!r}"
        )
        _, description, keywords, base, resources, capabilities, commands = cells

        res = _RESOURCES_RE.search(resources)
        ports = _PORTS_RE.search(resources)
        rows[name] = {
            "description": description,
            "keywords": _BACKTICK_RE.findall(keywords),
            "base": _BACKTICK_RE.findall(base),
            "cpu": int(res.group(1)) if res else None,
            "memory": int(res.group(2)) if res else None,
            "ports": (
                [int(p) for p in re.split(r"\s*,\s*", ports.group(1))]
                if ports
                else []
            ),
            "capabilities": _BACKTICK_RE.findall(capabilities),
            "commands": _COMMAND_RE.findall(commands),
        }
    return rows


def _parse_capability_matrix(readme: str) -> dict[str, list[str]]:
    """Parse the 'capabilities 分布' table into ``{template_name: capabilities}``."""
    matrix: dict[str, list[str]] = {}
    for line in readme.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) != 2:
            continue
        caps = _BACKTICK_RE.findall(cells[0])
        if not caps or not set(caps) <= STANDARD_CAPABILITIES:
            continue
        for name in _BACKTICK_RE.findall(cells[1]):
            matrix[name] = caps
    return matrix


class TestCatalogReadme:
    """The README is the *only* index — it must not drift from the YAML files."""

    def test_readme_exists(self, catalog_readme: Path) -> None:
        assert catalog_readme.is_file(), (
            f"missing catalog index at {catalog_readme}"
        )

    def test_index_table_covers_every_template(
        self, catalog_readme: Path, template_dirs: list[Path]
    ) -> None:
        rows = _parse_index_table(catalog_readme.read_text(encoding="utf-8"))
        expected = {d.name for d in template_dirs}
        assert set(rows) == expected, (
            f"index table mismatch — missing rows: {sorted(expected - set(rows))}, "
            f"phantom rows: {sorted(set(rows) - expected)}"
        )

    def test_index_table_matches_yaml(
        self, catalog_readme: Path, template_dirs: list[Path]
    ) -> None:
        readme = catalog_readme.read_text(encoding="utf-8")
        rows = _parse_index_table(readme)
        for folder in template_dirs:
            name = folder.name
            assert name in rows, f"{name}: not listed in the README index table"
            row = rows[name]
            tmpl = _load(folder)

            assert row["description"] == tmpl.description, (
                f"{name}: README description {row['description']!r} != YAML "
                f"{tmpl.description!r}"
            )
            assert row["keywords"] == list(tmpl.tags), (
                f"{name}: README keywords {row['keywords']} != YAML tags {tmpl.tags}"
            )
            assert row["base"] == [tmpl.base], (
                f"{name}: README base {row['base']} != YAML base {tmpl.base!r}"
            )
            assert row["cpu"] == tmpl.cpu_count, (
                f"{name}: README cpu {row['cpu']} != YAML resources.cpu "
                f"{tmpl.cpu_count}"
            )
            assert row["memory"] == tmpl.memory_mb, (
                f"{name}: README memory {row['memory']} != YAML resources.memory "
                f"{tmpl.memory_mb}"
            )
            assert row["ports"] == list(tmpl.ports), (
                f"{name}: README ports {row['ports']} != YAML ports {tmpl.ports}"
            )

            expected_caps = (
                list(tmpl.capabilities)
                if tmpl.capabilities is not None
                else sorted(DEFAULT_CAPABILITIES)
            )
            assert row["capabilities"] == expected_caps, (
                f"{name}: README capabilities {row['capabilities']} != YAML "
                f"{expected_caps}"
            )

            expected_cmds = [
                (cmd_name, [
                    a.name + ("*" if a.required else "") for a in cmd.args
                ])
                for cmd_name, cmd in tmpl.custom_commands.items()
            ]
            actual_cmds = [(n, argspec.split()) for n, argspec in row["commands"]]
            assert actual_cmds == expected_cmds, (
                f"{name}: README custom commands {actual_cmds} != YAML "
                f"{expected_cmds}"
            )

    def test_capability_matrix_matches_yaml(
        self, catalog_readme: Path, template_dirs: list[Path]
    ) -> None:
        readme = catalog_readme.read_text(encoding="utf-8")
        matrix = _parse_capability_matrix(readme)
        assert matrix, "could not find the 'capabilities 分布' table in the README"
        for folder in template_dirs:
            name = folder.name
            tmpl = _load(folder)
            expected = (
                list(tmpl.capabilities)
                if tmpl.capabilities is not None
                else sorted(DEFAULT_CAPABILITIES)
            )
            assert name in matrix, (
                f"{name}: missing from the README capability matrix"
            )
            assert matrix[name] == expected, (
                f"{name}: README capability matrix {matrix[name]} != YAML {expected}"
            )

    def test_readme_documents_both_install_flavours(self, catalog_readme: Path) -> None:
        readme = catalog_readme.read_text(encoding="utf-8")
        assert "--registry-type local" in readme
        assert "--registry-type github" in readme
        assert "--registry-url" in readme

    def test_readme_documents_run_vs_exec(self, catalog_readme: Path) -> None:
        readme = catalog_readme.read_text(encoding="utf-8")
        assert "sbox run" in readme
        assert "sbox exec" in readme

    def test_readme_documents_full_schema(self, catalog_readme: Path) -> None:
        """Contribution guide must spell out the capability + command schema."""
        readme = catalog_readme.read_text(encoding="utf-8")
        for token in STANDARD_CAPABILITIES:
            assert f"`{token}`" in readme, f"capability {token!r} not documented"
        for token in (
            "DEFAULT_CAPABILITIES",
            "STANDARD_CAPABILITIES",
            "custom_commands",
            "cmd",
            "cwd",
            "timeout",
            "required",
        ):
            assert token in readme, f"schema keyword {token!r} not documented"
