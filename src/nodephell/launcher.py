# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, NoReturn

from .errors import NodePhellError
from .locking import shared_store_lock
from .metadata import Project, discover_project, invocation_start, load_project
from .references import ensure_project_reference
from .runtime import Runtime, bootstrap_runtime, data_root, load_registry, select_runtime
from .store import PackageSelection, package_environment, resolve_packages


@dataclass(frozen=True)
class Resolution:
    runtime: Runtime
    project: Project | None
    packages: PackageSelection
    user_home: Path | None = None

    @property
    def system_fallback(self) -> bool:
        return self.project is None


def resolve(
    arguments: list[str],
    cwd: Path | None = None,
    user_home: Path | None = None,
) -> Resolution:
    runtime, project = resolve_project(arguments, cwd, user_home)
    if project is None:
        return Resolution(runtime, None, PackageSelection(()), user_home)
    packages = resolve_packages(project, runtime, user_home)
    return Resolution(runtime, project, packages, user_home)


def resolve_project(
    arguments: list[str],
    cwd: Path | None = None,
    user_home: Path | None = None,
) -> tuple[Runtime, Project | None]:
    """Select a project and runtime before choosing package providers."""
    working_directory = Path.cwd() if cwd is None else cwd
    current = bootstrap_runtime()
    start = invocation_start(arguments, working_directory)
    root = discover_project(start)
    if root is None:
        return current, None

    project = load_project(root)
    runtime = select_runtime(
        project.runtime_requirement,
        load_registry(user_home),
        current,
        project.runtime_artifact,
    )
    return runtime, project


def register_resolution(resolution: Resolution) -> None:
    """Lazily register a fully resolved project before it is executed."""
    if resolution.project is not None:
        guard = data_root(resolution.user_home) / "maintenance"
        with shared_store_lock(guard, resolution.user_home) as acquired:
            assert acquired
            ensure_project_reference(
                resolution.project,
                resolution.runtime,
                resolution.packages,
                resolution.user_home,
            )


def execution_environment(
    resolution: Resolution,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if resolution.system_fallback:
        return dict(os.environ if base is None else base)
    return package_environment(resolution.runtime, resolution.packages, base)


def execute(arguments: list[str], resolution: Resolution) -> NoReturn:
    register_resolution(resolution)
    executable = str(resolution.runtime.executable)
    try:
        os.execvpe(
            executable,
            [executable, *arguments],
            execution_environment(resolution),
        )
    except OSError as error:
        raise NodePhellError(f"cannot execute {executable}: {error}") from error
