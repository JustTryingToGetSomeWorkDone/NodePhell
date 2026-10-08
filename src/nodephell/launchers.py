# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from .errors import NodePhellError


_MARKER = "# Managed by NodePhell launcher installer v1"
_APPLICATION_MARKER = "# NodePhell application: "
_COMMAND_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$")
_NAMES = ("nodephell", "python", "python3")


@dataclass(frozen=True)
class LauncherChange:
    installed: tuple[Path, ...] = ()
    unchanged: tuple[Path, ...] = ()
    removed: tuple[Path, ...] = ()
    skipped: tuple[Path, ...] = ()


def launcher_directory(user_home: Path | None = None) -> Path:
    home = Path.home() if user_home is None else user_home
    return home / ".local" / "bin"


def install_launchers(
    user_home: Path | None = None,
    *,
    source_root: Path | None = None,
) -> LauncherChange:
    root = (
        Path(__file__).resolve().parents[2]
        if source_root is None
        else source_root.expanduser().resolve(strict=False)
    )
    source = root / "src"
    if not (source / "nodephell" / "cli.py").is_file():
        raise NodePhellError(f"NodePhell source directory is missing: {source}")
    directory = launcher_directory(user_home)
    desired = {
        name: _launcher_text(source, name == "nodephell") for name in _NAMES
    }
    for name, text in desired.items():
        path = directory / name
        if path.exists() or path.is_symlink():
            current = _managed_text(path)
            if current is None:
                raise NodePhellError(f"refusing to replace existing command: {path}")

    directory.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    unchanged: list[Path] = []
    for name, text in desired.items():
        path = directory / name
        if path.is_file() and not path.is_symlink() and path.read_text() == text:
            unchanged.append(path)
            continue
        _write_launcher(path, text)
        installed.append(path)
    return LauncherChange(tuple(installed), tuple(unchanged))


def install_package_launchers(
    commands: tuple[str, ...],
    user_home: Path | None = None,
    *,
    source_root: Path | None = None,
) -> LauncherChange:
    root = (
        Path(__file__).resolve().parents[2]
        if source_root is None
        else source_root.expanduser().resolve(strict=False)
    )
    source = root / "src"
    directory = launcher_directory(user_home)
    reserved = set(_NAMES)
    conflict = reserved.intersection(commands)
    if conflict:
        raise NodePhellError(
            f"package command conflicts with a NodePhell launcher: "
            f"{sorted(conflict)[0]}"
        )
    desired = {
        command: _package_launcher_text(source, command) for command in commands
    }
    skipped: list[Path] = []
    available: dict[str, str] = {}
    for name, launcher in desired.items():
        path = directory / name
        if path.exists() or path.is_symlink():
            current = _managed_text(path)
            if current is None or _application_name(current) is not None:
                skipped.append(path)
                continue
        available[name] = launcher
    directory.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    unchanged: list[Path] = []
    for name, launcher in available.items():
        path = directory / name
        if path.is_file() and not path.is_symlink() and path.read_text() == launcher:
            unchanged.append(path)
        else:
            _write_launcher(path, launcher)
            installed.append(path)
    return LauncherChange(
        tuple(installed),
        tuple(unchanged),
        skipped=tuple(skipped),
    )


def application_launcher_path(
    name: str,
    user_home: Path | None = None,
) -> Path:
    _validate_command_name(name)
    return launcher_directory(user_home) / name


def check_application_launcher(
    name: str,
    user_home: Path | None = None,
) -> Path:
    """Return the target path when an application launcher may be installed."""
    path = application_launcher_path(name, user_home)
    if not (path.exists() or path.is_symlink()):
        return path
    current = _managed_text(path)
    if current is None or _application_name(current) != name:
        raise NodePhellError(f"refusing to replace existing command: {path}")
    return path


def application_launcher_problem(
    name: str,
    user_home: Path | None = None,
) -> str | None:
    path = application_launcher_path(name, user_home)
    if not path.is_file() or path.is_symlink():
        return f"launcher is missing: {path}"
    current = _managed_text(path)
    if current is None or _application_name(current) != name:
        return f"launcher is not owned by this application: {path}"
    return None


