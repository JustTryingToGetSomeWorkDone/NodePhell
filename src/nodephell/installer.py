# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .activity import working
from .errors import NodePhellError
from .editable import ensure_editable_project
from .host import (
    EmbeddedHost,
    ensure_host,
    load_hosts,
    resolve_host_artifact,
    select_host,
)
from .locking import STAGING_MANIFEST, exclusive_store_lock, shared_store_lock
from .metadata import (
    PackagePin,
    Project,
    discover_project,
    lock_matches_project_definition,
    load_project,
    load_project_definition,
)
from .references import ensure_project_reference
from .runtime import (
    Runtime,
    data_root,
    ensure_runtime,
    load_registry,
    native_build_failure_guidance,
    resolve_runtime_artifact,
    runtime_build_environment,
    select_reusable_runtime,
)
from .resolver import resolve_and_write_lock
from .store import (
    PackageSelection,
    inspect_packages,
    locked_package_commands,
    package_artifact,
    release_matches,
    resolve_packages,
    stored_release_path,
    write_release_manifest,
)
from .versions import matches_runtime


@dataclass(frozen=True)
class InstallationResult:
    project: Project
    runtime: Runtime
    installed_packages: tuple[PackagePin, ...]
    selection: PackageSelection
    host: EmbeddedHost | None = None
    commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class LockResult:
    project: Project
    runtime: Runtime
    path: Path
    updated: bool


@dataclass(frozen=True)
class SyncResult:
    installation: InstallationResult
    lock: LockResult | None


def lock_project(
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
    *,
    update: bool = False,
    selected_extras: tuple[str, ...] | None = None,
    selected_groups: tuple[str, ...] | None = None,
    runtime_requirement: str | None = None,
) -> LockResult:
    guard = data_root(user_home) / "maintenance"
    with shared_store_lock(guard, user_home) as acquired:
        assert acquired
        root = _project_root(start)
        with exclusive_store_lock(root / "pylock.toml", user_home) as locked:
            assert locked
            return _lock_project(
                root,
                user_home,
                progress,
                update=update,
                selected_extras=selected_extras,
                selected_groups=selected_groups,
                runtime_requirement=runtime_requirement,
            )


def _lock_project(
    root: Path,
    user_home: Path | None,
    progress: Callable[[str], None] | None,
    *,
    update: bool,
    selected_extras: tuple[str, ...] | None,
    selected_groups: tuple[str, ...] | None,
    runtime_requirement: str | None,
) -> LockResult:
    lock_path = root / "pylock.toml"
    lock_present = lock_path.exists() or lock_path.is_symlink()
    if lock_present and not update:
        raise NodePhellError(
            f"project lock already exists: {lock_path}; "
            "run 'nodephell update' to replace it"
        )
    if update and (not lock_path.is_file() or lock_path.is_symlink()):
        raise NodePhellError(
            f"project has no lock to update: {lock_path}; "
            "run 'nodephell lock' first"
        )
    project = load_project_definition(root)
    if selected_extras is None or selected_groups is None:
        existing = load_project(root) if lock_path.is_file() else None
        if selected_extras is None:
            selected_extras = (
                existing.selected_extras if existing is not None else ()
            )
        if selected_groups is None:
            selected_groups = (
                existing.selected_groups if existing is not None else ()
            )
    project = replace(
        project,
        selected_extras=tuple(sorted(selected_extras)),
        selected_groups=tuple(sorted(selected_groups)),
    )
    announce = progress if progress is not None else lambda message: None
    artifact = None
    runtime = None
    selection_requirement = runtime_requirement or project.requires_python
    if selection_requirement:
        runtime = select_reusable_runtime(
            selection_requirement,
            load_registry(user_home),
        )
        if runtime is not None:
            artifact = runtime.artifact
            announce(f"Reusing managed CPython {runtime.version} runtime")
        else:
            announce("Selecting an exact CPython runtime artifact")
            artifact = resolve_runtime_artifact(selection_requirement)
    if runtime is None:
        requirement = (
            f"=={artifact.version}" if artifact else selection_requirement
        )
        runtime = ensure_runtime(requirement, user_home, announce, artifact)
    if (
        runtime_requirement is not None
        and project.requires_python is not None
        and not matches_runtime(runtime.version, project.requires_python)
    ):
        raise NodePhellError(
            f"selected runtime {runtime.version} does not satisfy the project's "
            f"Python requirement {project.requires_python!r}"
        )
    host_artifact = None
    if project.host is not None:
        try:
            select_host(project.host, load_hosts(user_home), runtime)
        except NodePhellError:
            announce(f"Selecting an exact {project.host.kind} host artifact")
            host_artifact = resolve_host_artifact(project.host, runtime)
    if progress is None:
        path = resolve_and_write_lock(project, runtime, host_artifact)
    else:
        path = resolve_and_write_lock(
            project,
            runtime,
            host_artifact,
            progress=progress,
        )
    return LockResult(load_project(root), runtime, path, update)


