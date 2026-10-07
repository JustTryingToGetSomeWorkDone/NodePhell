# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from functools import cache
import importlib
from pathlib import Path
import pkgutil
import re

from ..errors import NodePhellError
from .base import EmbeddedHost, HostAdapter


_KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
_CAPABILITIES = (
    "accepts_executable",
    "probe",
    "resolve_artifact",
    "validate_artifact",
    "validate_probed_artifact",
    "extract",
    "installed_executable",
    "gui_executable",
    "launch_arguments",
    "augment_environment",
)


@cache
def load_adapter(kind: str) -> HostAdapter:
    if _KIND.fullmatch(kind) is None:
        raise NodePhellError(f"invalid embedded-host adapter kind: {kind!r}")
    module_name = f"{__name__}.{kind}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name:
            raise NodePhellError(
                f"no embedded-host adapter is installed for {kind!r}"
            ) from error
        raise NodePhellError(
            f"cannot load embedded-host adapter {kind!r}: {error}"
        ) from error
    adapter = getattr(module, "ADAPTER", None)
    if adapter is None or adapter.kind != kind:
        raise NodePhellError(f"invalid embedded-host adapter for {kind!r}")
    missing = [
        name
        for name in _CAPABILITIES
        if not callable(getattr(adapter, name, None))
    ]
    if missing:
        raise NodePhellError(
            f"embedded-host adapter {kind!r} lacks: {', '.join(missing)}"
        )
    if not isinstance(getattr(adapter, "display_name", None), str):
        raise NodePhellError(
            f"embedded-host adapter {kind!r} has no display name"
        )
    return adapter


def discover_adapters() -> tuple[HostAdapter, ...]:
    names = sorted(
        module.name
        for module in pkgutil.iter_modules(__path__)
        if module.name != "base" and not module.name.startswith("_")
    )
    return tuple(load_adapter(name) for name in names)


def adapter_for_executable(executable: Path) -> HostAdapter:
    matches = [
        adapter
        for adapter in discover_adapters()
        if adapter.accepts_executable(executable)
    ]
    if not matches:
        raise NodePhellError(
            f"no embedded-host adapter recognizes {executable}; specify --kind"
        )
    if len(matches) > 1:
        kinds = ", ".join(adapter.kind for adapter in matches)
        raise NodePhellError(
            f"multiple embedded-host adapters recognize {executable}: {kinds}; "
            "specify --kind"
        )
    return matches[0]


__all__ = (
    "EmbeddedHost",
    "HostAdapter",
    "adapter_for_executable",
    "discover_adapters",
    "load_adapter",
)
