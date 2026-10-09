# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import sys

from . import __version__
from .activity import TerminalProgress, activity
from .applications import (
    ApplicationCandidate,
    application_problem,
    application_project_root,
    apply_application,
    discover_application_candidates,
    get_application,
    install_declared_application,
    load_applications,
    move_application_projects,
    plan_application,
    plan_declared_application,
    remove_application,
)
from .errors import NodePhellError, highlight_detail, print_error, print_warning
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
from .initializer import initialize_project
from .installer import install_project, lock_project, sync_project
from .launcher import Resolution, execute, resolve
from .launchers import (
    configure_shell_path,
    install_launchers,
    install_package_launchers,
    path_problem,
    remove_shell_path,
    uninstall_launchers,
)
from .maintenance import clean_store, remove_unused_releases, validate_store
from .plugins import add_plugin, remove_plugin, scan_plugins
from .project_options import (
    inspect_project_options,
    release_label,
    update_project_options,
)
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
from .store import stored_release_path
from .troubleshooting import suggested_project_commands, troubleshoot_project


_PROGRESS = TerminalProgress()


def python_main(arguments: list[str] | None = None) -> int:
    python_arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        resolution = resolve(python_arguments)
        execute(python_arguments, resolution)
    except NodePhellError as error:
        print_error(error)
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
        if values[0] == "init":
            return _init_command(values[1:])
        if values[0] == "sync":
            return _sync_command(values[1:])
        if values[0] == "options":
            return _options_command(values[1:])
        if values[0] == "troubleshoot":
            return _troubleshoot_command(values[1:])
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
        if values[0] == "app":
            return _application_command(values[1:])
        if values[0] == "plugin":
            return _plugin_command(values[1:])
        if values[0] == "launcher":
            return _launcher_command(values[1:])
        if values[0] == "doctor":
            return _doctor_command(values[1:])
        raise NodePhellError(f"unknown command: {values[0]}")
    except NodePhellError as error:
        print_error(error)
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
            progress=_PROGRESS,
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
    inspect = subparsers.add_parser(
        "resolve", help="show embedded-host selection without launching it"
    )
    inspect.add_argument("arguments", nargs=argparse.REMAINDER)
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

    if options.command == "resolve":
        host_arguments = _without_separator(options.arguments)
        resolution = resolve_host(host_arguments)
        _print_resolution(resolution.project, resolution.host)
        return 0

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


def _application_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser(
        "add",
        help="configure an embedded application and create its launcher",
    )
    add.add_argument("executable", nargs="?", type=Path)
    add.add_argument("--project", type=Path)
    add.add_argument("--name", help="launcher name; defaults to the adapter name")
    add.add_argument("-y", "--yes", action="store_true")
    subparsers.add_parser("list", help="list configured applications")
    refresh = subparsers.add_parser(
        "refresh",
        help="re-probe and synchronize a configured application",
    )
    refresh.add_argument("name")
    refresh.add_argument("--executable", type=Path)
    refresh.add_argument("--project", type=Path)
    refresh.add_argument("-y", "--yes", action="store_true")
    remove = subparsers.add_parser(
        "remove",
        help="remove an application launcher and registration",
    )
    remove.add_argument("name")
    options = parser.parse_args(arguments)

    if options.command == "list":
        applications = load_applications()
        if not applications:
            print("No applications are configured.")
            return 0
        for application in applications:
            print(
                f"{application.name}\t{application.kind}\t"
                f"{application.project_root}\t{application.executable}"
            )
        return 0

    if options.command == "remove":
        application, launcher = remove_application(options.name)
        print(f"Removed application: {application.name}")
        for path in launcher.removed:
            print(f"Removed launcher: {path}")
        print("The project, host, and shared packages were not removed.")
        return 0

    if options.command == "refresh":
        existing = get_application(options.name)
        project = application_project_root(
            options.project or existing.project_root
        )
        executable = options.executable or existing.executable
        plan = plan_application(
            executable,
            project,
            existing.name,
            replace=True,
        )
        _print_application_plan(plan, action="Refresh")
        if not options.yes:
            _confirm_application("Refresh this application? [Y/n]: ")
        setup = apply_application(
            plan,
            progress=_PROGRESS,
        )
        _print_sync(setup.sync)
        _print_application_ready(setup)
        return 0

    project = application_project_root(options.project)
    executable = _select_application_executable(
        options.executable,
        project,
        assume_yes=options.yes,
    )
    plan = plan_application(executable, project, options.name)
    _print_application_plan(plan, action="Configure")
    if not options.yes:
        _confirm_application("Configure this application? [Y/n]: ")
    setup = apply_application(
        plan,
        progress=_PROGRESS,
    )
    _print_sync(setup.sync)
    _print_application_ready(setup)
    return 0


