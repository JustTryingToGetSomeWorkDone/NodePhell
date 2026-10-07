# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from .errors import NodePhellError
from .host import (
    EmbeddedHost,
    ensure_host,
    load_hosts,
    resolve_host_artifact,
    select_host,
)
from .locking import STAGING_MANIFEST, exclusive_store_lock, shared_store_lock
from .metadata import PackagePin, Project, discover_project, load_project
from .references import ensure_project_reference
from .runtime import (
    Runtime,
    data_root,
    ensure_runtime,
    resolve_runtime_artifact,
    runtime_environment,
)
from .resolver import resolve_and_write_lock
from .store import (
    PackageSelection,
    inspect_packages,
    package_artifact,
    release_matches,
    resolve_packages,
    stored_release_path,
    write_release_manifest,
)


@dataclass(frozen=True)
class InstallationResult:
    project: Project
    runtime: Runtime
    installed_packages: tuple[PackagePin, ...]
    selection: PackageSelection
    host: EmbeddedHost | None = None


def install_project(
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> InstallationResult:
    guard = data_root(user_home) / "maintenance"
    with shared_store_lock(guard, user_home) as acquired:
        assert acquired
        return _install_project(start, user_home, progress)


def _install_project(
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> InstallationResult:
    location = Path.cwd() if start is None else start.expanduser()
    if start is not None and not location.exists():
        raise NodePhellError(f"project path does not exist: {location}")
    root = discover_project(location)
    if root is None:
        raise NodePhellError(f"no pylock.toml or pyproject.toml found from {location}")

    project = load_project(root)
    announce = progress if progress is not None else lambda message: None
    artifact = project.runtime_artifact
    if (
        artifact is None
        and project.metadata_file.name == "pyproject.toml"
        and project.requires_python
    ):
        announce("Selecting an exact CPython runtime artifact")
        artifact = resolve_runtime_artifact(project.requires_python)
    requirement = f"=={artifact.version}" if artifact else project.requires_python
    runtime = ensure_runtime(
        requirement,
        user_home,
        announce,
        artifact,
    )
    host_artifact = project.host_artifact
    if (
        host_artifact is None
        and project.metadata_file.name == "pyproject.toml"
        and project.host is not None
    ):
        try:
            select_host(
                project.host,
                load_hosts(user_home),
                runtime,
            )
        except NodePhellError:
            announce(
                f"Selecting an exact {project.host.kind} host artifact"
            )
            host_artifact = resolve_host_artifact(project.host, runtime)
    if project.metadata_file.name == "pyproject.toml":
        announce("Resolving the complete dependency closure with stock pip")
        lock_path = resolve_and_write_lock(project, runtime, host_artifact)
        announce(f"Wrote {lock_path}")
        project = load_project(root)
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

    for package in inspection.missing_packages:
        announce(f"Installing {package.name}=={package.version}")
        install_release(package, project, runtime, user_home)
        installed.append(package)

    selection = resolve_packages(
        project,
        runtime,
        user_home,
        package_roots,
        include_ordinary=embedded_host is None,
    )
    ensure_project_reference(project, runtime, selection, user_home)
    return InstallationResult(
        project,
        runtime,
        tuple(installed),
        selection,
        embedded_host,
    )


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
    environment = runtime_environment(runtime)
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
            )
        except OSError as error:
            raise NodePhellError(
                f"cannot run pip with {runtime.executable}: {error}"
            ) from error
    if result.returncode != 0:
        raise NodePhellError(
            f"stock pip failed while installing {identity} "
            f"(exit status {result.returncode})"
        )
