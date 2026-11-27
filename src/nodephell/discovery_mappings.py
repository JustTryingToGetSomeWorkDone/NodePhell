# SPDX-License-Identifier: GPL-3.0-only

"""Load editable discovery hints without importing application code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from .errors import NodePhellError
from .metadata import normalize_name, parse_package_requirement


DEFAULT_MAPPINGS = Path(__file__).resolve().parents[2] / "assets/import-mappings.toml"


@dataclass(frozen=True)
class DiscoveryMappings:
    imports: dict[str, tuple[str, ...]]
    applications: dict[str, tuple[str, ...]]


def load_discovery_mappings(additional: Path | None = None) -> DiscoveryMappings:
    imports: dict[str, tuple[str, ...]] = {}
    applications: dict[str, tuple[str, ...]] = {}
    paths = (DEFAULT_MAPPINGS,) if additional is None else (
        DEFAULT_MAPPINGS, additional.expanduser()
    )
    for path in paths:
        try:
            with path.open("rb") as file:
                data = tomllib.load(file)
        except (OSError, ValueError) as error:
            raise NodePhellError(f"cannot read discovery mappings {path}: {error}") from error
        try:
            if set(data) - {"imports", "applications"}:
                raise ValueError("expected only [imports] and [applications] tables")
            for section, destination in (("imports", imports), ("applications", applications)):
                entries = data.get(section, {})
                if not isinstance(entries, dict):
                    raise ValueError(f"{section} must be a table")
                for name, values in entries.items():
                    valid_name = (
                        name.isidentifier() if section == "imports"
                        else re.fullmatch(r"[a-z][a-z0-9_-]*", name) is not None
                    )
                    if not valid_name:
                        raise ValueError(f"invalid {section} name: {name!r}")
                    if not isinstance(values, list) or not values or not all(
                        isinstance(value, str) and value for value in values
                    ):
                        raise ValueError(f"{section}.{name} must be a nonempty list of names")
                    unique: dict[str, str] = {}
                    for value in values:
                        if section == "imports":
                            requirement = parse_package_requirement(value)
                            if requirement.text != requirement.name:
                                raise ValueError(f"{section}.{name} expects distribution names only")
                            unique.setdefault(normalize_name(value), value)
                        else:
                            if not value.isidentifier():
                                raise ValueError(f"{section}.{name} expects top-level module names")
                            unique.setdefault(value, value)
                    destination[name] = tuple(unique.values())
        except (ValueError, NodePhellError) as error:
            raise NodePhellError(f"invalid discovery mappings {path}: {error}") from error
    return DiscoveryMappings(imports, applications)
