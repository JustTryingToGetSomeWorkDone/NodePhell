# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .adapters import load_adapter, user_adapter_directory
from .adapters.base import HostAdapter
from .errors import NodePhellError


_KIND = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class PluginChange:
    adapter: HostAdapter
    path: Path
    installed: bool


@dataclass(frozen=True)
class PluginScanIssue:
    source: Path
    message: str


@dataclass(frozen=True)
class PluginScan:
    directory: Path
    changes: tuple[PluginChange, ...]
    issues: tuple[PluginScanIssue, ...]


def user_plugin_directory(user_home: Path | None = None) -> Path:
    if user_home is None:
        from os import environ

        data_home = environ.get("XDG_DATA_HOME")
        shared = (
            Path(data_home).expanduser()
            if data_home
            else Path.home() / ".local/share"
        )
    else:
        shared = user_home.expanduser() / ".local/share"
    return shared / "nodephell" / "plugins"


def add_plugin(
    source: Path,
    user_home: Path | None = None,
) -> PluginChange:
    module = _plugin_module(source)
    kind = module.stem if module.is_file() else module.name
    if _KIND.fullmatch(kind) is None:
        raise NodePhellError(
            f"adapter module name is not a valid plugin kind: {kind!r}"
        )
    directory = user_adapter_directory(user_home)
    target = directory / (f"{kind}.py" if module.is_file() else kind)
    if target.exists() or target.is_symlink():
        try:
            if target.is_symlink() and target.resolve() == module.resolve():
                return PluginChange(load_adapter(kind), target, False)
            if target.is_symlink() and _same_plugin(target.resolve(), module):
                return PluginChange(load_adapter(kind), target, False)
        except OSError:
            pass
        raise NodePhellError(f"adapter plugin destination already exists: {target}")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target.symlink_to(module, target_is_directory=module.is_dir())
        adapter = load_adapter(kind)
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return PluginChange(adapter, target, True)


def scan_plugins(
    directory: Path | None = None,
    user_home: Path | None = None,
) -> PluginScan:
    root = (
        user_plugin_directory(user_home)
        if directory is None
        else directory.expanduser().resolve(strict=False)
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise NodePhellError(
            f"cannot prepare plugin directory {root}: {error}"
        ) from error
    if not root.is_dir():
        raise NodePhellError(f"plugin scan location is not a directory: {root}")

    changes: list[PluginChange] = []
    issues: list[PluginScanIssue] = []
    try:
        entries = tuple(sorted(root.iterdir(), key=lambda path: path.name))
    except OSError as error:
        raise NodePhellError(
            f"cannot read plugin directory {root}: {error}"
        ) from error
    for source in entries:
        if source.name.startswith(".") or not (
            source.is_dir() or (source.is_file() and source.suffix == ".py")
        ):
            continue
        try:
            changes.append(add_plugin(source, user_home))
        except NodePhellError as error:
            issues.append(PluginScanIssue(source, str(error)))
    return PluginScan(root, tuple(changes), tuple(issues))


def remove_plugin(
    kind: str,
    user_home: Path | None = None,
) -> Path:
    if _KIND.fullmatch(kind) is None:
        raise NodePhellError(f"invalid adapter plugin kind: {kind!r}")
    directory = user_adapter_directory(user_home)
    paths = (directory / kind, directory / f"{kind}.py")
    matches = tuple(path for path in paths if path.exists() or path.is_symlink())
    if not matches:
        raise NodePhellError(f"user adapter plugin is not installed: {kind!r}")
    if len(matches) > 1:
        raise NodePhellError(f"multiple user adapter plugins exist for {kind!r}")
    path = matches[0]
    if not path.is_symlink():
        raise NodePhellError(
            f"refusing to remove adapter plugin not linked by NodePhell: {path}"
        )
    try:
        path.unlink()
        directory.rmdir()
    except OSError as error:
        if path.exists() or path.is_symlink():
            raise NodePhellError(
                f"cannot remove adapter plugin {path}: {error}"
            ) from error
    return path


def _plugin_module(source: Path) -> Path:
    path = source.expanduser().resolve(strict=False)
    if path.is_file() and path.suffix == ".py":
        return path
    if path.is_dir() and (path / "__init__.py").is_file():
        return path
    roots = (path / "src", path)
    candidates: dict[Path, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = tuple(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and (child / "__init__.py").is_file():
                candidates[child.resolve()] = child.resolve()
            elif child.is_file() and child.suffix == ".py":
                candidates[child.resolve()] = child.resolve()
    if not candidates:
        raise NodePhellError(f"no adapter module was found under {path}")
    if len(candidates) > 1:
        locations = ", ".join(str(item) for item in sorted(candidates))
        raise NodePhellError(
            f"multiple possible adapter modules were found: {locations}; "
            "pass the intended module directory"
        )
    return next(iter(candidates.values()))


def _same_plugin(first: Path, second: Path) -> bool:
    if first.is_file() or second.is_file():
        if not first.is_file() or not second.is_file():
            return False
        return first.read_bytes() == second.read_bytes()
    if not first.is_dir() or not second.is_dir():
        return False
    return _plugin_tree(first) == _plugin_tree(second)


def _plugin_tree(root: Path) -> dict[Path, bytes]:
    files: dict[Path, bytes] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_file():
            files[relative] = path.read_bytes()
    return files
