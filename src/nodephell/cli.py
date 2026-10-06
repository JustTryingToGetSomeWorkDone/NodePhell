# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .errors import NodePhellError
from .installer import install_project
from .launcher import Resolution, execute, resolve
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
        print(f"Installed {count} {noun} into the historical store.")
    else:
        print("All exact releases are already available.")
    print(f"Ready for {result.runtime.identifier}")
    return 0


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
        "runtime": {
            "implementation": resolution.runtime.implementation,
            "version": resolution.runtime.version,
            "executable": str(resolution.runtime.executable),
            "abi": resolution.runtime.abi,
            "platform": resolution.runtime.platform,
            "library_paths": [
                str(path) for path in resolution.runtime.library_paths
            ],
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

The separate 'python' shim passes all arguments directly to the selected
interpreter. Outside a project it delegates to the system interpreter.
"""
    )