def _plugin_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell plugin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add", help="link a local adapter plugin")
    add.add_argument("source", type=Path)
    scan = subparsers.add_parser(
        "scan",
        help="install plugins dropped into a directory",
    )
    scan.add_argument("directory", nargs="?", type=Path)
    subparsers.add_parser("list", help="list discovered adapter plugins")
    remove = subparsers.add_parser(
        "remove",
        help="remove a locally linked adapter plugin",
    )
    remove.add_argument("kind")
    options = parser.parse_args(arguments)

    if options.command == "add":
        change = add_plugin(options.source)
        verb = "Installed" if change.installed else "Already installed"
        print(f"{verb}: {change.adapter.kind} ({change.adapter.display_name})")
        print(change.path)
        return 0
    if options.command == "remove":
        path = remove_plugin(options.kind)
        print(f"Removed plugin link: {path}")
        print("The plugin source, applications, hosts, and packages were not removed.")
        return 0
    if options.command == "scan":
        result = scan_plugins(options.directory)
        print(f"Plugin directory: {highlight_detail(result.directory, sys.stdout)}")
        if not result.changes and not result.issues:
            print(f"No plugin projects found in {result.directory}")
            return 0
        for change in result.changes:
            verb = "Installed" if change.installed else "Already installed"
            print(f"{verb}: {change.adapter.kind} ({change.adapter.display_name})")
        for issue in result.issues:
            print_error(NodePhellError(f"{issue.source}: {issue.message}"))
        return 2 if result.issues else 0
    adapters = discover_adapters()
    if not adapters:
        print("No adapter plugins are installed.")
        return 0
    for adapter in adapters:
        print(f"{adapter.kind}\t{adapter.display_name}")
    return 0


def _select_application_executable(
    explicit: Path | None,
    project: Path,
    *,
    assume_yes: bool,
) -> Path:
    if explicit is not None:
        return explicit
    candidates = discover_application_candidates(project)
    if len(candidates) == 1:
        candidate = candidates[0]
        print(
            f"Found {candidate.adapter.display_name}: "
            f"{highlight_detail(candidate.executable, sys.stdout)}"
        )
        return candidate.executable
    if len(candidates) > 1:
        _print_application_candidates(candidates)
        if assume_yes:
            raise NodePhellError(
                "multiple application executables were found; "
                "pass the intended path"
            )
        while True:
            answer = _read_answer(
                f"Select an executable [1-{len(candidates)}]: "
            ).strip()
            try:
                selected = int(answer)
            except ValueError:
                selected = 0
            if 1 <= selected <= len(candidates):
                return candidates[selected - 1].executable
            print("Enter one of the displayed numbers.")
    if assume_yes:
        raise NodePhellError(
            "no application executable was found; pass its path"
        )
    answer = _read_answer("Application executable path: ").strip()
    if not answer:
        raise NodePhellError("application setup cancelled")
    return Path(answer).expanduser()


