# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .errors import NodePhellError
from .host import (
    delete_host,
    execute_host,
    execute_host_gui,
    load_hosts,
    register_host,
    resolve_host,
    unregister_host,
)
from .adapters import discover_adapters
from .installer import install_project, lock_project
from .launcher import Resolution, execute, resolve
from .launchers import install_launchers, path_problem, uninstall_launchers
from .maintenance import clean_store, validate_store
from .references import (
    inspect_project_references,
    move_project_reference,
    reference_problem,
    remove_project_reference,
)
from .runtime import (
    bootstrap_runtime,
    delete_runtime,
    install_runtime,
    load_registry,
    register_runtime,
    unregister_runtime,
)


def python_main(arguments: list[str] | None = None) -> int:
    python_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        resolution = resolve(python_arguments)
        execute(python_arguments, resolution)
    except NodePhellError as error:
        print(f"nodephell: {error}", file=sys.stderr)
        return 2


def main(arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values or values[0] in {"-h", "--help"}:
        _print_help()
        return 0
    if values[0] in {"-V", "--version"}:
        print(f"NodePhell {__version__}")
        return 0
    try:
        if values[0] == "run":
            python_arguments = _without_separator(values[1:])
            resolution = resolve(python_arguments)
            execute(python_arguments, resolution)
        if values[0] == "resolve":
            python_arguments = _without_separator(values[1:])
            _print_resolution(resolve(python_arguments))
            return 0
        if values[0] == "install":
            return _install_command(values[1:])
        if values[0] == "lock":
            return _lock_command(values[1:], update=False)
        if values[0] == "update":
            return _lock_command(values[1:], update=True)
        if values[0] == "runtime":
            return _runtime_command(values[1:])
        if values[0] == "store":
            return _store_command(values[1:])
        if values[0] == "project":
            return _project_command(values[1:])
        if values[0] == "host":
            return _host_command(values[1:])
        if values[0] == "launcher":
            return _launcher_command(values[1:])
        if values[0] == "doctor":
            return _doctor_command(values[1:])
        raise NodePhellError(f"unknown command: {values[0]}")
    except NodePhellError as error:
        print(f"nodephell: {error}", file=sys.stderr)
        return 2


def _runtime_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add", help="register an installed interpreter")
    add.add_argument("executable", type=Path)
    add.add_argument(
        "--library-path",
        action="append",
        default=[],
        type=Path,
        help="shared-library directory needed to start this interpreter",
    )
    install = subparsers.add_parser(
        "install",
        help="download and register a compatible CPython runtime",
    )
    install.add_argument("requires_python", help="Python version requirement")
    remove = subparsers.add_parser("remove", help="unregister an interpreter")
    remove.add_argument("executable", type=Path)
    remove.add_argument(
        "--delete",
        action="store_true",
        help="also delete a NodePhell-managed interpreter",
    )
    subparsers.add_parser("list", help="list registered interpreters")
    options = parser.parse_args(arguments)

    if options.command == "add":
        runtime = register_runtime(
            options.executable,
            tuple(options.library_path),
        )
        print(f"registered {runtime.identifier}")
        print(runtime.executable)
        return 0

    if options.command == "install":
        runtime = install_runtime(
            options.requires_python,
            progress=lambda text: print(text, flush=True),
        )
        print(f"registered {runtime.identifier}")
        print(runtime.executable)
        return 0

    if options.command == "remove":
        if options.delete:
            runtime, path, existed = delete_runtime(options.executable)
            print(f"unregistered {runtime.identifier}")
            print(f"Deleted: {path}" if existed else f"Already absent: {path}")
            return 0
        runtime = unregister_runtime(options.executable)
        print(f"unregistered {runtime.identifier}")
        print(f"Files were not deleted: {runtime.executable}")
        return 0

    current = bootstrap_runtime()
    print(f"bootstrap\t{current.version}\t{current.executable}")
    for runtime in load_registry():
        libraries = os_path_list(runtime.library_paths)
        suffix = f"\t{libraries}" if libraries else ""
        print(
            f"registered\t{runtime.version}\t{runtime.executable}{suffix}"
        )
    return 0


def _host_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell host")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add", help="probe and register an embedded host")
    add.add_argument("executable", type=Path)
    add.add_argument(
        "--kind",
        help="adapter kind; inferred from the executable when omitted",
    )
    remove = subparsers.add_parser("remove", help="unregister an embedded host")
    remove.add_argument("executable", type=Path)
    remove.add_argument(
        "--delete",
        action="store_true",
        help="also delete a NodePhell-managed host",
    )
    subparsers.add_parser("list", help="list registered embedded hosts")
    subparsers.add_parser("adapters", help="list discovered host adapters")
    run = subparsers.add_parser("run", help="run a script through the project host")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    gui = subparsers.add_parser("gui", help="launch the project's graphical host")
    gui.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)

    if options.command == "add":
        host = register_host(options.executable, kind=options.kind)
        print(f"registered {host.identifier}")
        print(
            f"embedded {host.runtime.implementation} {host.runtime.version} "
            f"({host.runtime.abi})"
        )
        print(host.executable)
        return 0

    if options.command == "remove":
        if options.delete:
            host, path, existed = delete_host(options.executable)
            print(f"unregistered {host.identifier}")
            print(f"Deleted: {path}" if existed else f"Already absent: {path}")
            return 0
        host = unregister_host(options.executable)
        print(f"unregistered {host.identifier}")
        print(f"Files were not deleted: {host.executable}")
        return 0

    if options.command == "adapters":
        adapters = discover_adapters()
        if not adapters:
            print("No embedded-host adapters are installed.")
            return 0
        for adapter in adapters:
            print(f"{adapter.kind}\t{adapter.display_name}")
        return 0

    if options.command == "run":
        host_arguments = _without_separator(options.arguments)
        if not host_arguments:
            raise NodePhellError("host run requires a script or host argument")
        resolution = resolve_host(host_arguments)
        execute_host(host_arguments, resolution)

    if options.command == "gui":
        host_arguments = _without_separator(options.arguments)
        resolution = resolve_host(host_arguments)
        execute_host_gui(host_arguments, resolution)

    for host in load_hosts():
        print(
            f"{host.kind}\t{host.version}\tPython {host.runtime.version}\t"
            f"{host.runtime.abi}\t{host.executable}"
        )
    return 0


