# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .errors import NodePhellError
from .host import (
    execute_host,
    execute_host_gui,
    load_hosts,
    register_host,
    resolve_host,
)
from .installer import install_project
from .launcher import Resolution, execute, resolve
from .maintenance import clean_store, validate_store
from .references import inspect_project_references, reference_problem
from .runtime import bootstrap_runtime, install_runtime, load_registry, register_runtime


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
        if values[0] == "runtime":
            return _runtime_command(values[1:])
        if values[0] == "store":
            return _store_command(values[1:])
        if values[0] == "project":
            return _project_command(values[1:])
        if values[0] == "host":
            return _host_command(values[1:])
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
    subparsers.add_parser("list", help="list registered embedded hosts")
    run = subparsers.add_parser("run", help="run a script through the project host")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    gui = subparsers.add_parser("gui", help="launch the project's graphical host")
    gui.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)

    if options.command == "add":
        host = register_host(options.executable)
        print(f"registered {host.identifier}")
        print(
            f"embedded {host.runtime.implementation} {host.runtime.version} "
            f"({host.runtime.abi})"
        )
        print(host.executable)
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
    parser.parse_args(arguments)

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
            status = "missing" if obsolete else "changed"
        count = len(reference.releases)
        noun = "release" if count == 1 else "releases"
        print(f"{status}\t{reference.project_root}\t{count} shared {noun}")
        if detail is not None:
            print(f"  {detail}")
    for issue in issues:
        print(f"invalid\t{issue.path}")
        print(f"  {issue.message}")
    return 1 if issues else 0


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
  install [PROJECT]          install missing exact releases with stock pip
  run [--] PYTHON-ARGS       select and execute Python
  resolve [--] PYTHON-ARGS   show the selection without executing it
  runtime add PYTHON         register an installed Python runtime
  runtime install SPEC       download and register a compatible CPython runtime
  runtime list               list known Python runtimes
  store check                validate the shared package store
  store clean [--apply]      find or remove unusable store entries
  project list               list registered projects and their status
  host add EXECUTABLE        probe and register FreeCADCmd
  host list                  list registered embedded hosts
  host run [--] HOST-ARGS    run through the project's embedded host
  host gui [--] HOST-ARGS    launch the project's graphical host

The separate 'python' shim passes all arguments directly to the selected
interpreter. Outside a project it delegates to the system interpreter.
"""
    )
