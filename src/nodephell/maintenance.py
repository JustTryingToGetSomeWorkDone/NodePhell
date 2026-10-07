# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import json
import os
from pathlib import Path
import re
import shutil

from .errors import NodePhellError
from .locking import STAGING_MANIFEST, exclusive_store_lock
from .metadata import normalize_name
from .runtime import data_root
from .store import package_store, release_contents, valid_contents_record


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPOSITION_NAME = re.compile(r"^[0-9a-f]{32}$")
_RELEASE_MANIFEST = "nodephell.json"


@dataclass(frozen=True)
class StoreIssue:
    path: Path
    message: str
    cleanup_path: Path | None = None
    lock_target: Path | None = None


@dataclass(frozen=True)
class StoreValidation:
    checked_releases: int
    issues: tuple[StoreIssue, ...]


@dataclass(frozen=True)
class StoreCleanup:
    validation: StoreValidation
    candidates: tuple[Path, ...]
    removed: tuple[Path, ...] = ()
    skipped: tuple[Path, ...] = ()


def validate_store(user_home: Path | None = None) -> StoreValidation:
    """Check committed releases and derived compositions without changing them."""
    issues: list[StoreIssue] = []
    checked = 0
    root = package_store(user_home)
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        issues.append(StoreIssue(root, "package store is not a directory"))
    elif root.is_dir():
        for package_dir in _directories(root, issues, "package"):
            if package_dir.name.startswith("."):
                issues.append(StoreIssue(package_dir, "unexpected store directory"))
                continue
            for version_dir in _directories(package_dir, issues, "package version"):
                for artifact_dir in _directories(
                    version_dir, issues, "package artifact"
                ):
                    for digest_dir in _directories(
                        artifact_dir, issues, "artifact hash"
                    ):
                        if digest_dir.name.startswith("."):
                            issue = _staging_issue(digest_dir, user_home)
                            if issue is not None:
                                issues.append(issue)
                            continue
                        if _SHA256.fullmatch(digest_dir.name) is None:
                            issues.append(
                                StoreIssue(
                                    digest_dir,
                                    "artifact directory is not a SHA-256 hash",
                                )
                            )
                            continue
                        built_for = digest_dir / "built-for"
                        if (digest_dir / "root").exists() or (
                            digest_dir / _RELEASE_MANIFEST
                        ).exists():
                            checked += 1
                            _add_release_issue(issues, digest_dir, root, False)
                        if built_for.is_dir() and not built_for.is_symlink():
                            for python_dir in _directories(
                                built_for, issues, "source-build Python version"
                            ):
                                for abi_dir in _directories(
                                    python_dir, issues, "source-build ABI"
                                ):
                                    if abi_dir.name.startswith("."):
                                        issue = _staging_issue(abi_dir, user_home)
                                        if issue is not None:
                                            issues.append(issue)
                                        continue
                                    checked += 1
                                    _add_release_issue(issues, abi_dir, root, True)
                        elif built_for.exists() or built_for.is_symlink():
                            issues.append(
                                StoreIssue(
                                    built_for,
                                    "source-build container is not a directory",
                                )
                            )
                        elif not (digest_dir / "root").exists() and not (
                            digest_dir / _RELEASE_MANIFEST
                        ).exists():
                            checked += 1
                            issues.append(
                                StoreIssue(
                                    digest_dir,
                                    "stored release is incomplete",
                                    digest_dir,
                                    digest_dir,
                                )
                            )

    invalid_roots = tuple(
        issue.cleanup_path / "root"
        for issue in issues
        if issue.cleanup_path is not None
        and issue.cleanup_path.is_relative_to(root)
    )
    issues.extend(_composition_issues(user_home, invalid_roots))
    return StoreValidation(checked, tuple(issues))