def _install_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell install")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    options = parser.parse_args(arguments)
    result = install_project(
        options.project,
        progress=lambda text: print(text, flush=True),
    )
    count = len(result.installed_packages)
    if count:
        noun = "release" if count == 1 else "releases"
        print(f"Installed {count} {noun} into the shared store.")
    else:
        print("All exact releases are already available.")
    print(f"Ready for {result.runtime.identifier}")
    if result.host is not None:
        print(f"Ready for {result.host.identifier}")
    return 0


def _lock_command(arguments: list[str], *, update: bool) -> int:
    command = "update" if update else "lock"
    parser = argparse.ArgumentParser(prog=f"nodephell {command}")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    options = parser.parse_args(arguments)
    result = lock_project(
        options.project,
        progress=lambda text: print(text, flush=True),
        update=update,
    )
    verb = "Updated" if update else "Created"
    print(f"{verb} {result.path}")
    print(f"Locked runtime: {result.runtime.identifier}")
    print("Run 'nodephell install' to supply the locked packages.")
    return 0


def _store_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell store")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "check",
        help="validate stored releases and package compositions",
    )
    clean = subparsers.add_parser(
        "clean",
        help="find invalid or abandoned store entries",
    )
    clean.add_argument(
        "--apply",
        action="store_true",
        help="remove the entries reported as safe cleanup candidates",
    )
    options = parser.parse_args(arguments)

    if options.command == "check":
        validation = validate_store()
        print(f"Checked {validation.checked_releases} stored releases.")
        if not validation.issues:
            print("The shared store is healthy.")
            return 0
        _print_store_issues(validation.issues)
        return 1

    result = clean_store(apply=options.apply)
    if not options.apply:
        if not result.candidates:
            print("No safe cleanup candidates found.")
        else:
            reasons = {
                issue.cleanup_path: issue.message
                for issue in result.issues
                if issue.cleanup_path is not None
            }
            for path in result.candidates:
                print(f"Would remove: {path} ({reasons[path]})")
            print("Run 'nodephell store clean --apply' to remove them.")
        unremovable = tuple(
            issue for issue in result.issues if issue.cleanup_path is None
        )
        if unremovable:
            _print_store_issues(unremovable)
        return 1 if result.issues else 0

    for path in result.removed:
        print(f"Removed: {path}")
    for path in result.skipped:
        print(f"In use, skipped: {path}")
    remaining = clean_store()
    if remaining.issues:
        _print_store_issues(remaining.issues)
        return 1
    print("The shared store is clean.")
    return 0