def install_project(
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> InstallationResult:
    guard = data_root(user_home) / "maintenance"
    with shared_store_lock(guard, user_home) as acquired:
        assert acquired
        return _install_project(start, user_home, progress)


def sync_project(
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    root = _project_root(start)
    project_path = root / "pyproject.toml"
    lock_path = root / "pylock.toml"
    lock_result = None
    if project_path.is_file():
        if not lock_path.is_file() or lock_path.is_symlink():
            lock_result = lock_project(root, user_home, progress)
        elif (
            load_project_definition(root).dynamic_dependencies
            or not lock_matches_project_definition(root)
        ):
            lock_result = lock_project(root, user_home, progress, update=True)
    installation = install_project(root, user_home, progress)
    return SyncResult(installation, lock_result)


def _install_project(
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> InstallationResult:
    root = _project_root(start)

    project = load_project(root)
    if project.metadata_file.name != "pylock.toml":
        raise NodePhellError(
            f"project has no lock: {root / 'pylock.toml'}; "
            "run 'nodephell lock' first"
        )
    announce = progress if progress is not None else lambda message: None
    artifact = project.runtime_artifact
    requirement = f"=={artifact.version}" if artifact else project.requires_python
    runtime = ensure_runtime(
        requirement,
        user_home,
        announce,
        artifact,
    )
    host_artifact = project.host_artifact
    embedded_host = None
    if project.host is not None:
        embedded_host = ensure_host(
            project.host,
            runtime,
            user_home,
            announce,
            project.host_artifact,
        )
    package_roots = embedded_host.package_roots if embedded_host is not None else ()
    inspection = inspect_packages(
        project,
        runtime,
        user_home,
        package_roots,
        include_ordinary=embedded_host is None,
    )
    installed: list[PackagePin] = []

    package_count = len(inspection.missing_packages)
    for index, package in enumerate(inspection.missing_packages, start=1):
        with working(
            progress,
            f"Installing {package.name}=={package.version} with stock pip "
            f"({index} of {package_count})",
        ):
            install_release(package, project, runtime, user_home)
        installed.append(package)

    selection = resolve_packages(
        project,
        runtime,
        user_home,
        package_roots,
        include_ordinary=embedded_host is None,
    )
    editable = ensure_editable_project(project, runtime, user_home, announce)
    if editable is not None:
        selection = selection.with_editable_project(
            editable.paths,
            editable.package,
        )
    ensure_project_reference(project, runtime, selection, user_home)
    try:
        commands = locked_package_commands(project, runtime, selection, user_home)
    except NodePhellError as error:
        raise NodePhellError(
            f"{error}\n"
            "The project's packages are available and registered, but "
            "NodePhell could not create their command launchers. Nothing "
            "needs to be deleted or downloaded again. Correct or report "
            "the command setup problem, then rerun 'nodephell install'."
        ) from error
    return InstallationResult(
        project,
        runtime,
        tuple(installed),
        selection,
        embedded_host,
        tuple(command.name for command in commands),
    )


def _project_root(start: Path | None) -> Path:
    location = Path.cwd() if start is None else start.expanduser()
    if start is not None and not location.exists():
        raise NodePhellError(f"project path does not exist: {location}")
    root = discover_project(location)
    if root is None:
        raise NodePhellError(
            f"no pylock.toml or pyproject.toml found from {location}"
        )
    return root


def install_release(
    package: PackagePin,
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
) -> Path:
    target = stored_release_path(package, runtime, user_home)
    commit_target = target.parent
    with exclusive_store_lock(commit_target, user_home) as acquired:
        assert acquired
        if commit_target.exists() or commit_target.is_symlink():
            if release_matches(package, target, runtime):
                return target.resolve()
            raise NodePhellError(
                f"refusing to replace invalid existing store entry: {target}; "
                "run 'nodephell store clean --apply' to remove it"
            )

        staging: Path | None = None
        try:
            commit_target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{package.version}-",
                    dir=commit_target.parent,
                )
            )
            (staging / STAGING_MANIFEST).write_text(
                json.dumps(
                    {"version": 1, "target": str(commit_target.absolute())},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            staged_release = staging / "root"
            staged_release.mkdir()
        except OSError as error:
            if staging is not None and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise NodePhellError(
                f"cannot create staging directory for {target}: {error}"
            ) from error

        try:
            _run_stock_pip(package, project, runtime, staged_release)
            write_release_manifest(package, runtime, staged_release)
            if not release_matches(package, staged_release, runtime):
                raise NodePhellError(
                    f"pip produced no matching metadata for "
                    f"{package.name}=={package.version}"
                )
            try:
                (staging / STAGING_MANIFEST).unlink()
                staging.rename(commit_target)
            except OSError as error:
                raise NodePhellError(
                    f"cannot commit shared store entry {target}: {error}"
                ) from error
            return target.resolve()
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def _run_stock_pip(
    package: PackagePin,
    project: Project,
    runtime: Runtime,
    staging: Path,
) -> None:
    environment = runtime_build_environment(runtime)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    identity = f"{package.name}=={package.version}"
    artifact = package_artifact(package)
    requirement = f"{package.name} @ {artifact.url}"
    hash_options = [
        f"--hash={algorithm}:{digest}"
        for algorithm, digest in artifact.hashes
    ]
    requirement_arguments = [requirement]
    with tempfile.TemporaryDirectory(prefix="nodephell-requirements-") as temporary:
        if hash_options:
            requirements_file = Path(temporary) / "requirements.txt"
            requirements_file.write_text(
                " ".join((requirement, *hash_options)) + "\n",
                encoding="utf-8",
            )
            requirement_arguments = ["-r", str(requirements_file)]
        command = [
            str(runtime.executable),
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--no-deps",
            "--no-compile",
            "--target",
            str(staging),
            *(("--require-hashes",) if hash_options else ()),
            *requirement_arguments,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=project.root,
                env=environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as error:
            raise NodePhellError(
                f"cannot run pip with {runtime.executable}: {error}"
            ) from error
    if result.returncode != 0:
        message = (
            f"stock pip failed while installing {identity} "
            f"(exit status {result.returncode})"
        )
        details = (result.stdout or "").strip()
        if details:
            message += f":\n{details}"
        raise NodePhellError(
            message,
            guidance=native_build_failure_guidance(details),
        )
