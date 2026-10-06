# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping

from .errors import NodePhellError
from .metadata import PackagePin, Project, normalize_name
from .runtime import Runtime, data_root, runtime_environment


_INSTALLED_VERSION_PROBE = """
import importlib.metadata as metadata
import json
import sys

versions = {}
for name in sys.argv[1:]:
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        versions[name] = None
print(json.dumps(versions))
"""


@dataclass(frozen=True)
class PackageSelection:
    paths: tuple[Path, ...]
    ordinary_packages: tuple[PackagePin, ...] = ()


def package_store(runtime: Runtime, user_home: Path | None = None) -> Path:
    return data_root(user_home) / runtime.python_store_name / "packages"


def resolve_packages(
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
) -> PackageSelection:
    root = package_store(runtime, user_home)
    projects = _indexed_projects(root)
    paths: list[Path] = []
    ordinary: list[PackagePin] = []
    missing: list[PackagePin] = []
    installed = _ordinary_versions(runtime, list(project.packages))

    for package in project.packages:
        if installed.get(package.name) == package.version:
            ordinary.append(package)
            continue
        project_directory = projects.get(normalize_name(package.name))
        release = (
            project_directory / package.version
            if project_directory is not None
            else None
        )
        if release is not None and release.is_dir():
            paths.append(release.resolve())
        else:
            missing.append(package)
    if missing:
        details = ", ".join(
            f"{package.name}=={package.version}" for package in missing
        )
        raise NodePhellError(
            f"locked packages are unavailable for {runtime.python_store_name}: "
            f"{details}; install them with the NodePhell-aware pip"
        )
    return PackageSelection(tuple(paths), tuple(ordinary))


def package_environment(
    runtime: Runtime,
    selection: PackageSelection,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = runtime_environment(runtime, base)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    if selection.paths:
        environment["PYTHONPATH"] = os.pathsep.join(
            str(path) for path in selection.paths
        )
    return environment


def _indexed_projects(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    result: dict[str, Path] = {}
    try:
        children = tuple(root.iterdir())
    except OSError as error:
        raise NodePhellError(f"cannot inspect package store {root}: {error}") from error
    for child in children:
        if not child.is_dir():
            continue
        normalized = normalize_name(child.name)
        previous = result.get(normalized)
        if previous is not None and previous != child:
            raise NodePhellError(
                f"ambiguous package-store directories: {previous} and {child}"
            )
        result[normalized] = child
    return result


def _ordinary_versions(
    runtime: Runtime,
    packages: list[PackagePin],
) -> dict[str, str | None]:
    if not packages:
        return {}
    environment = runtime_environment(runtime)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    command = [
        str(runtime.executable),
        "-c",
        _INSTALLED_VERSION_PROBE,
        *(package.name for package in packages),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=runtime.executable.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NodePhellError(
            f"cannot inspect packages in {runtime.executable}: {error}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise NodePhellError(
            f"cannot inspect packages in {runtime.executable}: {detail}"
        )
    try:
        versions = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise NodePhellError(
            f"runtime returned invalid package information: {runtime.executable}"
        ) from error
    if not isinstance(versions, dict) or not all(
        isinstance(key, str) and (value is None or isinstance(value, str))
        for key, value in versions.items()
    ):
        raise NodePhellError(
            f"runtime returned invalid package information: {runtime.executable}"
        )
    return versions