def _print_application_candidates(
    candidates: tuple[ApplicationCandidate, ...],
) -> None:
    print("Found multiple application executables:")
    for index, candidate in enumerate(candidates, start=1):
        print(
            f"  {index}. {candidate.adapter.display_name}: "
            f"{highlight_detail(candidate.executable, sys.stdout)}"
        )


def _print_application_plan(plan, *, action: str) -> None:
    application = plan.application
    print(f"{action}: {application.name}")
    print(f"Application: {plan.host.kind} {plan.host.version}")
    print(
        f"Embedded Python: {plan.host.runtime.version} "
        f"({plan.host.runtime.abi})"
    )
    print(
        "Entry executable: "
        f"{highlight_detail(application.executable, sys.stdout)}"
    )
    print(f"Project: {highlight_detail(application.project_root, sys.stdout)}")
    print(f"Launcher: {highlight_detail(plan.launcher, sys.stdout)}")
    if plan.project_update:
        print("The project host requirement and lock will be updated.")
    else:
        print("The project already declares this host requirement.")


def _print_application_ready(setup) -> None:
    launcher = setup.launcher.installed or setup.launcher.unchanged
    path = launcher[0] if launcher else setup.application.name
    print(f"Application ready: {setup.application.name}")
    print(f"Run it with: {highlight_detail(path, sys.stdout)}")


def _confirm_application(prompt: str) -> None:
    answer = _read_answer(prompt).strip().lower()
    if answer not in {"", "y", "yes"}:
        raise NodePhellError("application setup cancelled")


def _read_answer(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError as error:
        raise NodePhellError("application setup cancelled") from error


def _install_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell install")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="list every package-command launcher change",
    )
    options = parser.parse_args(arguments)
    declared = plan_declared_application(options.project)
    if declared is not None:
        _print_declared_plugin(declared)
        setup = install_declared_application(
            declared,
            progress=_PROGRESS,
        )
        _print_installation(setup.installation, verbose=options.verbose)
        _print_application_ready(setup)
    else:
        result = install_project(
            options.project,
            progress=_PROGRESS,
        )
        _print_installation(result, verbose=options.verbose)
    return 0


def _init_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell init")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    options = parser.parse_args(arguments)
    path = initialize_project(options.project)
    print(f"Created {path}")
    result = sync_project(
        path.parent,
        progress=_PROGRESS,
    )
    _print_sync(result)
    return 0


def _sync_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell sync")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    options = parser.parse_args(arguments)
    declared = plan_declared_application(options.project)
    if declared is not None:
        _print_declared_plugin(declared)
        setup = apply_application(
            declared.application,
            progress=_PROGRESS,
        )
        _print_sync(setup.sync)
        _print_application_ready(setup)
    else:
        result = sync_project(
            options.project,
            progress=_PROGRESS,
        )
        _print_sync(result)
    return 0


def _troubleshoot_command(arguments: list[str]) -> int:
    command: tuple[str, ...] = ()
    if "--" in arguments:
        separator = arguments.index("--")
        command = tuple(arguments[separator + 1 :])
        arguments = arguments[:separator]
        if not command:
            raise NodePhellError(
                "no command follows '--'",
                guidance=(
                    "Add the command that reproduces the failure, for example "
                    "'nodephell troubleshoot -- frogmouth --help'."
                ),
            )
    parser = argparse.ArgumentParser(prog="nodephell troubleshoot")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    options = parser.parse_args(arguments)
    if not command:
        command = _ask_troubleshoot_command(options.project)

    def confirm_keep(runtime) -> bool:
        try:
            answer = input(
                f"The command works with Python {runtime.version}. "
                "Keep this generated lock? [y/N]: "
            ).strip().lower()
        except EOFError:
            print("No confirmation was available; restoring the original lock.")
            return False
        return answer in {"y", "yes"}

    result = troubleshoot_project(
        command,
        options.project,
        progress=_PROGRESS,
        keep_trial=confirm_keep,
    )
    if result.baseline_status == 0:
        runtime = result.original_runtime or "the currently selected runtime"
        print(f"The command succeeded with {runtime}; no fallback was needed.")
        return 0
    if result.trial_status == 0:
        if result.kept:
            print(f"Kept the working Python {result.trial_runtime} lock.")
            print(
                "Next action: run the project's normal tests, then commit "
                "pylock.toml."
            )
        else:
            print(
                f"Python {result.trial_runtime} fixed the smoke command; "
                "the original lock was restored."
            )
            print(
                "Next action: rerun troubleshoot and confirm the working lock, or "
                "bound requires-python to the verified Python line and run "
                "nodephell sync."
            )
        return 0
    print(
        f"Python {result.trial_runtime} did not fix the command "
        f"(status {result.trial_status}); the original lock was restored."
    )
    print(
        "Next action: inspect the traceback above and check the failing package's "
        "supported Python and dependency versions. After correcting pyproject.toml, "
        "run nodephell sync and retry the command."
    )
    return 1