def _project_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell project")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list projects known to NodePhell")
    remove = subparsers.add_parser("remove", help="unregister a project")
    remove.add_argument(
        "project",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="project directory; defaults to the current directory",
    )
    move = subparsers.add_parser("move", help="update a moved project registration")
    move.add_argument("old", type=Path)
    move.add_argument("new", type=Path)
    options = parser.parse_args(arguments)

    if options.command == "remove":
        root = remove_project_reference(options.project)
        print(f"unregistered {root}")
        print("Shared packages were not deleted.")
        return 0

    if options.command == "move":
        reference = move_project_reference(options.old, options.new)
        print(f"moved registration to {reference.project_root}")
        return 0

    references, issues = inspect_project_references()
    if not references and not issues:
        print("No projects are registered.")
        return 0
    for reference in references:
        problem = reference_problem(reference)
        if problem is None:
            status = "current"
            detail = None
        else:
            detail, obsolete = problem
            if obsolete:
                status = "obsolete"
            elif detail.startswith("project lock changed;"):
                status = "changed"
            else:
                status = "unavailable"
        count = len(reference.releases)
        noun = "release" if count == 1 else "releases"
        print(f"{status}\t{reference.project_root}\t{count} shared {noun}")
        if detail is not None:
            print(f"  {detail}")
    for issue in issues:
        print(f"invalid\t{issue.path}")
        print(f"  {issue.message}")
    return 1 if issues else 0


def _launcher_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell launcher")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("install", help="install commands into the user PATH")
    subparsers.add_parser("uninstall", help="remove installed commands")
    options = parser.parse_args(arguments)
    if options.command == "install":
        change = install_launchers()
        for path in change.installed:
            print(f"Installed: {path}")
        for path in change.unchanged:
            print(f"Already installed: {path}")
        problem = path_problem()
        if problem is not None:
            print(f"PATH notice: {problem}")
        return 0
    change = uninstall_launchers()
    for path in change.removed:
        print(f"Removed: {path}")
    if not change.removed:
        print("No NodePhell launchers are installed.")
    print("Stored runtimes, hosts, packages, and project records were not removed.")
    return 0


def _doctor_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell doctor")
    parser.parse_args(arguments)
    problems = 0

    launcher_problem = path_problem()
    if launcher_problem is None:
        print("Launchers: available through PATH.")
    else:
        print(f"Problem: launchers: {launcher_problem}")
        problems += 1

    try:
        adapters = discover_adapters()
        print(f"Adapters: {len(adapters)} discovered.")
    except NodePhellError as error:
        print(f"Problem: adapter plugins: {error}")
        problems += 1

    for name, loader in (("runtimes", load_registry), ("hosts", load_hosts)):
        try:
            records = loader()
            print(f"{name.title()}: {len(records)} registered.")
        except NodePhellError as error:
            print(f"Problem: {name} registry: {error}")
            problems += 1

    references, reference_issues = inspect_project_references()
    project_problems: list[tuple[Path, str]] = [
        (issue.path, issue.message) for issue in reference_issues
    ]
    for reference in references:
        problem = reference_problem(reference)
        if problem is not None:
            project_problems.append((reference.project_root, problem[0]))
    print(f"Projects: {len(references)} registered.")
    for path, message in project_problems:
        print(f"Problem: projects: {path}: {message}")
    problems += len(project_problems)

    validation = validate_store()
    print(f"Store: checked {validation.checked_releases} releases.")
    for issue in validation.issues:
        print(f"Problem: store: {issue.path}: {issue.message}")
    problems += len(validation.issues)

    if problems:
        noun = "problem" if problems == 1 else "problems"
        print(f"Doctor found {problems} {noun}.")
        return 1
    print("Doctor found no problems.")
    return 0


