# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile
from typing import Callable

from .errors import NodePhellError
from .installer import InstallationResult, LockResult, install_project, lock_project
from .locking import exclusive_store_lock, shared_store_lock
from .metadata import (
    DependencyOption,
    LOCK_FILENAMES,
    Project,
    discover_project,
    lock_matches_project_definition,
    load_project,
    load_project_definition,
    normalize_name,
    project_lock_path,
)
from .references import ProjectReference, inspect_project_references
from .resolver import rewrite_lock_selection
from .runtime import data_root


@dataclass(frozen=True)
class ReleaseUse:
    path: Path
    project_count: int


@dataclass(frozen=True)
class OptionUpdate:
    project: Project
    lock: LockResult
    installation: InstallationResult
    used_elsewhere: tuple[ReleaseUse, ...]
    unused_releases: tuple[Path, ...]
    uncertain_releases: tuple[Path, ...]
    dependencies_changed: bool = True


def inspect_project_options(start: Path | None = None) -> Project:
    root = _project_root(start)
    definition = load_project_definition(root)
    lock = project_lock_path(root)
    if not lock.is_file() or lock.is_symlink():
        return definition
    installed = load_project(root)
    optional_dependencies = _with_missing_options(
        definition.optional_dependencies,
        installed.selected_extras,
    )
    dependency_groups = _with_missing_options(
        definition.dependency_groups,
        installed.selected_groups,
    )
    return replace(
        definition,
        optional_dependencies=optional_dependencies,
        dependency_groups=dependency_groups,
        selected_extras=installed.selected_extras,
        selected_groups=installed.selected_groups,
    )