def _ask_troubleshoot_command(project: Path | None) -> tuple[str, ...]:
    suggestions = suggested_project_commands(project)
    default = None
    if len(suggestions) == 1:
        default = (suggestions[0], "--help")
        prompt = f"Smoke command [{shlex.join(default)}]: "
    elif suggestions:
        print("Project commands:")
        for index, name in enumerate(suggestions, start=1):
            print(f"  {index}. {name} --help")
        prompt = "Smoke command (number or full command): "
    else:
        prompt = "Smoke command (for example, python -c 'import package'): "
    try:
        answer = input(prompt).strip()
    except EOFError as error:
        raise NodePhellError(
            "no interactive smoke command was available",
            guidance=(
                "Rerun with the exact command after '--', for example "
                "'nodephell troubleshoot -- python -c \"import package\"'."
            ),
        ) from error
    if not answer and default is not None:
        return default
    if answer.isdigit() and suggestions:
        index = int(answer)
        if 1 <= index <= len(suggestions):
            return (suggestions[index - 1], "--help")
        raise NodePhellError(
            f"project command number is out of range: {answer}",
            guidance=(
                f"Enter a number from 1 through {len(suggestions)}, or a full "
                "command."
            ),
        )
    if not answer:
        raise NodePhellError(
            "no smoke command was provided",
            guidance=(
                "Enter a command that reproduces the problem, or rerun with the "
                "command after '--'."
            ),
        )
    try:
        parsed = tuple(shlex.split(answer))
    except ValueError as error:
        raise NodePhellError(
            f"cannot parse smoke command: {error}",
            guidance="Correct the shell quoting and enter the command again.",
        ) from error
    if not parsed:
        raise NodePhellError(
            "no smoke command was provided",
            guidance="Enter an executable followed by any arguments, then retry.",
        )
    return parsed


