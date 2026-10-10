# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping, NoReturn

from .errors import NodePhellError, print_error
from .editable import resolve_editable_project
from .locking import shared_store_lock
from .metadata import (
    Project,
    discover_project,
    invocation_start,
    is_project_lock_path,
    load_project,
    lock_matches_project_definition,
)
from .references import ensure_project_reference
from .runtime import (
    Runtime,
    bootstrap_runtime,
    data_root,
    load_registry,
    select_runtime,
)
from .store import (
    PackageCommand,
    PackageSelection,
    locked_package_commands,
    package_environment,
    resolve_packages,
)


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
    editable = resolve_editable_project(project, runtime, user_home)
    if editable is not None:
        packages = packages.with_editable_project(
            editable.paths,
            editable.package,
        )
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
    if not is_project_lock_path(project.metadata_file, root):
        raise NodePhellError("project has no lock; run 'nodephell sync'")
    if (
        project.source_fingerprint is not None
        and (root / "pyproject.toml").is_file()
        and not lock_matches_project_definition(root)
    ):
        raise NodePhellError(
            f"project definition changed since {project.metadata_file.name} "
            "was created; "
            "run 'nodephell sync'"
        )
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


def command_main(command: str, arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    try:
        _, project = resolve_project([], Path.cwd())
        if project is not None and project.host is not None:
            from .host import execute_host_package_command, resolve_host

            execute_host_package_command(command, values, resolve_host([]))
            return 0
        execute_package_command(command, values, resolve([]))
    except NodePhellError as error:
        print_error(error)
        return 2


def execute_package_command(
    command: str,
    arguments: list[str],
    resolution: Resolution,
) -> NoReturn:
    if resolution.project is None:
        raise NodePhellError(
            f"package command {command!r} requires a NodePhell project"
        )
    selected = _select_package_command(
        command,
        resolution.project,
        resolution.runtime,
        resolution.packages,
        resolution.user_home,
    )
    register_resolution(resolution)
    executable = str(resolution.runtime.executable)
    try:
        os.execvpe(
            executable,
            [executable, *_package_command_arguments(selected, arguments)],
            execution_environment(resolution),
        )
    except OSError as error:
        raise NodePhellError(f"cannot execute {executable}: {error}") from error


def _select_package_command(
    name: str,
    project: Project,
    runtime: Runtime,
    selection: PackageSelection,
    user_home: Path | None,
) -> PackageCommand:
    matches = tuple(
        command
        for command in locked_package_commands(
            project, runtime, selection, user_home
        )
        if command.name == name
    )
    if not matches:
        raise NodePhellError(
            f"the project and its locked packages do not provide command {name!r}"
        )
    return matches[0]


def _package_command_arguments(
    command: PackageCommand,
    arguments: list[str],
) -> list[str]:
    runner = Path(__file__).with_name("command_runner.py")
    return [
        str(runner),
        command.module,
        command.attributes,
        command.name,
        *arguments,
    ]
