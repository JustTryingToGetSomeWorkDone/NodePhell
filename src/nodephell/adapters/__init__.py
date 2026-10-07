# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
from importlib import metadata, util
import os
from pathlib import Path
import re
import sys

from ..errors import NodePhellError
from .base import EmbeddedHost, HostAdapter


_KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
_ENTRY_POINT_GROUP = "nodephell.adapters"
_CAPABILITIES = (
    "accepts_executable", "probe", "resolve_artifact", "validate_artifact",
    "validate_probed_artifact", "extract", "installed_executable",
    "gui_executable", "launch_arguments", "augment_environment",
)


def adapter_directories() -> tuple[Path, ...]:
    configured = tuple(
        Path(item).expanduser()
        for item in os.environ.get("NODEPHELL_ADAPTER_PATH", "").split(os.pathsep)
        if item
    )
    data_home = os.environ.get("XDG_DATA_HOME")
    shared = Path(data_home).expanduser() if data_home else Path.home() / ".local/share"
    return (*configured, shared / "nodephell" / "adapters")


def load_adapter(kind: str) -> HostAdapter:
    _validate_kind(kind)
    dropins = _dropin_paths(kind)
    entry_points = _adapter_entry_points(kind)
    if len(dropins) + len(entry_points) > 1:
        locations = [str(path) for path in dropins]
        locations.extend(_entry_point_label(item) for item in entry_points)
        raise NodePhellError(
            f"multiple external adapters provide {kind!r}: {', '.join(locations)}"
        )
    if dropins:
        adapter = _load_dropin(kind, dropins[0])
    elif entry_points:
        adapter = _load_entry_point(kind, entry_points[0])
    else:
        raise NodePhellError(
            f"no embedded-host adapter is installed for {kind!r}"
        )
    return _validate_adapter(kind, adapter)


def discover_adapters() -> tuple[HostAdapter, ...]:
    return tuple(load_adapter(name) for name in _adapter_kinds())


def adapter_for_executable(executable: Path) -> HostAdapter:
    matches: list[HostAdapter] = []
    failures: list[str] = []
    for kind in _adapter_kinds():
        try:
            adapter = load_adapter(kind)
        except NodePhellError as error:
            failures.append(f"{kind}: {error}")
            continue
        if adapter.accepts_executable(executable):
            matches.append(adapter)
    if not matches:
        detail = f"; unavailable adapters: {'; '.join(failures)}" if failures else ""
        raise NodePhellError(
            f"no embedded-host adapter recognizes {executable}; specify --kind{detail}"
        )
    if len(matches) > 1:
        kinds = ", ".join(adapter.kind for adapter in matches)
        raise NodePhellError(
            f"multiple embedded-host adapters recognize {executable}: {kinds}; "
            "specify --kind"
        )
    return matches[0]


def _adapter_kinds() -> tuple[str, ...]:
    names: set[str] = set()
    for directory in adapter_directories():
        if not directory.is_dir():
            continue
        try:
            entries = tuple(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.stem if entry.is_file() and entry.suffix == ".py" else entry.name
            if _KIND.fullmatch(name) and (
                entry.is_file() or (entry / "__init__.py").is_file()
            ):
                names.add(name)
    names.update(
        item.name for item in _adapter_entry_points() if _KIND.fullmatch(item.name)
    )
    return tuple(sorted(names))


def _dropin_paths(kind: str) -> tuple[Path, ...]:
    found: list[Path] = []
    resolved: set[Path] = set()
    for directory in adapter_directories():
        module = directory / f"{kind}.py"
        package = directory / kind / "__init__.py"
        for candidate in (module, package):
            if not candidate.is_file():
                continue
            identity = candidate.resolve()
            if identity not in resolved:
                resolved.add(identity)
                found.append(candidate)
    return tuple(found)


def _adapter_entry_points(kind: str | None = None) -> tuple[metadata.EntryPoint, ...]:
    selected = metadata.entry_points().select(group=_ENTRY_POINT_GROUP)
    if kind is not None:
        selected = selected.select(name=kind)
    return tuple(selected)


def _load_dropin(kind: str, path: Path) -> object:
    digest = hashlib.sha256(os.fsencode(path.resolve())).hexdigest()[:16]
    module_name = f"_nodephell_adapter_{kind}_{digest}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return getattr(existing, "ADAPTER", None)
    package_paths = [str(path.parent)] if path.name == "__init__.py" else None
    spec = util.spec_from_file_location(
        module_name, path, submodule_search_locations=package_paths
    )
    if spec is None or spec.loader is None:
        raise NodePhellError(f"cannot load embedded-host adapter from {path}")
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        sys.modules.pop(module_name, None)
        raise NodePhellError(
            f"cannot load embedded-host adapter {kind!r} from {path}: {error}"
        ) from error
    return getattr(module, "ADAPTER", None)


def _load_entry_point(kind: str, entry_point: metadata.EntryPoint) -> object:
    try:
        loaded = entry_point.load()
    except Exception as error:
        raise NodePhellError(
            f"cannot load embedded-host adapter {kind!r} from "
            f"{_entry_point_label(entry_point)}: {error}"
        ) from error
    return getattr(loaded, "ADAPTER", loaded)


def _validate_adapter(kind: str, adapter: object) -> HostAdapter:
    if adapter is None or getattr(adapter, "kind", None) != kind:
        raise NodePhellError(f"invalid embedded-host adapter for {kind!r}")
    missing = [
        name for name in _CAPABILITIES if not callable(getattr(adapter, name, None))
    ]
    if missing:
        raise NodePhellError(
            f"embedded-host adapter {kind!r} lacks: {', '.join(missing)}"
        )
    if not isinstance(getattr(adapter, "display_name", None), str):
        raise NodePhellError(f"embedded-host adapter {kind!r} has no display name")
    return adapter  # type: ignore[return-value]


def _validate_kind(kind: str) -> None:
    if _KIND.fullmatch(kind) is None:
        raise NodePhellError(f"invalid embedded-host adapter kind: {kind!r}")


def _entry_point_label(entry_point: metadata.EntryPoint) -> str:
    distribution = entry_point.dist
    return distribution.name if distribution is not None else entry_point.value


__all__ = (
    "EmbeddedHost", "HostAdapter", "adapter_directories",
    "adapter_for_executable", "discover_adapters", "load_adapter",
)
