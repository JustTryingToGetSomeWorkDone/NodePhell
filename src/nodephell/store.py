# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import csv
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Mapping

from .errors import NodePhellError
from .locking import exclusive_store_lock
from .metadata import PackageArtifact, PackagePin, Project, normalize_name
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
_STORE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_MANIFEST = "nodephell.json"
COMPOSITION_MANIFEST = ".nodephell-composition.json"


@dataclass(frozen=True)
class PackageSelection:
    paths: tuple[Path, ...]
    ordinary_packages: tuple[PackagePin, ...] = ()
    external_packages: tuple[PackagePin, ...] = ()


@dataclass(frozen=True)
class PackageInspection:
    selection: PackageSelection
    missing_packages: tuple[PackagePin, ...]


@dataclass(frozen=True)
class _ExternalRelease:
    name: str
    version: str
    root: Path
    files: tuple[Path, ...]
    identity: str


def package_store(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "packages"


def composition_store(runtime: Runtime, user_home: Path | None = None) -> Path:
    return data_root(user_home) / runtime.python_store_name / "compositions"


def resolve_packages(
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
    external_roots: tuple[Path, ...] = (),
    include_ordinary: bool = True,
) -> PackageSelection:
    inspection = inspect_packages(
        project,
        runtime,
        user_home,
        external_roots,
        include_ordinary,
    )
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
    external_roots: tuple[Path, ...] = (),
    include_ordinary: bool = True,
) -> PackageInspection:
    releases: list[Path] = []
    external_releases: list[_ExternalRelease] = []
    ordinary: list[PackagePin] = []
    external: list[PackagePin] = []
    missing: list[PackagePin] = []
    external_pins = _external_release_pins(user_home) if external_roots else {}
    installed = (
        _ordinary_versions(runtime, list(project.packages))
        if include_ordinary
        else {}
    )

    for package in project.packages:
        package_artifact(package)
        if installed.get(package.name) == package.version:
            ordinary.append(package)
            continue
        release = stored_release_path(package, runtime, user_home)
        if release_matches(package, release, runtime):
            releases.append(release.resolve())
            continue
        external_release = _find_external_release(
            package,
            external_roots,
            external_pins,
        )
        if external_release is not None:
            external_releases.append(external_release)
            external.append(package)
            continue
        missing.append(package)
    paths: tuple[Path, ...] = ()
    if releases or external_releases:
        paths = (
            _compose_package_sources(
                tuple(releases),
                tuple(external_releases),
                runtime,
                user_home,
            ),
        )
    return PackageInspection(
        PackageSelection(paths, tuple(ordinary), tuple(external)),
        tuple(missing),
    )


def _find_external_release(
    package: PackagePin,
    roots: tuple[Path, ...],
    existing: dict[tuple[str, str, str], set[str]],
) -> _ExternalRelease | None:
    """Find an exact installed distribution without taking ownership of it."""
    for raw_root in roots:
        try:
            root = raw_root.expanduser().resolve(strict=True)
        except OSError:
            continue
        if not root.is_dir() or root.is_symlink():
            continue
        try:
            metadata_files = tuple(sorted(root.glob("*.dist-info/METADATA")))
        except OSError:
            continue
        for metadata_file in metadata_files:
            try:
                with metadata_file.open("rb") as file:
                    metadata_bytes = file.read()
                metadata = BytesParser(policy=compat32).parsebytes(
                    metadata_bytes,
                    headersonly=True,
                )
            except OSError:
                continue
            name = metadata.get("Name")
            version = metadata.get("Version")
            if (
                not isinstance(name, str)
                or normalize_name(name) != normalize_name(package.name)
                or version != package.version
            ):
                continue
            record = metadata_file.with_name("RECORD")
            external = _external_release_from_record(
                normalize_name(package.name),
                package.version,
                root,
                metadata_file,
                metadata_bytes,
                record,
            )
            if external is not None and existing.get(
                (external.name, external.version, str(external.root)),
                {external.identity},
            ) == {external.identity}:
                return external
    return None


