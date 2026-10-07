# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .errors import NodePhellError
from .locking import exclusive_store_lock
from .metadata import Project
from .runtime import Runtime, data_root
from .store import (
    PackageSelection,
    release_matches,
    stored_release_path,
)


_REFERENCE_VERSION = 1
_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class ProjectReference:
    manifest: Path
    project_root: Path
    metadata_file: Path
    lock_sha256: str
    runtime_identity: tuple[str, str, str, str]
    releases: tuple[Path, ...]
    compositions: tuple[Path, ...]


@dataclass(frozen=True)
class ReferenceIssue:
    path: Path
    message: str


def project_registry(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "projects"


def remove_project_reference(
    project_root: Path,
    user_home: Path | None = None,
) -> Path:
    root = project_root.expanduser().resolve(strict=False)
    registry = project_registry(user_home)
    manifest = registry / (_project_key(root) + ".json")
    with exclusive_store_lock(manifest, user_home) as acquired:
        assert acquired
        if not manifest.is_file() or manifest.is_symlink():
            raise NodePhellError(f"project is not registered: {root}")
        try:
            manifest.unlink()
        except OSError as error:
            raise NodePhellError(
                f"cannot remove project record {manifest}: {error}"
            ) from error
    try:
        registry.rmdir()
    except OSError:
        pass
    return root


def move_project_reference(
    old_root: Path,
    new_root: Path,
    user_home: Path | None = None,
) -> ProjectReference:
    old = old_root.expanduser().resolve(strict=False)
    try:
        new = new_root.expanduser().resolve(strict=True)
    except OSError as error:
        raise NodePhellError(
            f"new project location is unavailable: {new_root}"
        ) from error
    if not new.is_dir():
        raise NodePhellError(f"new project location is not a directory: {new}")
    registry = project_registry(user_home)
    old_manifest = registry / (_project_key(old) + ".json")
    new_manifest = registry / (_project_key(new) + ".json")
    if old_manifest == new_manifest:
        raise NodePhellError(f"project is already registered at {new}")
    with exclusive_store_lock(old_manifest, user_home) as acquired:
        assert acquired
        if not old_manifest.is_file() or old_manifest.is_symlink():
            raise NodePhellError(f"project is not registered: {old}")
        try:
            with old_manifest.open(encoding="utf-8") as file:
                data = json.load(file)
            reference = _reference_from_data(old_manifest, data, user_home)
        except (OSError, json.JSONDecodeError, NodePhellError) as error:
            raise NodePhellError(
                f"cannot read project registration for {old}: {error}"
            ) from error
        new_lock = new / "pylock.toml"
        if not new_lock.is_file() or _file_sha256(new_lock) != reference.lock_sha256:
            raise NodePhellError(
                f"new project lock does not match the registration for {old}"
            )
        if new_manifest.exists() or new_manifest.is_symlink():
            raise NodePhellError(f"project is already registered: {new}")
        data["project"] = str(new)
        data["lock"]["path"] = str(new_lock)
        staging: Path | None = None
        try:
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{new_manifest.stem}-", suffix=".json", dir=registry
            )
            os.close(descriptor)
            staging = Path(temporary)
            staging.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            staging.replace(new_manifest)
            old_manifest.unlink()
        except OSError as error:
            raise NodePhellError(
                f"cannot move project registration: {error}"
            ) from error
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    pass
    return _reference_from_data(new_manifest, data, user_home)


def record_project_reference(
    project: Project,
    runtime: Runtime,
    selection: PackageSelection,
    user_home: Path | None = None,
) -> ProjectReference:
    try:
        root = project.root.resolve(strict=True)
        metadata_file = project.metadata_file.resolve(strict=True)
    except OSError as error:
        raise NodePhellError(
            f"cannot inspect installed project {project.root}: {error}"
        ) from error
    if metadata_file.name != "pylock.toml" or metadata_file.parent != root:
        raise NodePhellError(
            "a project reference can be recorded only from its completed pylock.toml"
        )

    releases, compositions = _selection_paths(
        project,
        runtime,
        selection,
        user_home,
        verify=True,
    )
    registry = project_registry(user_home)
    manifest = registry / (_project_key(root) + ".json")
    data = {
        "version": _REFERENCE_VERSION,
        "project": str(root),
        "lock": {
            "path": str(metadata_file),
            "sha256": _file_sha256(metadata_file),
        },
        "runtime": {
            "implementation": runtime.implementation,
            "version": runtime.version,
            "abi": runtime.abi,
            "platform": runtime.platform,
        },
        "releases": [str(path) for path in releases],
        "compositions": [str(path) for path in compositions],
    }

    with exclusive_store_lock(manifest, user_home) as acquired:
        assert acquired
        staging: Path | None = None
        try:
            registry.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{manifest.stem}-",
                suffix=".json",
                dir=registry,
            )
            os.close(descriptor)
            staging = Path(temporary)
            staging.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            staging.replace(manifest)
        except OSError as error:
            raise NodePhellError(
                f"cannot record project use in {manifest}: {error}"
            ) from error
        finally:
            if staging is not None:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    pass

    return ProjectReference(
        manifest,
        root,
        metadata_file,
        data["lock"]["sha256"],
        _runtime_identity(runtime),
        releases,
        compositions,
    )


def ensure_project_reference(
    project: Project,
    runtime: Runtime,
    selection: PackageSelection,
    user_home: Path | None = None,
) -> ProjectReference:
    """Return the current record, creating it only when needed."""
    try:
        root = project.root.resolve(strict=True)
        manifest = project_registry(user_home) / (_project_key(root) + ".json")
        with manifest.open(encoding="utf-8") as file:
            reference = _reference_from_data(manifest, json.load(file), user_home)
        releases, compositions = _selection_paths(
            project,
            runtime,
            selection,
            user_home,
            verify=False,
        )
        if (
            reference_problem(reference) is None
            and reference.runtime_identity == _runtime_identity(runtime)
            and reference.releases == releases
            and reference.compositions == compositions
        ):
            return reference
    except (OSError, json.JSONDecodeError, NodePhellError):
        pass
    return record_project_reference(project, runtime, selection, user_home)


