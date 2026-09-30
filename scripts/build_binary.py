#!/usr/bin/env python3
"""Build a standalone ``ebx`` binary with PyInstaller.

Produces a single-file executable that bundles the Python runtime, the
``easy_sandbox`` package (including every lazily-imported CLI subcommand),
and the core runtime dependencies (pydantic, httpx, websockets, click, ...).

Output naming convention::

    ebx-{version}-{platform}-{arch}[.exe]

where ``platform`` is one of ``linux`` / ``darwin`` / ``windows`` and
``arch`` is one of ``x64`` / ``arm64``. Both are detected from the current
interpreter, so the produced binary always matches the Python that built it
(e.g. an x86_64 Python on macOS produces a darwin-x64 binary).

Usage::

    python scripts/build_binary.py

Prerequisites::

    pip install -e ".[binary]"   # CLI runtime deps + PyInstaller

Notes on PyInstaller specifics:

* ``easy_sandbox.cli.main.LazyGroup`` resolves subcommands at runtime via
  ``importlib.import_module`` — invisible to static analysis. This is
  handled by ``--collect-all easy_sandbox``.
* Several optional imports live inside ``try/except ImportError`` blocks
  (rich, yaml, questionary, orjson, ...). They are declared as hidden
  imports and bundled only when present in the build environment.
* Native extensions (pydantic-core's Rust ``.so``/``.pyd``, PyYAML's C
  accelerator, orjson's Rust core) are picked up automatically by
  PyInstaller's dependency analysis for whatever wheels are installed.

After the build, a smoke test runs ``ebx --version`` against the produced
binary and the SHA256 digest is printed for verification.
"""

from __future__ import annotations

import hashlib
import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist" / "binary"
BUILD_DIR = REPO_ROOT / "build" / "pyinstaller"
ENTRY_SCRIPT = BUILD_DIR / "ebx_entry.py"

# Entry point passed to PyInstaller. A tiny launcher (instead of freezing
# ``easy_sandbox.cli.main`` directly) keeps ``main.py`` a regular importable
# module inside the frozen bundle and avoids a duplicated ``__main__`` copy.
ENTRY_TEMPLATE = '''\
"""PyInstaller entry point for the standalone ``ebx`` binary."""

from easy_sandbox.cli.main import main

if __name__ == "__main__":
    main()
'''

# Modules that MUST be bundled. Some of them are imported lazily (inside
# functions or try/except blocks) and may be missed by static analysis.
REQUIRED_HIDDEN_IMPORTS = [
    "pydantic",
    "pydantic_core",
    "httpx",
    "click",
    "websockets",
    "dotenv",
]

# Optional extras — bundled only when installed in the build environment.
OPTIONAL_HIDDEN_IMPORTS = [
    "rich",
    "yaml",
    "questionary",
    "orjson",
    "tomli",
    "filelock",
]