def _options_command(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="nodephell options")
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        help="project directory; defaults to the current directory",
    )
    options = parser.parse_args(arguments)
    project = inspect_project_options(options.project)
    choices = _option_choices(project)
    if not choices:
        print("This project declares no optional features or dependency groups.")
        return 0

    selected_extras = set(project.selected_extras)
    selected_groups = set(project.selected_groups)
    applied_extras = set(selected_extras)
    applied_groups = set(selected_groups)
    while True:
        _print_option_choices(
            choices,
            selected_extras,
            selected_groups,
            applied_extras,
            applied_groups,
        )
        answer = _read_option_answer(
            "Enter numbers to toggle, A to apply, Q to quit, "
            "or Esc to cancel: "
        )
        if answer == "\x1b":
            if (
                selected_extras != applied_extras
                or selected_groups != applied_groups
            ):
                print("Unapplied changes cancelled.")
            else:
                print("No pending changes.")
            return 0
        if answer in {"q", "quit"}:
            if (
                selected_extras != applied_extras
                or selected_groups != applied_groups
            ):
                print("Quit without applying the pending changes.")
            return 0
        if answer in {"a", "apply"}:
            if (
                selected_extras == applied_extras
                and selected_groups == applied_groups
            ):
                print("There are no pending changes to apply.")
                continue
            try:
                result = update_project_options(
                    project.root,
                    tuple(sorted(selected_extras)),
                    tuple(sorted(selected_groups)),
                    progress=_PROGRESS,
                )
            except NodePhellError as error:
                print_error(error)
                print(
                    "Nothing was applied. The pending choices remain marked."
                )
                if not _pause_after_option_error():
                    return 0
                continue
            print(f"Updated {result.lock.path}")
            print(f"Locked runtime: {result.lock.runtime.identifier}")
            _print_installation(
                result.installation,
                install_commands=result.dependencies_changed,
            )
            _print_option_changes(
                applied_extras,
                selected_extras,
                applied_groups,
                selected_groups,
            )
            _offer_option_cleanup(result)
            project = result.project
            choices = _option_choices(project)
            applied_extras = set(project.selected_extras)
            applied_groups = set(project.selected_groups)
            selected_extras = set(applied_extras)
            selected_groups = set(applied_groups)
            if not choices:
                print("This project declares no more configurable options.")
                return 0
            continue
        if not answer:
            print_warning("enter option numbers, A to apply, or Q to quit")
            continue
        try:
            numbers = {
                int(value)
                for value in answer.replace(",", " ").split()
            }
        except ValueError:
            print_warning("enter option numbers separated by spaces")
            continue
        if not numbers or min(numbers) < 1 or max(numbers) > len(choices):
            print_warning(f"choose numbers from 1 through {len(choices)}")
            continue
        for number in numbers:
            kind, choice = choices[number - 1]
            selected = selected_extras if kind == "extra" else selected_groups
            if choice.name in selected:
                selected.remove(choice.name)
            else:
                selected.add(choice.name)


def _option_choices(project) -> tuple:
    return tuple(
        [("extra", option) for option in project.optional_dependencies]
        + [("group", option) for option in project.dependency_groups]
    )


def _print_option_choices(
    choices,
    selected_extras,
    selected_groups,
    applied_extras,
    applied_groups,
) -> None:
    print("\nProject options\n")
    previous_kind = None
    for index, (kind, choice) in enumerate(choices, start=1):
        if kind != previous_kind:
            print("Optional features:" if kind == "extra" else "Dependency groups:")
            previous_kind = kind
        selected = selected_extras if kind == "extra" else selected_groups
        applied = applied_extras if kind == "extra" else applied_groups
        mark = "x" if choice.name in selected else " "
        detail = _option_detail(choice)
        pending = " (pending)" if (choice.name in selected) != (
            choice.name in applied
        ) else ""
        print(f" {index:>2}. [{mark}] {choice.name}{pending}{detail}")
    print()


def _option_detail(choice) -> str:
    if not choice.available:
        return " — no longer declared; deselect to continue"
    count = len(choice.requirements)
    if choice.includes:
        groups = ", ".join(choice.includes)
        included = f"; includes {groups}"
    else:
        included = ""
    if count == 0 and not included:
        return " — no additional packages"
    if count == 0:
        dependency = ""
    elif count <= 3:
        names = ", ".join(
            _requirement_display_name(value) for value in choice.requirements
        )
        dependency = f"adds {names}"
    elif choice.includes:
        dependency = f"adds {count} direct dependencies"
    else:
        dependency = f"adds {count} dependencies"
    separator = "; " if dependency and included else ""
    return f" — {dependency}{separator}{included.removeprefix('; ')}"