def _print_store_issues(issues) -> None:
    for issue in issues:
        print(f"Problem: {issue.path}: {issue.message}")


def _print_resolution(resolution: Resolution) -> None:
    data = {
        "system_fallback": resolution.system_fallback,
        "project": (
            str(resolution.project.root) if resolution.project is not None else None
        ),
        "metadata": (
            str(resolution.project.metadata_file)
            if resolution.project is not None
            else None
        ),
        "host": (
            {
                "kind": resolution.project.host.kind,
                "requires": resolution.project.host.requires,
                "artifact": (
                    {
                        "version": resolution.project.host_artifact.version,
                        "platform": resolution.project.host_artifact.platform,
                        "name": resolution.project.host_artifact.name,
                        "url": resolution.project.host_artifact.url,
                        "sha256": resolution.project.host_artifact.sha256,
                    }
                    if resolution.project.host_artifact is not None
                    else None
                ),
            }
            if resolution.project is not None and resolution.project.host is not None
            else None
        ),
        "runtime": {
            "implementation": resolution.runtime.implementation,
            "version": resolution.runtime.version,
            "executable": str(resolution.runtime.executable),
            "abi": resolution.runtime.abi,
            "platform": resolution.runtime.platform,
            "library_paths": [
                str(path) for path in resolution.runtime.library_paths
            ],
            "artifact": (
                {
                    "name": resolution.runtime.artifact.name,
                    "url": resolution.runtime.artifact.url,
                    "platform": resolution.runtime.artifact.platform,
                    "sha256": resolution.runtime.artifact.sha256,
                }
                if resolution.runtime.artifact is not None
                else None
            ),
        },
        "package_paths": [str(path) for path in resolution.packages.paths],
        "ordinary_packages": [
            f"{package.name}=={package.version}"
            for package in resolution.packages.ordinary_packages
        ],
        "external_packages": [
            f"{package.name}=={package.version}"
            for package in resolution.packages.external_packages
        ],
    }
    print(json.dumps(data, indent=2))


def _without_separator(arguments: list[str]) -> list[str]:
    if arguments[:1] == ["--"]:
        return arguments[1:]
    return arguments


def os_path_list(paths: tuple[Path, ...]) -> str:
    return ":".join(str(path) for path in paths)


def _print_help() -> None:
    print(
        """usage: nodephell COMMAND [ARGUMENTS]

Commands:
  lock [PROJECT]             create a lock from pyproject.toml
  install [PROJECT]          install exactly what pylock.toml records
  update [PROJECT]           deliberately replace an existing lock
  run [--] PYTHON-ARGS       select and execute Python
  resolve [--] PYTHON-ARGS   show the selection without executing it
  runtime add PYTHON         register an installed Python runtime
  runtime install SPEC       download and register a compatible CPython runtime
  runtime remove [--delete] PYTHON
                              unregister or delete a managed runtime
  runtime list               list known Python runtimes
  store check                validate the shared package store
  store clean [--apply]      find or remove unusable store entries
  project list               list registered projects and their status
  project remove [PROJECT]   unregister a project without deleting packages
  project move OLD NEW       update a moved project registration
  launcher install           install commands under ~/.local/bin
  launcher uninstall         remove commands but preserve stored data
  host add [--kind KIND] EXECUTABLE
                              probe and register an embedded host
  host list                  list registered embedded hosts
  host adapters              list discovered adapter plugins
  host remove [--delete] EXECUTABLE
                              unregister or delete a managed host
  host run [--] HOST-ARGS    run through the project's embedded host
  host gui [--] HOST-ARGS    launch the project's graphical host
  doctor                     check launchers, registries, and shared storage

The separate 'python' shim passes all arguments directly to the selected
interpreter. Outside a project it delegates to the system interpreter.
"""
    )