ARCH_MAP = {
    "x86_64": "x64",
    "amd64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def detect_platform() -> str:
    """Return the normalized platform name (linux / darwin / windows)."""
    system = platform.system().lower()
    if system not in ("linux", "darwin", "windows"):
        raise SystemExit(f"error: unsupported platform: {system!r}")
    return system


def detect_arch() -> str:
    """Return the normalized architecture name (x64 / arm64)."""
    machine = platform.machine().lower()
    arch = ARCH_MAP.get(machine)
    if arch is None:
        raise SystemExit(f"error: unsupported architecture: {machine!r}")
    return arch


def get_version() -> str:
    """Return the package version from ``easy_sandbox._version``."""
    from easy_sandbox._version import __version__

    return __version__


def resolve_hidden_imports() -> list[str]:
    """Filter the hidden-import list against the current environment.

    Required modules must be importable — a missing one aborts the build.
    Optional modules (extras not installed in this environment) are skipped
    with a notice.
    """
    resolved: list[str] = []
    for module in REQUIRED_HIDDEN_IMPORTS:
        if importlib.util.find_spec(module) is None:
            raise SystemExit(
                f"error: required module {module!r} is not installed. "
                'Run: pip install -e ".[binary]"'
            )
        resolved.append(module)
    for module in OPTIONAL_HIDDEN_IMPORTS:
        if importlib.util.find_spec(module) is None:
            print(f"note: optional module {module!r} not installed — skipping")
            continue
        resolved.append(module)
    return resolved


def write_entry_script() -> Path:
    """Write the PyInstaller entry-point launcher and return its path."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ENTRY_SCRIPT.write_text(ENTRY_TEMPLATE, encoding="utf-8")
    return ENTRY_SCRIPT


def run_pyinstaller(entry: Path, hidden_imports: list[str]) -> None:
    """Invoke PyInstaller to build the onefile binary."""
    workpath = BUILD_DIR / "work"
    # Clean the work directory ourselves instead of passing ``--clean``:
    # PyInstaller's own cleanup also wipes the shared global cache and has
    # been observed to fail on macOS with ``Operation not permitted`` when
    # unlinking previously-copied native extensions (e.g. orjson's .so).
    # Keeping the work directory inside the project also makes the build
    # self-contained and fully removable via ``make clean``.
    if workpath.exists():
        shutil.rmtree(workpath, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "ebx",
        # LazyGroup loads subcommands via importlib.import_module at
        # runtime; collect the whole package (modules + data files).
        "--collect-all",
        "easy_sandbox",
        # ``cli`` uses ``click.version_option(package_name="easy-sandbox")``,
        # which resolves the version via importlib.metadata at runtime —
        # the dist-info metadata must be present inside the bundle.
        "--copy-metadata",
        "easy-sandbox",
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(workpath),
        "--specpath",
        str(BUILD_DIR),
    ]
    for module in hidden_imports:
        cmd.extend(["--hidden-import", module])
    cmd.append(str(entry))

    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def _run_version(binary: Path) -> subprocess.CompletedProcess[str]:
    """Run ``ebx --version`` once and capture the result."""
    return subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def smoke_test(binary: Path, version: str) -> None:
    """Run ``ebx --version`` against the produced binary."""
    print(f"\nsmoke test: {binary} --version")
    result = _run_version(binary)
    if result.returncode != 0:
        # Transient launch failures have been observed on macOS: a freshly
        # built ad-hoc signed onefile binary may be SIGKILLed on its very
        # first launch while Gatekeeper evaluates the new signature, and
        # restricted sandboxes may intermittently reject the bootloader's
        # sync semaphore. Real defects reproduce consistently, so a single
        # retry does not mask them.
        print(f"  first attempt failed (exit code {result.returncode}); retrying once...")
        result = _run_version(binary)
    output = (result.stdout + result.stderr).strip()
    print(f"  exit code: {result.returncode}")
    print(f"  output:    {output}")
    if result.returncode != 0:
        raise SystemExit(f"error: smoke test failed with exit code {result.returncode}")
    if version not in output:
        raise SystemExit(f"error: smoke test output does not contain version {version!r}")


def main() -> None:
    """Build, rename, and smoke-test the standalone ebx binary."""
    system = detect_platform()
    arch = detect_arch()
    version = get_version()

    exe_suffix = ".exe" if system == "windows" else ""
    final_path = DIST_DIR / f"ebx-{version}-{system}-{arch}{exe_suffix}"

    print(f"Building ebx {version} for {system}-{arch}")
    print(f"Output: {final_path}\n")

    hidden_imports = resolve_hidden_imports()
    print(f"hidden imports: {', '.join(hidden_imports)}\n")

    entry = write_entry_script()
    run_pyinstaller(entry, hidden_imports)

    built_path = DIST_DIR / f"ebx{exe_suffix}"
    if not built_path.is_file():
        raise SystemExit(f"error: PyInstaller did not produce {built_path}")

    if final_path.exists():
        final_path.unlink()
    shutil.move(built_path, final_path)

    smoke_test(final_path, version)

    size_mb = final_path.stat().st_size / (1024 * 1024)
    digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
    print(f"\nBuild succeeded: {final_path} ({size_mb:.1f} MB)")
    print(f"SHA256: {digest}")


if __name__ == "__main__":
    main()