def _requirement_display_name(value: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", value.strip())
    return match.group(0) if match is not None else value


def _print_option_changes(
    old_extras: set[str],
    new_extras: set[str],
    old_groups: set[str],
    new_groups: set[str],
) -> None:
    enabled = sorted((new_extras - old_extras) | (new_groups - old_groups))
    disabled = sorted((old_extras - new_extras) | (old_groups - new_groups))
    if enabled:
        print(f"Enabled: {', '.join(enabled)}")
    if disabled:
        print(f"Disabled: {', '.join(disabled)}")


def _offer_option_cleanup(result) -> None:
    for release in result.used_elsewhere:
        noun = "project" if release.project_count == 1 else "projects"
        print(
            f"Kept {release_label(release.path)} — used by "
            f"{release.project_count} other {noun}."
        )
    for path in result.uncertain_releases:
        print_warning(
            f"kept {release_label(path)} because project registrations "
            "could not all be verified"
        )
    if not result.unused_releases:
        return
    count = len(result.unused_releases)
    noun = "release" if count == 1 else "releases"
    verb = "is" if count == 1 else "are"
    print(
        f"{count} {noun} {verb} no longer selected and remain in the shared store."
    )
    answer = _read_option_answer(f"Remove the safely unused {noun}? [y/N]: ")
    if answer not in {"y", "yes"}:
        print("Shared releases were not deleted.")
        return
    with activity("Rechecking use and removing unused releases"):
        cleanup = remove_unused_releases(result.unused_releases)
    for path in cleanup.removed:
        print(f"Removed: {release_label(path)}")
    for path in cleanup.skipped:
        print(f"Kept after safety recheck: {release_label(path)}")


def _read_option_answer(prompt: str) -> str:
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _read_terminal_answer(prompt)
    except (AttributeError, OSError):
        pass
    try:
        return input(prompt).strip().lower()
    except EOFError as error:
        raise NodePhellError("interactive option selection was cancelled") from error


def _pause_after_option_error() -> bool:
    while True:
        answer = _read_option_answer(
            "Press Enter to return to the options, Q to quit, "
            "or Esc to cancel: "
        )
        if answer in {"\x1b", "q", "quit"}:
            return False
        if not answer:
            return True
        print_warning("press Enter to continue, Q to quit, or Esc to cancel")


def _read_terminal_answer(prompt: str) -> str:
    try:
        import termios
        import tty

        descriptor = sys.stdin.fileno()
        previous = termios.tcgetattr(descriptor)
    except (ImportError, OSError, ValueError):
        return input(prompt).strip().lower()

    characters: list[str] = []
    print(prompt, end="", flush=True)
    try:
        tty.setcbreak(descriptor)
        while True:
            character = sys.stdin.read(1)
            if not character:
                raise NodePhellError(
                    "interactive option selection was cancelled"
                )
            if character == "\x1b":
                print()
                return character
            if character in {"\n", "\r"}:
                print()
                return "".join(characters).strip().lower()
            if character in {"\x08", "\x7f"}:
                if characters:
                    characters.pop()
                    print("\b \b", end="", flush=True)
                continue
            if character == "\x04":
                raise NodePhellError("interactive option selection was cancelled")
            if character.isprintable():
                characters.append(character)
                print(character, end="", flush=True)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def _print_declared_plugin(declared) -> None:
    change = declared.plugin
    verb = "Installed" if change.installed else "Using"
    print(
        f"{verb} project plugin: {change.adapter.kind} "
        f"({change.adapter.display_name})"
    )


def _print_sync(result) -> None:
    if result.lock is None:
        print("Lock already matches pyproject.toml.")
    else:
        verb = "Updated" if result.lock.updated else "Created"
        print(f"{verb} {result.lock.path}")
        print(f"Locked runtime: {result.lock.runtime.identifier}")
    _print_installation(result.installation)


def _print_installation(
    result,
    *,
    verbose: bool = False,
    install_commands: bool = True,
) -> None:
    count = len(result.installed_packages)
    if count:
        noun = "release" if count == 1 else "releases"
        print(f"Installed {count} {noun} into the shared store.")
    else:
        print("All exact releases are already available.")
    print(f"Ready for {result.runtime.identifier}")
    selection = getattr(result, "selection", None)
    if selection is not None and selection.project_package is not None:
        package = selection.project_package
        print(f"Editable project ready: {package.name}=={package.version}")
    if result.host is not None:
        print(f"Ready for {result.host.identifier}")
    if not install_commands:
        return
    launchers = install_package_launchers(result.commands)
    if launchers.installed:
        directory = launchers.installed[0].parent
        noun = "command" if len(launchers.installed) == 1 else "commands"
        print(
            f"Installed {len(launchers.installed)} package {noun} in "
            f"{highlight_detail(directory, sys.stdout)}."
        )
    if verbose:
        for path in launchers.installed:
            print(f"  installed: {highlight_detail(path.name, sys.stdout)}")
        for path in launchers.skipped:
            print(f"  kept existing: {highlight_detail(path.name, sys.stdout)}")
    if launchers.skipped:
        directory = launchers.skipped[0].parent
        noun = "command" if len(launchers.skipped) == 1 else "commands"
        pronoun = "it" if len(launchers.skipped) == 1 else "them"
        print_warning(
            f"kept {len(launchers.skipped)} existing package {noun} in "
            f"{directory} rather than replacing {pronoun}. The project is ready. "
            "Run 'nodephell install --verbose' to list the names."
        )


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
        progress=_PROGRESS,
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
        with activity("Checking the shared store"):
            validation = validate_store()
        print(f"Checked {validation.checked_releases} stored releases.")
        if not validation.issues:
            print("The shared store is healthy.")
            return 0
        _print_store_issues(validation.issues)
        return 1

    message = (
        "Checking and cleaning the shared store"
        if options.apply
        else "Looking for safe cleanup candidates"
    )
    with activity(message):
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
    with activity("Verifying the cleaned shared store"):
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
        applications = move_application_projects(options.old, options.new)
        if applications:
            noun = "application" if applications == 1 else "applications"
            print(f"updated {applications} bound {noun}")
            print(
                "Refresh any bound application whose entry executable moved."
            )
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
    install = subparsers.add_parser(
        "install", help="install commands into the user PATH"
    )
    shell_setup = install.add_mutually_exclusive_group()
    shell_setup.add_argument(
        "--configure-shell",
        action="store_true",
        help="put the launcher directory first in Bash startup",
    )
    shell_setup.add_argument(
        "--no-configure-shell",
        action="store_true",
        help="do not offer to change Bash startup",
    )
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
            if not options.configure_shell and not options.no_configure_shell:
                if sys.stdin.isatty():
                    answer = _read_shell_answer(
                        "Put ~/.local/bin first in ~/.bashrc? [Y/n]: "
                    )
                    options.configure_shell = answer in {"", "y", "yes"}
                else:
                    print(
                        "Run 'nodephell launcher install --configure-shell' "
                        "to configure Bash automatically."
                    )
        if options.configure_shell:
            shell_change = configure_shell_path()
            verb = "Updated" if shell_change.changed else "Already configured"
            print(f"{verb}: {shell_change.path}")
            _print_new_shell_instructions()
        return 0
    change = uninstall_launchers()
    for path in change.removed:
        print(f"Removed: {path}")
    if not change.removed:
        print("No NodePhell launchers are installed.")
    shell_change = remove_shell_path()
    if shell_change.changed:
        print(f"Removed PATH setup from: {shell_change.path}")
    print(
        "Application records, runtimes, hosts, packages, and project records "
        "were not removed."
    )
    return 0


def _read_shell_answer(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "no"


def _print_new_shell_instructions() -> None:
    print("Close this terminal and open a new one to use NodePhell's commands.")
    print("To update this terminal instead, run:")
    print("  source ~/.bashrc")
    print("  hash -r")


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

    try:
        applications = load_applications()
        application_problems = tuple(
            (application, application_problem(application))
            for application in applications
        )
        application_problems = tuple(
            (application, problem)
            for application, problem in application_problems
            if problem is not None
        )
        print(f"Applications: {len(applications)} configured.")
        for application, problem in application_problems:
            print(f"Problem: applications: {application.name}: {problem}")
        problems += len(application_problems)
    except NodePhellError as error:
        print(f"Problem: applications registry: {error}")
        problems += 1

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


def _print_resolution(resolution: Resolution, selected_host=None) -> None:
    ordinary = set(resolution.packages.ordinary_packages)
    external = set(resolution.packages.external_packages)
    package_selections = []
    if resolution.project is not None:
        for package in resolution.project.packages:
            if package in ordinary:
                provider = "selected-runtime"
                path = None
            elif package in external:
                provider = "external-host"
                path = None
            else:
                provider = "managed-store"
                path = str(
                    stored_release_path(
                        package,
                        resolution.runtime,
                        resolution.user_home,
                    )
                )
            package_selections.append(
                {
                    "name": package.name,
                    "version": package.version,
                    "provider": provider,
                    "path": path,
                }
            )
    if resolution.system_fallback:
        runtime_provider = "system-fallback"
    elif resolution.project.runtime_artifact is not None:
        runtime_provider = "locked-artifact"
    elif resolution.runtime.executable == bootstrap_runtime().executable:
        runtime_provider = "bootstrap-compatible"
    else:
        runtime_provider = "registered-compatible"
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
            "provider": runtime_provider,
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
        "selected_host": (
            {
                "kind": selected_host.kind,
                "version": selected_host.version,
                "executable": str(selected_host.executable),
                "python": selected_host.runtime.version,
                "abi": selected_host.runtime.abi,
                "package_roots": [
                    str(path) for path in selected_host.package_roots
                ],
            }
            if selected_host is not None
            else None
        ),
        "package_paths": [str(path) for path in resolution.packages.paths],
        "project_paths": [
            str(path) for path in resolution.packages.project_paths
        ],
        "project_package": (
            {
                "name": resolution.packages.project_package.name,
                "version": resolution.packages.project_package.version,
            }
            if resolution.packages.project_package is not None
            else None
        ),
        "selected_options": (
            {
                "extras": list(resolution.project.selected_extras),
                "groups": list(resolution.project.selected_groups),
            }
            if resolution.project is not None
            else None
        ),
        "package_selections": package_selections,
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
  init [PROJECT]             create and prepare a project interactively
  sync [PROJECT]             update when needed, then install the lock
  options [PROJECT]          select optional features and dependency groups
  troubleshoot [PROJECT]     test a failing command on the declared Python floor
  lock [PROJECT]             create a lock from pyproject.toml
  install [-v] [PROJECT]     install exactly what pylock.toml records
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
  launcher install           install commands and offer Bash PATH setup
  launcher uninstall         remove commands but preserve stored data
  host add [--kind KIND] EXECUTABLE
                              probe and register an embedded host
  host list                  list registered embedded hosts
  host adapters              list discovered adapter plugins
  host resolve [--] HOST-ARGS
                              show host and package selection without launching
  host remove [--delete] EXECUTABLE
                              unregister or delete a managed host
  host run [--] HOST-ARGS    run through the project's embedded host
  host gui [--] HOST-ARGS    launch the project's graphical host
  app add [EXECUTABLE]       configure an application and create its launcher
  app list                   list configured application launchers
  app refresh NAME           re-probe and synchronize an application
  app remove NAME            remove its launcher and registration
  plugin add PATH            link a local adapter plugin
  plugin scan [DIRECTORY]    install plugins dropped into a directory
  plugin list                list discovered adapter plugins
  plugin remove KIND         remove a locally linked adapter
  doctor                     check launchers, registries, and shared storage

The separate 'python' shim passes all arguments directly to the selected
interpreter. Outside a project it delegates to the system interpreter.
"""
    )
