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
