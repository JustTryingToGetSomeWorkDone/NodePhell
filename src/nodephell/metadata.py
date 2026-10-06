# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from .errors import NodePhellError


_EXACT_DEPENDENCY = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\[[^]]+\])?\s*==\s*"
    r"([A-Za-z0-9][A-Za-z0-9._+!-]*)\s*$"
)


@dataclass(frozen=True)
class PackagePin:
    name: str
    version: str


@dataclass(frozen=True)
class Project:
    root: Path
    metadata_file: Path
    requires_python: str | None
    packages: tuple[PackagePin, ...]


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def invocation_start(arguments: list[str], cwd: Path) -> Path:
    """Return the best project-discovery start for Python-style arguments."""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            index += 1
            if index < len(arguments) and arguments[index] != "-":
                return _script_start(arguments[index], cwd)
            return cwd
        if argument in {"-c", "-m"}:
            return cwd
        if argument in {"-W", "-X", "--check-hash-based-pycs"}:
            index += 2
            continue
        if argument.startswith("-") and argument != "-":
            index += 1
            continue
        if argument == "-":
            return cwd
        return _script_start(argument, cwd)
    return cwd


def _script_start(argument: str, cwd: Path) -> Path:
    script = Path(argument).expanduser()
    if not script.is_absolute():
        script = cwd / script
    return script.resolve(strict=False).parent


def discover_project(start: Path) -> Path | None:
    directory = start.expanduser().resolve(strict=False)
    if directory.is_file():
        directory = directory.parent
    while True:
        if (directory / "pylock.toml").is_file() or (
            directory / "pyproject.toml"
        ).is_file():
            return directory
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


def load_project(root: Path) -> Project:
    lock_path = root / "pylock.toml"
    project_path = root / "pyproject.toml"
    project_data = _read_toml(project_path) if project_path.is_file() else {}
    project_table = project_data.get("project", {})
    if not isinstance(project_table, dict):
        raise NodePhellError(f"invalid [project] table in {project_path}")

    if lock_path.is_file():
        lock_data = _read_toml(lock_path)
        if lock_data.get("lock-version") != "1.0":
            raise NodePhellError(
                f"unsupported lock version in {lock_path}; expected 1.0"
            )
        packages = _locked_packages(lock_data, lock_path)
        requires_python = lock_data.get("requires-python")
        if requires_python is None:
            requires_python = project_table.get("requires-python")
        _validate_requires_python(requires_python, lock_path)
        return Project(root, lock_path, requires_python, packages)

    if not project_path.is_file():
        raise NodePhellError(f"no project metadata found below {root}")
    packages = _project_packages(
        project_table.get("dependencies", ()), project_path
    )
    requires_python = project_table.get("requires-python")
    _validate_requires_python(requires_python, project_path)
    return Project(
        root,
        project_path,
        requires_python,
        packages,
    )


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise NodePhellError(f"cannot read {path}: {error}") from error


def _locked_packages(data: dict, path: Path) -> tuple[PackagePin, ...]:
    result: list[PackagePin] = []
    seen: dict[str, str] = {}
    entries = data.get("packages", ())
    if not isinstance(entries, (list, tuple)):
        raise NodePhellError(f"invalid packages list in {path}")
    for package in entries:
        if not isinstance(package, dict):
            raise NodePhellError(f"invalid package entry in {path}")
        if package.get("marker"):
            raise NodePhellError(
                f"environment markers are not supported yet: {path}"
            )
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise NodePhellError(f"unversioned package entry in {path}")
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None and previous != version:
            raise NodePhellError(
                f"{name} has conflicting locked versions in {path}"
            )
        if previous is None:
            seen[normalized] = version
            result.append(PackagePin(name, version))
    return tuple(result)


def _project_packages(dependencies: object, path: Path) -> tuple[PackagePin, ...]:
    if not isinstance(dependencies, (list, tuple)):
        raise NodePhellError(f"invalid project dependencies in {path}")
    result: list[PackagePin] = []
    seen: dict[str, str] = {}
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise NodePhellError(f"invalid dependency in {path}")
        match = _EXACT_DEPENDENCY.fullmatch(dependency)
        if match is None:
            raise NodePhellError(
                f"prototype requires exact dependency pins; found "
                f"{dependency!r} in {path}"
            )
        name, version = match.groups()
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None and previous != version:
            raise NodePhellError(
                f"{name} has conflicting pinned versions in {path}"
            )
        if previous is None:
            seen[normalized] = version
            result.append(PackagePin(name, version))
    return tuple(result)


def _validate_requires_python(value: object, path: Path) -> None:
    if value is not None and not isinstance(value, str):
        raise NodePhellError(f"invalid requires-python value in {path}")