def inspect_project_references(
    user_home: Path | None = None,
) -> tuple[tuple[ProjectReference, ...], tuple[ReferenceIssue, ...]]:
    registry = project_registry(user_home)
    if not registry.exists():
        return (), ()
    if not registry.is_dir() or registry.is_symlink():
        return (), (ReferenceIssue(registry, "project registry is not a directory"),)

    references: list[ProjectReference] = []
    issues: list[ReferenceIssue] = []
    try:
        entries = tuple(sorted(registry.iterdir(), key=lambda path: path.name))
    except OSError as error:
        return (), (ReferenceIssue(registry, f"cannot read project registry: {error}"),)
    for manifest in entries:
        if (
            manifest.name.startswith(".")
            or manifest.suffix != ".json"
            or not manifest.is_file()
            or manifest.is_symlink()
        ):
            issues.append(ReferenceIssue(manifest, "unrecognized project record"))
            continue
        try:
            with manifest.open(encoding="utf-8") as file:
                data = json.load(file)
            references.append(_reference_from_data(manifest, data, user_home))
        except (OSError, json.JSONDecodeError, NodePhellError) as error:
            issues.append(ReferenceIssue(manifest, str(error)))
    return tuple(references), tuple(issues)


def reference_problem(reference: ProjectReference) -> tuple[str, bool] | None:
    """Return a problem and whether the record is safely obsolete."""
    if not reference.project_root.is_dir():
        return "registered project location is unavailable", False
    if not reference.metadata_file.is_file():
        return "registered project lock is unavailable", False
    try:
        digest = _file_sha256(reference.metadata_file)
    except NodePhellError as error:
        return str(error), False
    if digest != reference.lock_sha256:
        return "project lock changed; run 'nodephell install' in that project", False
    return None


def _reference_from_data(
    manifest: Path,
    data: object,
    user_home: Path | None,
) -> ProjectReference:
    if not isinstance(data, dict) or set(data) != {
        "version",
        "project",
        "lock",
        "runtime",
        "releases",
        "compositions",
    }:
        raise NodePhellError("project record has an unsupported format")
    lock = data.get("lock")
    runtime = data.get("runtime")
    if (
        data.get("version") != _REFERENCE_VERSION
        or not isinstance(data.get("project"), str)
        or not isinstance(lock, dict)
        or set(lock) != {"path", "sha256"}
        or not isinstance(lock.get("path"), str)
        or not isinstance(lock.get("sha256"), str)
        or len(lock["sha256"]) != 64
        or any(character not in _HEX_DIGITS for character in lock["sha256"])
        or not isinstance(runtime, dict)
        or set(runtime) != {"implementation", "version", "abi", "platform"}
        or not all(isinstance(runtime.get(key), str) for key in runtime)
        or not isinstance(data.get("releases"), list)
        or not all(isinstance(path, str) for path in data["releases"])
        or not isinstance(data.get("compositions"), list)
        or not all(isinstance(path, str) for path in data["compositions"])
    ):
        raise NodePhellError("project record is incomplete")

    root = Path(data["project"])
    metadata_file = Path(lock["path"])
    releases = tuple(Path(path) for path in data["releases"])
    compositions = tuple(Path(path) for path in data["compositions"])
    store_root = data_root(user_home).resolve(strict=False)
    if (
        not root.is_absolute()
        or manifest.name != _project_key(root) + ".json"
        or not metadata_file.is_absolute()
        or metadata_file.parent != root
        or metadata_file.name != "pylock.toml"
        or any(
            not path.is_absolute() or not path.is_relative_to(store_root)
            for path in (*releases, *compositions)
        )
        or len(set(releases)) != len(releases)
        or len(set(compositions)) != len(compositions)
    ):
        raise NodePhellError("project record contains invalid paths")
    return ProjectReference(
        manifest,
        root,
        metadata_file,
        lock["sha256"],
        (
            runtime["implementation"],
            runtime["version"],
            runtime["abi"],
            runtime["platform"],
        ),
        releases,
        compositions,
    )


def _project_key(root: Path) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip(".-")
    digest = hashlib.sha256(os.fsencode(os.path.abspath(root))).hexdigest()
    return f"{readable or 'project'}-{digest}"


def _runtime_identity(runtime: Runtime) -> tuple[str, str, str, str]:
    return (
        runtime.implementation,
        runtime.version,
        runtime.abi,
        runtime.platform,
    )


def _selection_paths(
    project: Project,
    runtime: Runtime,
    selection: PackageSelection,
    user_home: Path | None,
    *,
    verify: bool,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    unmanaged = set(selection.ordinary_packages) | set(selection.external_packages)
    releases: list[Path] = []
    for package in project.packages:
        if package in unmanaged:
            continue
        release = stored_release_path(package, runtime, user_home)
        if verify and not release_matches(package, release, runtime):
            raise NodePhellError(
                f"cannot register missing shared release "
                f"{package.name}=={package.version}"
            )
        releases.append(release.parent.resolve(strict=True))
    compositions = tuple(
        sorted(
            (path.resolve(strict=True) for path in selection.paths),
            key=os.fspath,
        )
    )
    return tuple(sorted(set(releases), key=os.fspath)), compositions


def _file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                hasher.update(chunk)
    except OSError as error:
        raise NodePhellError(f"cannot read project lock {path}: {error}") from error
    return hasher.hexdigest()