def install_application_launcher(
    name: str,
    user_home: Path | None = None,
    *,
    source_root: Path | None = None,
) -> LauncherChange:
    root = (
        Path(__file__).resolve().parents[2]
        if source_root is None
        else source_root.expanduser().resolve(strict=False)
    )
    source = root / "src"
    if not (source / "nodephell" / "applications.py").is_file():
        raise NodePhellError(f"NodePhell source directory is missing: {source}")
    path = check_application_launcher(name, user_home)
    text = _application_launcher_text(source, name)
    if path.is_file() and not path.is_symlink() and path.read_text() == text:
        return LauncherChange(unchanged=(path,))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_launcher(path, text)
    return LauncherChange(installed=(path,))


def remove_application_launcher(
    name: str,
    user_home: Path | None = None,
) -> LauncherChange:
    path = application_launcher_path(name, user_home)
    if not (path.exists() or path.is_symlink()):
        return LauncherChange()
    current = _managed_text(path)
    if current is None or _application_name(current) != name:
        raise NodePhellError(f"refusing to remove unowned command: {path}")
    try:
        path.unlink()
    except OSError as error:
        raise NodePhellError(f"cannot remove launcher {path}: {error}") from error
    return LauncherChange(removed=(path,))


def uninstall_launchers(user_home: Path | None = None) -> LauncherChange:
    directory = launcher_directory(user_home)
    core_paths = tuple(directory / name for name in _NAMES)
    for path in core_paths:
        if (path.exists() or path.is_symlink()) and _managed_text(path) is None:
            raise NodePhellError(f"refusing to remove unowned command: {path}")
    paths = list(core_paths)
    if directory.is_dir():
        paths.extend(
            path
            for path in directory.iterdir()
            if path not in core_paths and _managed_text(path) is not None
        )
    removed: list[Path] = []
    for path in paths:
        if path.exists() or path.is_symlink():
            try:
                path.unlink()
            except OSError as error:
                raise NodePhellError(
                    f"cannot remove launcher {path}: {error}"
                ) from error
            removed.append(path)
    try:
        directory.rmdir()
    except OSError:
        pass
    return LauncherChange(removed=tuple(removed))


def path_problem(user_home: Path | None = None) -> str | None:
    directory = launcher_directory(user_home).resolve(strict=False)
    command = shutil.which("nodephell")
    if (
        command is not None
        and Path(command).resolve(strict=False) == directory / "nodephell"
    ):
        return None
    if command is None:
        return f"add {directory} to PATH"
    return f"put {directory} before {Path(command).parent} on PATH"


def _launcher_text(source: Path, management: bool) -> str:
    function = "main" if management else "python_main"
    return f'''#!/usr/bin/python3
{_MARKER}
# Source: {source}

import sys

sys.path.insert(0, {str(source)!r})

from nodephell.cli import {function}


raise SystemExit({function}())
'''


def _package_launcher_text(source: Path, command: str) -> str:
    return f'''#!/usr/bin/python3
{_MARKER}
# Source: {source}

import sys

sys.path.insert(0, {str(source)!r})

from nodephell.launcher import command_main


raise SystemExit(command_main({command!r}))
'''


def _application_launcher_text(source: Path, name: str) -> str:
    return f'''#!/usr/bin/python3
{_MARKER}
{_APPLICATION_MARKER}{name}
# Source: {source}

import sys

sys.path.insert(0, {str(source)!r})

from nodephell.applications import app_main


raise SystemExit(app_main({name!r}))
'''


def _application_name(text: str) -> str | None:
    for line in text.splitlines()[:4]:
        if line.startswith(_APPLICATION_MARKER):
            return line.removeprefix(_APPLICATION_MARKER)
    return None


def _validate_command_name(name: str) -> None:
    if name in _NAMES or _COMMAND_NAME.fullmatch(name) is None:
        raise NodePhellError(f"invalid application launcher name: {name!r}")


def _managed_text(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    return text if _MARKER in text.splitlines()[:3] else None


def _write_launcher(path: Path, text: str) -> None:
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}-",
            dir=path.parent,
            text=True,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(text)
        temporary = Path(temporary_name)
        temporary.chmod(
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
            | stat.S_IROTH | stat.S_IXOTH
        )
        temporary.replace(path)
    except OSError as error:
        raise NodePhellError(f"cannot install launcher {path}: {error}") from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