def update_project_options(
    start: Path | None,
    extras: tuple[str, ...],
    groups: tuple[str, ...],
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> OptionUpdate:
    root = _project_root(start)
    definition = load_project_definition(root)
    extras = tuple(sorted({normalize_name(name) for name in extras}))
    groups = tuple(sorted({normalize_name(name) for name in groups}))
    _validate_selection(definition, extras, groups)

    lock_path = project_lock_path(root)
    if lock_path.is_symlink():
        raise NodePhellError(f"refusing to replace symlinked lock: {lock_path}")
    lock_paths = tuple(root / name for name in LOCK_FILENAMES)
    try:
        previous_locks = {
            path: path.read_bytes() if path.is_file() else None
            for path in lock_paths
        }
    except OSError as error:
        raise NodePhellError(f"cannot read {lock_path}: {error}") from error
    previous_lock = previous_locks[lock_path]
    references, _ = inspect_project_references(user_home)
    old_reference = _project_reference(references, root)
    previous_reference = (
        old_reference.manifest.read_bytes() if old_reference is not None else None
    )

    try:
        path = _rewrite_dependency_neutral_selection(
            definition,
            extras,
            groups,
            user_home,
        )
        if path is None:
            lock = lock_project(
                root,
                user_home,
                progress,
                update=previous_lock is not None,
                selected_extras=extras,
                selected_groups=groups,
            )
        elif progress is not None:
            progress(
                "Option change does not affect dependencies; "
                "updating selection only"
            )
        installation = install_project(root, user_home, progress)
        if path is not None:
            lock = LockResult(
                load_project(root),
                installation.runtime,
                path,
                True,
            )
    except BaseException:
        for path, contents in previous_locks.items():
            _restore_file(path, contents)
        _restore_reference(root, old_reference, previous_reference, user_home)
        raise

    references, reference_issues = inspect_project_references(user_home)
    new_reference = _project_reference(references, root)
    old_releases = set(old_reference.releases if old_reference is not None else ())
    new_releases = set(new_reference.releases if new_reference is not None else ())
    removed = tuple(sorted(old_releases - new_releases, key=os.fspath))
    counts = {
        release: sum(release in reference.releases for reference in references)
        for release in removed
    }
    used = tuple(
        ReleaseUse(release, counts[release])
        for release in removed
        if counts[release]
    )
    if reference_issues:
        unused = ()
        uncertain = tuple(release for release in removed if not counts[release])
    else:
        unused = tuple(release for release in removed if not counts[release])
        uncertain = ()
    return OptionUpdate(
        inspect_project_options(root),
        lock,
        installation,
        used,
        unused,
        uncertain,
        path is None,
    )


def release_label(path: Path, user_home: Path | None = None) -> str:
    store = ((Path.home() if user_home is None else user_home) / ".python/packages")
    try:
        relative = path.relative_to(store)
    except ValueError:
        return str(path)
    if len(relative.parts) >= 2:
        return f"{relative.parts[0]}=={relative.parts[1]}"
    return str(path)


def _with_missing_options(
    declared: tuple[DependencyOption, ...],
    selected: tuple[str, ...],
) -> tuple[DependencyOption, ...]:
    names = {option.name for option in declared}
    missing = tuple(
        DependencyOption(name, (), available=False)
        for name in selected
        if name not in names
    )
    return tuple(sorted(declared + missing, key=lambda option: option.name))


def _rewrite_dependency_neutral_selection(
    project: Project,
    extras: tuple[str, ...],
    groups: tuple[str, ...],
    user_home: Path | None,
) -> Path | None:
    lock_path = project_lock_path(project.root)
    if not lock_path.is_file() or lock_path.is_symlink():
        return None
    locked = load_project(project.root)
    if not _selection_change_is_dependency_neutral(
        project,
        locked.selected_extras,
        extras,
        locked.selected_groups,
        groups,
    ):
        return None
    guard = data_root(user_home) / "maintenance"
    with shared_store_lock(guard, user_home) as acquired:
        assert acquired
        with exclusive_store_lock(lock_path, user_home) as locked_file:
            assert locked_file
            if not lock_matches_project_definition(project.root):
                return None
            selected = replace(
                project,
                selected_extras=extras,
                selected_groups=groups,
            )
            return rewrite_lock_selection(selected)


def _selection_change_is_dependency_neutral(
    project: Project,
    old_extras: tuple[str, ...],
    new_extras: tuple[str, ...],
    old_groups: tuple[str, ...],
    new_groups: tuple[str, ...],
) -> bool:
    extras = {option.name: option for option in project.optional_dependencies}
    groups = {option.name: option for option in project.dependency_groups}
    changed_extras = set(old_extras).symmetric_difference(new_extras)
    changed_groups = set(old_groups).symmetric_difference(new_groups)
    return all(
        name in extras and not extras[name].requirements
        for name in changed_extras
    ) and all(
        name in groups
        and not groups[name].requirements
        and not groups[name].includes
        for name in changed_groups
    )


def _validate_selection(
    project: Project,
    extras: tuple[str, ...],
    groups: tuple[str, ...],
) -> None:
    available_extras = {option.name for option in project.optional_dependencies}
    available_groups = {option.name for option in project.dependency_groups}
    missing_extra = next(
        (name for name in extras if name not in available_extras),
        None,
    )
    if missing_extra is not None:
        raise NodePhellError(f"project does not declare extra {missing_extra!r}")
    missing_group = next((name for name in groups if name not in available_groups), None)
    if missing_group is not None:
        raise NodePhellError(
            f"project does not declare dependency group {missing_group!r}"
        )


def _project_root(start: Path | None) -> Path:
    location = Path.cwd() if start is None else start.expanduser()
    root = discover_project(location)
    if root is None or not (root / "pyproject.toml").is_file():
        raise NodePhellError(f"no pyproject.toml found from {location}")
    return root


def _project_reference(
    references: tuple[ProjectReference, ...],
    root: Path,
) -> ProjectReference | None:
    resolved = root.resolve(strict=False)
    return next(
        (reference for reference in references if reference.project_root == resolved),
        None,
    )


def _restore_reference(
    root: Path,
    previous: ProjectReference | None,
    contents: bytes | None,
    user_home: Path | None,
) -> None:
    if previous is not None and contents is not None:
        _restore_file(previous.manifest, contents)
        return
    references, _ = inspect_project_references(user_home)
    current = _project_reference(references, root)
    if current is not None:
        try:
            current.manifest.unlink()
        except OSError:
            pass


def _restore_file(path: Path, contents: bytes | None) -> None:
    if contents is None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}-restore-",
            dir=path.parent,
        )
        with os.fdopen(descriptor, "wb") as file:
            file.write(contents)
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