def clean_store(
    user_home: Path | None = None,
    *,
    apply: bool = False,
) -> StoreCleanup:
    """Remove only entries that validation proves cannot be used."""
    validation = validate_store(user_home)
    removable: dict[Path, StoreIssue] = {}
    for issue in validation.issues:
        if issue.cleanup_path is not None:
            removable.setdefault(issue.cleanup_path, issue)
    candidates = tuple(sorted(removable, key=os.fspath))
    if not apply:
        return StoreCleanup(validation, candidates)

    removed: list[Path] = []
    skipped: list[Path] = []
    for path in candidates:
        issue = removable[path]
        with exclusive_store_lock(
            issue.lock_target or path,
            user_home,
            wait=False,
        ) as acquired:
            if not acquired:
                skipped.append(path)
                continue
            if not path.exists() and not path.is_symlink():
                continue
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as error:
                raise NodePhellError(f"cannot remove {path}: {error}") from error
            removed.append(path)
            _remove_empty_parents(path.parent, data_root(user_home))
    return StoreCleanup(validation, candidates, tuple(removed), tuple(skipped))


def _directories(
    root: Path,
    issues: list[StoreIssue],
    description: str,
) -> tuple[Path, ...]:
    try:
        children = tuple(sorted(root.iterdir(), key=lambda item: item.name))
    except OSError as error:
        issues.append(StoreIssue(root, f"cannot inspect {description}: {error}"))
        return ()
    directories: list[Path] = []
    for child in children:
        if child.is_dir() and not child.is_symlink():
            directories.append(child)
        else:
            issues.append(StoreIssue(child, f"{description} entry is not a directory"))
    return tuple(directories)


def _add_release_issue(
    issues: list[StoreIssue],
    entry: Path,
    root: Path,
    source: bool,
) -> None:
    problem = _release_problem(entry, root, source)
    if problem is not None:
        issues.append(StoreIssue(entry, problem, entry, entry))


def _release_problem(entry: Path, store_root: Path, source: bool) -> str | None:
    release = entry / "root"
    manifest = entry / _RELEASE_MANIFEST
    try:
        entry_names = {child.name for child in entry.iterdir()}
    except OSError as error:
        return f"stored release cannot be inspected: {error}"
    if entry_names != {"root", _RELEASE_MANIFEST}:
        return "stored release contains incomplete or unexpected entries"
    if not release.is_dir() or release.is_symlink():
        return "stored release has no usable root directory"
    if not manifest.is_file() or manifest.is_symlink():
        return "stored release has no usable identity manifest"
    try:
        with manifest.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        return f"stored release identity cannot be read: {error}"
    problem = _manifest_problem(data, entry, store_root, source)
    if problem is not None:
        return problem
    package = data["package"]
    if not _metadata_matches(release, package["name"], package["version"]):
        return "installed package metadata does not match its store identity"
    try:
        actual_contents = release_contents(release)
    except NodePhellError as error:
        return str(error)
    if actual_contents != data["contents"]:
        return "stored package files have changed since installation"
    return None


def _manifest_problem(
    data: object,
    entry: Path,
    store_root: Path,
    source: bool,
) -> str | None:
    if not isinstance(data, dict):
        return "stored release identity is not an object"
    fields = {"version", "package", "artifact", "contents"}
    if source:
        fields.add("built_for")
    if set(data) != fields or data.get("version") != 2:
        return "stored release identity has an unsupported format"
    package = data.get("package")
    artifact = data.get("artifact")
    if (
        not isinstance(package, dict)
        or set(package) != {"name", "version"}
        or not isinstance(package.get("name"), str)
        or not isinstance(package.get("version"), str)
        or not isinstance(artifact, dict)
        or set(artifact) != {"kind", "name", "sha256"}
        or artifact.get("kind") not in {"wheel", "sdist"}
        or not isinstance(artifact.get("name"), str)
        or not isinstance(artifact.get("sha256"), str)
        or not valid_contents_record(data.get("contents"))
    ):
        return "stored release identity is incomplete"
    relative = entry.relative_to(store_root).parts
    if len(relative) != (7 if source else 4):
        return "stored release is at an unexpected path"
    if (
        relative[0] != normalize_name(package["name"])
        or relative[1] != package["version"]
        or relative[2] != artifact["name"]
        or relative[3] != artifact["sha256"]
    ):
        return "stored release path does not match its identity"
    if source:
        built_for = data.get("built_for")
        if (
            artifact["kind"] != "sdist"
            or relative[4] != "built-for"
            or not isinstance(built_for, dict)
            or set(built_for) != {"implementation", "python", "abi"}
            or built_for.get("python") != relative[5]
            or built_for.get("abi") != relative[6]
            or not isinstance(built_for.get("implementation"), str)
        ):
            return "source build path does not match its Python identity"
    elif artifact["kind"] != "wheel":
        return "source-built package is missing its Python build identity"
    return None


