# SPDX-License-Identifier: GPL-3.0-only

"""Interactive inventory and maintenance using the existing guarded operations."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import sys

from .errors import NodePhellError
from .host import delete_host, host_store, load_hosts, probe_host, unregister_host
from .maintenance import clean_store, remove_unused_releases, validate_store
from .references import inspect_project_references, reference_problem, remove_project_reference
from .runtime import (
    delete_runtime, interpreter_store, load_registry, probe_runtime, unregister_runtime,
)
from .store import package_store


def parse_selection(value: str, count: int) -> tuple[int, ...]:
    """Return zero-based row indices, validating bounds before expanding ranges."""
    if value.strip().lower() in {"a", "all"}:
        return tuple(range(count))
    selected: set[int] = set()
    try:
        for token in value.replace(",", " ").split():
            ends = token.split("-")
            if len(ends) == 1:
                first = last = int(ends[0])
            elif len(ends) == 2:
                first, last = map(int, ends)
            else:
                raise ValueError
            if not 1 <= first <= last <= count:
                raise ValueError
            selected.update(range(first - 1, last))
    except ValueError as error:
        raise NodePhellError(f"choose numbers from 1 to {count}, ranges, or 'all'") from error
    return tuple(sorted(selected))


def _select(rows, ask, say):
    if not rows:
        say("No entries found.")
        return ()
    for number, (path, label) in enumerate(rows, 1):
        say(f"  {number}. {label}\n     {path}")
    while True:
        value = ask("Select numbers (e.g. 1,3-5), 'all', or Enter to go back: ").strip()
        if value.lower() in {"", "b", "q"}:
            return ()
        try:
            return parse_selection(value, len(rows))
        except NodePhellError as error:
            say(str(error))


def _confirm(action, paths, ask, say):
    say(f"{action}:")
    for path in paths:
        say(f"  {path}")
    return ask("Proceed? [y/N]: ").strip().lower() in {"y", "yes"}


def _references(home, say):
    references, issues = inspect_project_references(home)
    for issue in issues:
        say(f"Project record problem: {issue.path}: {issue.message}")
    return references, issues


def _availability(executable, library_paths=()):
    if not executable.is_file():
        return "missing executable"
    if not os.access(executable, os.X_OK):
        return "not executable"
    if any(not path.is_dir() for path in library_paths):
        return "missing library directory"
    return "present (not probed)"


def _registry_menu(kind, home, ask, say):
    runtime_menu = kind == "runtime"
    entries = (
        load_registry(home, require_executables=False) if runtime_menu
        else load_hosts(home, require_executables=False)
    )
    references, reference_issues = _references(home, say)
    rows = []
    for entry in entries:
        runtime = entry if runtime_menu else entry.runtime
        identity = (runtime.implementation, runtime.version, runtime.abi, runtime.platform)
        users = sum(reference.runtime_identity == identity for reference in references)
        usage = "usage unknown" if reference_issues else f"runtime referenced by {users} project(s)"
        ownership = "managed" if entry.artifact is not None else "external"
        status = _availability(entry.executable, runtime.library_paths)
        rows.append((entry.executable, f"{entry.identifier}: {status}; {ownership}; {usage}"))
    selected = _select(rows, ask, say)
    if not selected:
        return
    action = ask("[u] Unregister only, [d] Delete managed files, [p] Probe, [b] Back: ").strip().lower()
    if action not in {"u", "d", "p"}:
        return
    chosen = [entries[index] for index in selected]
    if action == "p":
        for entry in chosen:
            say(f"Checking {entry.executable}...")
            try:
                result = (
                    probe_runtime(entry.executable, entry.library_paths) if runtime_menu
                    else probe_host(entry.executable, kind=entry.kind)
                )
                say(f"Available: {result.identifier}")
            except NodePhellError as error:
                say(f"Unavailable: {error}")
        return
    targets = []
    eligible = []
    for entry in chosen:
        target = entry.executable
        if action == "d":
            if entry.artifact is None:
                say(f"Cannot delete external {kind}; use unregister: {entry.executable}")
                continue
            target = (
                interpreter_store(entry.version, entry.abi, home, entry.artifact)
                if runtime_menu else host_store(entry.artifact, home)
            ).resolve(strict=False)
            if not entry.executable.is_relative_to(target):
                say(f"Cannot delete {kind} outside its managed store: {entry.executable}")
                continue
        eligible.append(entry)
        targets.append(target)
    if not targets:
        return
    verb = "Unregister only; files will be kept" if action == "u" else "Delete managed files and unregister"
    if action == "d":
        say("Deletion checks project references again and refuses items still in use.")
    else:
        say("Unregistering a runtime or host may require re-registering it for existing projects.")
    if not _confirm(verb, targets, ask, say):
        say("Cancelled.")
        return
    for entry in eligible:
        try:
            if action == "u":
                operation = unregister_runtime if runtime_menu else unregister_host
                operation(entry.executable, home)
                say(f"Unregistered (files kept): {entry.executable}")
            else:
                operation = delete_runtime if runtime_menu else delete_host
                _, target, existed = operation(entry.executable, home)
                say(f"Deleted: {target}" if existed else f"Already absent; unregistered: {target}")
        except NodePhellError as error:
            say(f"Skipped {entry.executable}: {error}")


def _packages(home, ask, say):
    say("Reading package metadata; file integrity is checked separately.")
    inventory = validate_store(home, verify_contents=False)
    references, reference_issues = _references(home, say)
    problems = {issue.cleanup_path: issue.message for issue in inventory.issues
                if issue.cleanup_path is not None}
    paths = sorted(set(inventory.healthy_releases) | set(problems), key=os.fspath)
    rows = []
    for path in paths:
        users = sum(path in reference.releases for reference in references)
        usage = "usage unknown" if reference_issues else f"referenced by {users} project(s)"
        relative = path.resolve(strict=False).relative_to(package_store(home).resolve(strict=False))
        identity = "/".join(relative.parts[:3])
        status = problems.get(path, "metadata present; integrity not checked")
        rows.append((path, f"{identity}: {status}; {usage}"))
    for issue in inventory.issues:
        if issue.cleanup_path is None:
            say(f"Store problem: {issue.path}: {issue.message}")
    selected = _select(rows, ask, say)
    if not selected:
        return
    chosen = tuple(rows[index][0] for index in selected)
    say("Only releases still proven unused can be removed. Unused generated views may also be removed.")
    if not _confirm("Remove selected unused package releases", chosen, ask, say):
        say("Cancelled.")
        return
    say("Checking file integrity and current references before removal...")
    _cleanup_result(remove_unused_releases(chosen, home), say)


def _projects(home, ask, say):
    references, _ = _references(home, say)
    rows = []
    for reference in references:
        problem = reference_problem(reference)
        status = "current" if problem is None else problem[0]
        rows.append((reference.project_root, f"{status}; {len(reference.releases)} package release(s)"))
    selected = _select(rows, ask, say)
    if not selected:
        return
    chosen = tuple(rows[index][0] for index in selected)
    say("This removes registrations, not project files or shared packages.")
    if not _confirm("Unregister selected projects", chosen, ask, say):
        say("Cancelled.")
        return
    for path in chosen:
        try:
            remove_project_reference(path, home)
            say(f"Unregistered: {path}")
        except NodePhellError as error:
            say(f"Skipped {path}: {error}")


def _cleanup_result(result, say):
    for path in result.removed:
        say(f"Removed: {path}")
    for path in result.skipped:
        say(f"Skipped (busy, protected, or no longer eligible): {path}")
    if not result.removed and not result.skipped:
        say("Nothing was removed.")


def _check(home, say):
    say("Checking all package files and generated views; large stores can take time...")
    validation = validate_store(home)
    say(f"Checked {validation.checked_releases} stored releases.")
    if not validation.issues:
        say("The shared package store is healthy.")
    for issue in validation.issues:
        say(f"{issue.path}: {issue.message}")


def _clean(home, ask, say):
    say("Checking file integrity and looking for safe cleanup candidates...")
    preview = clean_store(home)
    reasons = {issue.cleanup_path: issue.message for issue in preview.issues
               if issue.cleanup_path is not None}
    for issue in preview.issues:
        if issue.cleanup_path is None:
            say(f"Not automatically removable: {issue.path}: {issue.message}")
    rows = [(path, reasons[path]) for path in preview.candidates]
    selected = _select(rows, ask, say)
    if not selected:
        return
    chosen = tuple(rows[index][0] for index in selected)
    say("Cleanup follows 'store clean': damaged entries may be removed even when a project references them.")
    say("Run nodephell install in affected projects to restore damaged packages afterward.")
    if not _confirm("Remove selected cleanup candidates", chosen, ask, say):
        say("Cancelled.")
        return
    _cleanup_result(clean_store(home, apply=True, selected=chosen), say)


def manage(
    user_home: Path | None = None,
    prompt: Callable[[str], str] | None = None,
    announce: Callable[[str], None] | None = None,
) -> None:
    read = input if prompt is None else prompt
    say = print if announce is None else announce

    def ask(message):
        try:
            return read(message)
        except (EOFError, KeyboardInterrupt):
            return "q"

    say(f"NodePhell management (management Python: {sys.executable})")
    while True:
        say("\n1. Runtimes\n2. Package releases\n3. Registered projects\n"
            "4. Embedded hosts\n5. Check shared package integrity\n"
            "6. Clean broken or unused store entries\nq. Quit")
        choice = ask("Choose an option: ").strip().lower()
        if choice in {"", "q"}:
            return
        try:
            if choice == "1":
                _registry_menu("runtime", user_home, ask, say)
            elif choice == "2":
                _packages(user_home, ask, say)
            elif choice == "3":
                _projects(user_home, ask, say)
            elif choice == "4":
                _registry_menu("host", user_home, ask, say)
            elif choice == "5":
                _check(user_home, say)
            elif choice == "6":
                _clean(user_home, ask, say)
            else:
                say("Choose a listed number, or q to quit.")
        except NodePhellError as error:
            say(f"Could not complete operation: {error}")
