# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, NoReturn

from .errors import NodePhellError
from .metadata import Project, discover_project, invocation_start, load_project
from .runtime import Runtime, bootstrap_runtime, load_registry, select_runtime
from .store import PackageSelection, package_environment, resolve_packages


@dataclass(frozen=True)
class Resolution:
    runtime: Runtime
    project: Project | None
    packages: PackageSelection

    @property
    def system_fallback(self) -> bool:
        return self.project is None


def resolve(
    arguments: list[str],
    cwd: Path | None = None,
    user_home: Path | None = None,
) -> Resolution:
    working_directory = Path.cwd() if cwd is None else cwd
    current = bootstrap_runtime()
    start = invocation_start(arguments, working_directory)
    root = discover_project(start)
    if root is None:
        return Resolution(current, None, PackageSelection(()))

    project = load_project(root)
    runtime = select_runtime(
        project.runtime_requirement,
        load_registry(user_home),
        current,
        project.runtime_artifact,
    )
    packages = resolve_packages(project, runtime, user_home)
    return Resolution(runtime, project, packages)


def execution_environment(
    resolution: Resolution,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if resolution.system_fallback:
        return dict(os.environ if base is None else base)
    return package_environment(resolution.runtime, resolution.packages, base)


def execute(arguments: list[str], resolution: Resolution) -> NoReturn:
    executable = str(resolution.runtime.executable)
    try:
        os.execvpe(
            executable,
            [executable, *arguments],
            execution_environment(resolution),
        )
    except OSError as error:
        raise NodePhellError(f"cannot execute {executable}: {error}") from error
