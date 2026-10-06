# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
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


@dataclass(frozen=True)
class PackageInspection:
    selection: PackageSelection
    missing_packages: tuple[PackagePin, ...]


def package_store(runtime: Runtime, user_home: Path | None = None) -> Path:
    return data_root(user_home) / runtime.python_store_name / "packages"


def composition_store(runtime: Runtime, user_home: Path | None = None) -> Path:
    return data_root(user_home) / runtime.python_store_name / "compositions"


def resolve_packages(
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
) -> PackageSelection:
    inspection = inspect_packages(project, runtime, user_home)
    missing = inspection.missing_packages
    if missing:
        details = ", ".join(
            f"{package.name}=={package.version}" for package in missing
        )
        raise NodePhellError(
            f"locked packages are unavailable for {runtime.python_store_name}: "
            f"{details}; run 'nodephell install'"
        )
    return inspection.selection


def inspect_packages(
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
) -> PackageInspection:
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
        if release is not None and release_matches(package, release):
            paths.append(release.resolve())
        else:
            missing.append(package)
    if paths:
        paths = [_compose_releases(tuple(paths), runtime, user_home)]
    return PackageInspection(
        PackageSelection(tuple(paths), tuple(ordinary)),
        tuple(missing),
    )


def stored_release_path(
    package: PackagePin,
    runtime: Runtime,
    user_home: Path | None = None,
) -> Path:
    root = package_store(runtime, user_home)
    project = _indexed_projects(root).get(normalize_name(package.name))
    if project is None:
        project = root / normalize_name(package.name)
    return project / package.version


def release_matches(package: PackagePin, release: Path) -> bool:
    if not release.is_dir():
        return False
    try:
        metadata_files = tuple(release.glob("*.dist-info/METADATA"))
    except OSError:
        return False
    for metadata_file in metadata_files:
        try:
            with metadata_file.open("rb") as file:
                metadata = BytesParser(policy=compat32).parse(file, headersonly=True)
        except OSError:
            continue
        name = metadata.get("Name")
        version = metadata.get("Version")
        if (
            isinstance(name, str)
            and normalize_name(name) == normalize_name(package.name)
            and version == package.version
        ):
            return True
    return False


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
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _compose_releases(
    releases: tuple[Path, ...],
    runtime: Runtime,
    user_home: Path | None,
) -> Path:
    digest = _composition_digest(releases)
    target = composition_store(runtime, user_home) / digest
    if target.is_dir():
        return target.resolve()

    root = target.parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{digest}-", dir=root))
    except OSError as error:
        raise NodePhellError(
            f"cannot create package composition for {runtime.python_store_name}: "
            f"{error}"
        ) from error

    try:
        for release in releases:
            _merge_release(release, staging)
        try:
            staging.rename(target)
        except FileExistsError:
            if target.is_dir():
                return target.resolve()
            raise NodePhellError(
                f"package composition path is not a directory: {target}"
            )
        except OSError as error:
            raise NodePhellError(
                f"cannot commit package composition {target}: {error}"
            ) from error
        return target.resolve()
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _composition_digest(releases: tuple[Path, ...]) -> str:
    hasher = hashlib.sha256()
    for release in releases:
        resolved = release.resolve()
        hasher.update(str(resolved).encode("utf-8"))
        hasher.update(b"\0")
        try:
            stat = resolved.stat()
        except OSError as error:
            raise NodePhellError(
                f"cannot inspect package release {resolved}: {error}"
            ) from error
        hasher.update(str(stat.st_mtime_ns).encode("ascii"))
        hasher.update(b"\0")
    return hasher.hexdigest()[:32]


def _merge_release(release: Path, destination: Path) -> None:
    try:
        children = tuple(release.iterdir())
    except OSError as error:
        raise NodePhellError(
            f"cannot inspect package release {release}: {error}"
        ) from error
    for child in children:
        _merge_path(child, destination / child.name)


def _merge_path(source: Path, destination: Path) -> None:
    if source.name == "__pycache__":
        return
    if source.is_dir() and not source.is_symlink():
        if destination.exists():
            if not destination.is_dir() or destination.is_symlink():
                raise NodePhellError(
                    f"package composition conflict: {destination}"
                )
        else:
            try:
                destination.mkdir()
            except OSError as error:
                raise NodePhellError(
                    f"cannot create package composition directory "
                    f"{destination}: {error}"
                ) from error
        try:
            children = tuple(source.iterdir())
        except OSError as error:
            raise NodePhellError(
                f"cannot inspect package path {source}: {error}"
            ) from error
        for child in children:
            _merge_path(child, destination / child.name)
        return

    if destination.exists() or destination.is_symlink():
        if _same_file(source, destination):
            return
        raise NodePhellError(f"package composition conflict: {destination}")
    try:
        destination.symlink_to(source.resolve())
    except OSError as error:
        raise NodePhellError(
            f"cannot add package composition link {destination}: {error}"
        ) from error


def _same_file(left: Path, right: Path) -> bool:
    try:
        left = left.resolve(strict=True)
        right = right.resolve(strict=True)
        if left.samefile(right):
            return True
        if not left.is_file() or not right.is_file():
            return False
        if left.stat().st_size != right.stat().st_size:
            return False
        with left.open("rb") as left_file, right.open("rb") as right_file:
            while True:
                left_chunk = left_file.read(1024 * 1024)
                if left_chunk != right_file.read(1024 * 1024):
                    return False
                if not left_chunk:
                    return True
    except OSError:
        return False


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