def _metadata_matches(release: Path, name: str, version: str) -> bool:
    for metadata_file in release.glob("*.dist-info/METADATA"):
        try:
            with metadata_file.open("rb") as file:
                metadata = BytesParser(policy=compat32).parse(file, headersonly=True)
        except OSError:
            continue
        found_name = metadata.get("Name")
        if (
            isinstance(found_name, str)
            and normalize_name(found_name) == normalize_name(name)
            and metadata.get("Version") == version
        ):
            return True
    return False


def _staging_issue(
    staging: Path,
    user_home: Path | None,
) -> StoreIssue | None:
    marker = staging / STAGING_MANIFEST
    try:
        with marker.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return StoreIssue(
            staging,
            "unrecognized temporary package directory; remove it manually",
        )
    target_value = data.get("target") if isinstance(data, dict) else None
    target = Path(target_value) if isinstance(target_value, str) else Path()
    if not target.is_absolute() or target.parent != staging.parent:
        return StoreIssue(staging, "temporary package target is invalid")
    with exclusive_store_lock(target, user_home, wait=False) as acquired:
        if not acquired:
            return None
    return StoreIssue(staging, "abandoned package installation", staging, target)


def _composition_issues(
    user_home: Path | None,
    invalid_roots: tuple[Path, ...],
) -> tuple[StoreIssue, ...]:
    root = data_root(user_home)
    if not root.is_dir():
        return ()
    issues: list[StoreIssue] = []
    for compositions in root.glob("python*/compositions"):
        if not compositions.is_dir() or compositions.is_symlink():
            issues.append(StoreIssue(compositions, "composition store is invalid"))
            continue
        for child in sorted(compositions.iterdir(), key=lambda item: item.name):
            if child.name.startswith("."):
                digest = child.name[1:33]
                target = compositions / digest
                if (
                    _COMPOSITION_NAME.fullmatch(digest) is None
                    or child.name[33:34] != "-"
                ):
                    issues.append(
                        StoreIssue(
                            child,
                            "unrecognized temporary composition; remove it manually",
                        )
                    )
                    continue
                with exclusive_store_lock(target, user_home, wait=False) as acquired:
                    if acquired:
                        issues.append(
                            StoreIssue(
                                child,
                                "abandoned package composition",
                                child,
                                target,
                            )
                        )
                continue
            if _COMPOSITION_NAME.fullmatch(child.name) is None:
                issues.append(StoreIssue(child, "unrecognized composition entry"))
                continue
            problem = _composition_problem(
                child,
                package_store(user_home),
                invalid_roots,
            )
            if problem is not None:
                issues.append(StoreIssue(child, problem, child, child))
    return tuple(issues)


def _composition_problem(
    composition: Path,
    packages: Path,
    invalid_roots: tuple[Path, ...],
) -> str | None:
    if not composition.is_dir() or composition.is_symlink():
        return "package composition is not a directory"
    found_link = False
    pending = [composition]
    while pending:
        directory = pending.pop()
        try:
            children = tuple(directory.iterdir())
        except OSError as error:
            return f"cannot inspect package composition: {error}"
        for child in children:
            if child.is_symlink():
                found_link = True
                try:
                    target = child.resolve(strict=True)
                    target.relative_to(packages.resolve(strict=True))
                except (OSError, ValueError):
                    return "package composition contains a broken or foreign link"
                if any(target.is_relative_to(root) for root in invalid_roots):
                    return "package composition refers to an invalid release"
            elif child.is_dir():
                pending.append(child)
            else:
                return "package composition contains an unexpected file"
    return None if found_link else "package composition is empty"


def _remove_empty_parents(path: Path, stop: Path) -> None:
    stop = stop.absolute()
    current = path.absolute()
    while current != stop and current.is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
