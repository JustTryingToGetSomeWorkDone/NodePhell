# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile

from .errors import NodePhellError
from .metadata import PackagePin, Project, discover_project, load_project
from .runtime import (
    Runtime,
    ensure_runtime,
    resolve_runtime_artifact,
    runtime_environment,
)
from .resolver import resolve_and_write_lock
from .store import (
    PackageSelection,
    inspect_packages,
    release_matches,
    resolve_packages,
    stored_release_path,
)


@dataclass(frozen=True)
class InstallationResult:
    project: Project
    runtime: Runtime
    installed_packages: tuple[PackagePin, ...]
    selection: PackageSelection


def install_project(
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
    if project.metadata_file.name == "pyproject.toml":
        announce("Resolving the complete dependency closure with stock pip")
        lock_path = resolve_and_write_lock(project, runtime)
        announce(f"Wrote {lock_path}")
        project = load_project(root)
    inspection = inspect_packages(project, runtime, user_home)
    installed: list[PackagePin] = []

    for package in inspection.missing_packages:
        announce(f"Installing {package.name}=={package.version}")
        install_release(package, project, runtime, user_home)
        installed.append(package)

    selection = resolve_packages(project, runtime, user_home)
    return InstallationResult(project, runtime, tuple(installed), selection)


def install_release(
    package: PackagePin,
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
) -> Path:
    target = stored_release_path(package, runtime, user_home)
    if target.exists():
        if release_matches(package, target):
            return target.resolve()
        raise NodePhellError(
            f"refusing to replace invalid existing store entry: {target}"
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{package.version}-",
                dir=target.parent,
            )
        )
    except OSError as error:
        raise NodePhellError(
            f"cannot create staging directory for {target}: {error}"
        ) from error

    try:
        _run_stock_pip(package, project, runtime, staging)
        if not release_matches(package, staging):
            raise NodePhellError(
                f"pip produced no matching metadata for "
                f"{package.name}=={package.version}"
            )
        try:
            staging.rename(target)
        except FileExistsError:
            if release_matches(package, target):
                return target.resolve()
            raise NodePhellError(
                f"store entry appeared during installation but is invalid: {target}"
            )
        except OSError as error:
            raise NodePhellError(
                f"cannot commit historical store entry {target}: {error}"
            ) from error
        return target.resolve()
    finally:
        if staging.exists():
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
    requirement = f"{package.name}=={package.version}"
    hash_options = [
        f"--hash={algorithm}:{digest}"
        for algorithm, digest in package.hashes
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
            f"stock pip failed while installing {requirement} "
            f"(exit status {result.returncode})"
        )