def _external_release_from_record(
    name: str,
    version: str,
    root: Path,
    metadata_file: Path,
    metadata_bytes: bytes,
    record: Path,
) -> _ExternalRelease | None:
    try:
        record_bytes = record.read_bytes()
        rows = tuple(csv.reader(record_bytes.decode("utf-8").splitlines()))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None

    relative_files: list[Path] = []
    fingerprints: list[tuple[str, str, int, int, int]] = []
    seen: set[Path] = set()
    for row in rows:
        if not row or not row[0]:
            return None
        relative = Path(row[0])
        if relative.is_absolute() or ".." in relative.parts:
            # Console scripts may deliberately live outside site-packages. They
            # are not import files and are never borrowed by NodePhell.
            continue
        if "__pycache__" in relative.parts or relative in seen:
            continue
        source = root / relative
        try:
            resolved = source.resolve(strict=True)
            link_details = source.lstat()
            details = source.stat()
        except OSError:
            return None
        if not resolved.is_relative_to(root) or not (
            stat.S_ISREG(link_details.st_mode)
            or stat.S_ISLNK(link_details.st_mode)
        ):
            return None
        seen.add(relative)
        relative_files.append(relative)
        fingerprints.append(
            (
                relative.as_posix(),
                resolved.relative_to(root).as_posix(),
                details.st_size,
                details.st_mtime_ns,
                stat.S_IMODE(details.st_mode),
            )
        )
    if not relative_files or metadata_file.relative_to(root) not in seen:
        return None

    hasher = hashlib.sha256()
    hasher.update(str(root).encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(metadata_bytes)
    hasher.update(b"\0")
    hasher.update(record_bytes)
    hasher.update(b"\0")
    hasher.update(
        json.dumps(fingerprints, separators=(",", ":")).encode("utf-8")
    )
    return _ExternalRelease(
        name,
        version,
        root,
        tuple(sorted(relative_files, key=os.fspath)),
        hasher.hexdigest(),
    )


def _external_release_pins(
    user_home: Path | None,
) -> dict[tuple[str, str, str], set[str]]:
    pins: dict[tuple[str, str, str], set[str]] = {}
    root = data_root(user_home)
    if not root.is_dir():
        return pins
    for manifest in root.glob(f"python*/compositions/*/{COMPOSITION_MANIFEST}"):
        try:
            with manifest.open(encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            continue
        records = data.get("external_releases") if isinstance(data, dict) else None
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            name = record.get("name")
            version = record.get("version")
            provider = record.get("root")
            identity = record.get("identity")
            if not all(
                isinstance(value, str)
                for value in (name, version, provider, identity)
            ):
                continue
            pins.setdefault((name, version, provider), set()).add(identity)
    return pins


def stored_release_path(
    package: PackagePin,
    runtime: Runtime,
    user_home: Path | None = None,
) -> Path:
    artifact = package_artifact(package)
    root = package_store(user_home)
    project = _indexed_projects(root).get(normalize_name(package.name))
    if project is None:
        project = root / normalize_name(package.name)
    release = project / package.version / artifact.name / artifact.sha256
    if artifact.kind == "sdist":
        release = (
            release
            / "built-for"
            / runtime.python_store_name
            / _store_component(runtime.abi or "unknown-abi", "Python ABI")
        )
    return release / "root"


def package_artifact(package: PackagePin) -> PackageArtifact:
    if len(package.artifacts) != 1:
        raise NodePhellError(
            f"{package.name}=={package.version} does not identify one exact "
            "locked download; create a NodePhell lock before installing"
        )
    return package.artifacts[0]


def release_matches(
    package: PackagePin,
    release: Path,
    runtime: Runtime | None = None,
) -> bool:
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
            return _release_manifest_matches(
                package,
                package_artifact(package),
                release,
                runtime,
            )
    return False


def write_release_manifest(
    package: PackagePin,
    runtime: Runtime,
    release: Path,
) -> None:
    artifact = package_artifact(package)
    data: dict[str, object] = {
        "version": 2,
        "package": {
            "name": normalize_name(package.name),
            "version": package.version,
        },
        "artifact": {
            "kind": artifact.kind,
            "name": artifact.name,
            "sha256": artifact.sha256,
        },
        "contents": release_contents(release),
    }
    if artifact.kind == "sdist":
        data["built_for"] = {
            "implementation": runtime.implementation,
            "python": runtime.python_store_name,
            "abi": runtime.abi,
        }
    path = release.parent / _RELEASE_MANIFEST
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        raise NodePhellError(
            f"cannot record package release identity in {path}: {error}"
        ) from error


def _release_manifest_matches(
    package: PackagePin,
    artifact: PackageArtifact,
    release: Path,
    runtime: Runtime | None,
) -> bool:
    path = release.parent / _RELEASE_MANIFEST
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return False
    expected: dict[str, object] = {
        "version": 2,
        "package": {
            "name": normalize_name(package.name),
            "version": package.version,
        },
        "artifact": {
            "kind": artifact.kind,
            "name": artifact.name,
            "sha256": artifact.sha256,
        },
    }
    if artifact.kind == "sdist":
        if runtime is None:
            return False
        expected["built_for"] = {
            "implementation": runtime.implementation,
            "python": runtime.python_store_name,
            "abi": runtime.abi,
        }
    contents = data.pop("contents", None) if isinstance(data, dict) else None
    return data == expected and valid_contents_record(contents)


def valid_contents_record(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"sha256", "entries", "bytes"}:
        return False
    return (
        isinstance(value.get("sha256"), str)
        and _SHA256.fullmatch(value["sha256"]) is not None
        and isinstance(value.get("entries"), int)
        and not isinstance(value.get("entries"), bool)
        and value["entries"] >= 0
        and isinstance(value.get("bytes"), int)
        and not isinstance(value.get("bytes"), bool)
        and value["bytes"] >= 0
    )


def release_contents(release: Path) -> dict[str, object]:
    hasher = hashlib.sha256()
    entries = 0
    byte_count = 0

    def record(kind: str, relative: str, mode: int, size: int) -> None:
        header = json.dumps(
            [kind, relative, mode, size],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        hasher.update(len(header).to_bytes(8, "big"))
        hasher.update(header)

    def visit(directory: Path, prefix: Path) -> None:
        nonlocal entries, byte_count
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise NodePhellError(
                f"cannot inspect stored package contents in {directory}: {error}"
            ) from error
        for child in children:
            relative = (prefix / child.name).as_posix()
            try:
                details = child.lstat()
            except OSError as error:
                raise NodePhellError(
                    f"cannot inspect stored package path {child}: {error}"
                ) from error
            mode = stat.S_IMODE(details.st_mode)
            entries += 1
            if stat.S_ISLNK(details.st_mode):
                try:
                    target = os.readlink(child)
                except OSError as error:
                    raise NodePhellError(
                        f"cannot inspect stored package link {child}: {error}"
                    ) from error
                target_bytes = os.fsencode(target)
                byte_count += len(target_bytes)
                record("link", relative, mode, len(target_bytes))
                hasher.update(target_bytes)
                continue
            if stat.S_ISDIR(details.st_mode):
                record("directory", relative, mode, 0)
                visit(child, prefix / child.name)
                continue
            if not stat.S_ISREG(details.st_mode):
                raise NodePhellError(
                    f"unsupported file type in stored package: {child}"
                )
            record("file", relative, mode, details.st_size)
            try:
                with child.open("rb") as file:
                    while chunk := file.read(1024 * 1024):
                        hasher.update(chunk)
                        byte_count += len(chunk)
            except OSError as error:
                raise NodePhellError(
                    f"cannot read stored package file {child}: {error}"
                ) from error

    if not release.is_dir() or release.is_symlink():
        raise NodePhellError(f"stored package root is not a directory: {release}")
    visit(release, Path())
    return {
        "sha256": hasher.hexdigest(),
        "entries": entries,
        "bytes": byte_count,
    }


def _store_component(value: str, description: str) -> str:
    if _STORE_COMPONENT.fullmatch(value) is None:
        raise NodePhellError(f"invalid {description} for package store: {value!r}")
    return value


def package_environment(
    runtime: Runtime,
    selection: PackageSelection,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = runtime_environment(runtime, base)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
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
    return _compose_package_sources(releases, (), runtime, user_home)


def _compose_package_sources(
    releases: tuple[Path, ...],
    external_releases: tuple[_ExternalRelease, ...],
    runtime: Runtime,
    user_home: Path | None,
) -> Path:
    digest = _composition_digest(releases, external_releases)
    target = composition_store(runtime, user_home) / digest
    if target.is_dir():
        return target.resolve()

    with exclusive_store_lock(target, user_home) as acquired:
        assert acquired
        if target.is_dir():
            return target.resolve()
        if target.exists() or target.is_symlink():
            raise NodePhellError(
                f"package composition path is not a directory: {target}"
            )
        root = target.parent
        try:
            root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{digest}-", dir=root))
        except OSError as error:
            raise NodePhellError(
                f"cannot create package composition for "
                f"{runtime.python_store_name}: {error}"
            ) from error

        try:
            for release in releases:
                _merge_release(release, staging)
            for release in external_releases:
                _merge_external_release(release, staging)
            try:
                _write_composition_manifest(
                    staging,
                    digest,
                    user_home,
                    external_releases,
                )
                _make_composition_read_only(staging)
                staging.rename(target)
            except OSError as error:
                raise NodePhellError(
                    f"cannot commit package composition {target}: {error}"
                ) from error
            return target.resolve()
        finally:
            if staging.exists():
                _make_directories_writable(staging)
                shutil.rmtree(staging, ignore_errors=True)


def _composition_digest(
    releases: tuple[Path, ...],
    external_releases: tuple[_ExternalRelease, ...] = (),
) -> str:
    hasher = hashlib.sha256()
    hasher.update(b"nodephell-composition-v2\0")
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
    for release in external_releases:
        hasher.update(b"external\0")
        hasher.update(release.identity.encode("ascii"))
        hasher.update(b"\0")
    return hasher.hexdigest()[:32]


def _write_composition_manifest(
    composition: Path,
    digest: str,
    user_home: Path | None,
    external_releases: tuple[_ExternalRelease, ...],
) -> None:
    managed_root = package_store(user_home).resolve(strict=False)
    external_links: list[dict[str, object]] = []
    for directory, directories, files in os.walk(composition):
        parent = Path(directory)
        for name in (*directories, *files):
            link = parent / name
            if not link.is_symlink():
                continue
            try:
                target = link.resolve(strict=True)
                details = target.stat()
            except OSError as error:
                raise NodePhellError(
                    f"cannot inspect package composition link {link}: {error}"
                ) from error
            if target.is_relative_to(managed_root):
                continue
            if not any(
                target.is_relative_to(release.root)
                for release in external_releases
            ):
                raise NodePhellError(
                    f"package composition contains an unowned link: {link}"
                )
            external_links.append(
                {
                    "path": link.relative_to(composition).as_posix(),
                    "target": str(target),
                    "size": details.st_size,
                    "mtime_ns": details.st_mtime_ns,
                    "mode": stat.S_IMODE(details.st_mode),
                }
            )
    manifest = composition / COMPOSITION_MANIFEST
    if manifest.exists() or manifest.is_symlink():
        raise NodePhellError(
            f"package composition reserves the path {manifest.name}"
        )
    data = {
        "version": 1,
        "digest": digest,
        "external_releases": [
            {
                "name": release.name,
                "version": release.version,
                "root": str(release.root),
                "identity": release.identity,
            }
            for release in external_releases
        ],
        "external_links": sorted(
            external_links,
            key=lambda item: str(item["path"]),
        ),
    }
    try:
        manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        manifest.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError as error:
        raise NodePhellError(
            f"cannot record package composition ownership in {manifest}: {error}"
        ) from error


def _make_composition_read_only(root: Path) -> None:
    directories = [Path(directory) for directory, _, _ in os.walk(root)]
    for directory in reversed(directories):
        mode = stat.S_IMODE(directory.stat().st_mode)
        directory.chmod(
            mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        )


def _make_directories_writable(root: Path) -> None:
    for directory, _, _ in os.walk(root):
        path = Path(directory)
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            path.chmod(mode | stat.S_IWUSR)
        except OSError:
            pass


def _merge_release(release: Path, destination: Path) -> None:
    try:
        children = tuple(release.iterdir())
    except OSError as error:
        raise NodePhellError(
            f"cannot inspect package release {release}: {error}"
        ) from error
    for child in children:
        _merge_path(child, destination / child.name)


def _merge_external_release(
    release: _ExternalRelease,
    destination: Path,
) -> None:
    for relative in release.files:
        target = destination / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise NodePhellError(
                f"cannot create package composition directory "
                f"{target.parent}: {error}"
            ) from error
        _merge_path(release.root / relative, target)


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
    environment["PYTHONNOUSERSITE"] = "1"
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
