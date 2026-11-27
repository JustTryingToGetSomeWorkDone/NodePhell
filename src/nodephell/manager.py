# SPDX-License-Identifier: GPL-3.0-only

"""Interactive inventory and maintenance using the existing guarded operations."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import sys
import textwrap

from .errors import NodePhellError, style_text
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


def _wrapped(value, indent="", prefix=""):
    width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
    return textwrap.fill(
        str(value), width=width, initial_indent=indent + prefix,
        subsequent_indent=indent + " " * len(prefix),
        expand_tabs=False, replace_whitespace=False, drop_whitespace=False,
        break_on_hyphens=False,
    )


def _status_style(text):
    problem_words = (
        "missing", "unavailable", "unknown", "not executable", "problem",
        "incomplete", "changed", "damaged",
    )
    return "warning" if any(word in text.lower() for word in problem_words) else "label"


def _select(rows, ask, say):
    if not rows:
        say("No entries found.")
        return ()
    for number, (path, label) in enumerate(rows, 1):
        heading, separator, details = label.partition(": ")
        say("")
        indent = " " * (len(str(number)) + 4)
        heading_lines = _wrapped(heading, indent).splitlines()
        say(f"  {style_text(f'{number}.', 'option')} "
            f"{style_text(heading_lines[0][len(indent):], 'label')}")
        for line in heading_lines[1:]:
            say(style_text(line, "label"))
        if separator:
            say(style_text(_wrapped(details, indent), _status_style(details)))
        say(_wrapped(path, indent, "Path: "))
    say("")
    while True:
        value = ask("Select numbers (e.g. 1,3-5), 'all', or Enter to go back: ").strip()
        if value.lower() in {"", "b", "q"}:
            return ()
        try:
            return parse_selection(value, len(rows))
        except NodePhellError as error:
            say(str(error))


def _confirm(action, paths, ask, say):
    role = "danger" if action.startswith(("Delete", "Remove")) else "heading"
    say(style_text(f"{action}:", role))
    for path in paths:
        say(_wrapped(path, "  "))
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
    say(style_text("\nRuntimes" if runtime_menu else "\nEmbedded hosts", "heading"))
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
    for key, label, role in (
        ("u", "Unregister only (keep files)", "label"),
        ("d", "Delete managed files", "danger"),
        ("p", "Probe selected entries", "label"),
        ("b", "Back", "label"),
    ):
        say(f"  {style_text(f'[{key}]', 'option')} {style_text(label, role)}")
    action = ask("Action: ").strip().lower()
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
                say(style_text(f"Available: {result.identifier}", "success"))
            except NodePhellError as error:
                say(style_text(f"Unavailable: {error}", "warning"))
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
                say(style_text(f"Unregistered (files kept): {entry.executable}", "success"))
            else:
                operation = delete_runtime if runtime_menu else delete_host
                _, target, existed = operation(entry.executable, home)
                message = f"Deleted: {target}" if existed else f"Already absent; unregistered: {target}"
                say(style_text(message, "success"))
        except NodePhellError as error:
            say(style_text(f"Skipped {entry.executable}: {error}", "warning"))


def _package_rows(home, say):
    inventory = validate_store(home, verify_contents=False)
    references, reference_issues = _references(home, say)
    problems = {issue.cleanup_path: issue.message for issue in inventory.issues
                if issue.cleanup_path is not None}
    paths = sorted(set(inventory.healthy_releases) | set(problems), key=os.fspath)
    groups = {}
    for path in paths:
        users = sum(path in reference.releases for reference in references)
        usage = "usage unknown" if reference_issues else f"referenced by {users} project(s)"
        relative = path.resolve(strict=False).relative_to(package_store(home).resolve(strict=False))
        identity = "/".join(relative.parts[1:3])
        if len(relative.parts) > 3:
            identity += f" (build {relative.parts[3][:12]})"
        if len(relative.parts) == 7:
            identity += f" [{relative.parts[5]}, {relative.parts[6]}]"
        status = problems.get(path, "metadata present; integrity not checked")
        groups.setdefault(relative.parts[0], []).append(
            (path, f"{identity}: {status}; {usage}")
        )
    for issue in inventory.issues:
        if issue.cleanup_path is None:
            say(f"Store problem: {issue.path}: {issue.message}")
    return groups


def _choose_package(names, page, ask, say):
    page_size = 15
    if not names:
        say("No package releases found.")
        return None, 0
    pages = (len(names) + page_size - 1) // page_size
    page = min(page, pages - 1)
    while True:
        start = page * page_size
        stop = min(start + page_size, len(names))
        say(style_text(f"\nPackages — page {page + 1}/{pages} ({len(names)} names)", "heading"))
        for index in range(start, stop):
            say(f"  {style_text(str(index + 1) + '.', 'option')} "
                f"{style_text(names[index], 'label')}")
        controls = []
        if page + 1 < pages:
            controls.append(f"{style_text('[n]', 'option')} Next page")
        if page > 0:
            controls.append(f"{style_text('[p]', 'option')} Previous page")
        controls.append(f"{style_text('[b]', 'option')} Back")
        say("  " + "   ".join(controls))
        value = ask("Package number, n/p for pages, or Enter to go back: ").strip().lower()
        try:
            number = int(value)
        except ValueError:
            number = 0
        if value in {"", "b", "q"}:
            return None, page
        if value == "n" and page + 1 < pages:
            page += 1
        elif value == "p" and page > 0:
            page -= 1
        elif start < number <= stop:
            return names[number - 1], page
        else:
            say("Choose a package number on this page, a page key, or Enter to go back.")


def _packages(home, ask, say):
    say(style_text("\nPackage releases", "heading"))
    say("Reading package metadata; file integrity is checked separately.")
    groups = _package_rows(home, say)
    page = 0
    while True:
        name, page = _choose_package(sorted(groups, key=str.casefold), page, ask, say)
        if name is None:
            return
        say(style_text(f"\n{name} — versions and builds", "heading"))
        rows = groups[name]
        selected = _select(rows, ask, say)
        if not selected:
            continue
        chosen = tuple(rows[index][0] for index in selected)
        say("Only releases still proven unused can be removed. Unused generated views may also be removed.")
        if not _confirm("Remove selected unused package releases", chosen, ask, say):
            say("Cancelled.")
            continue
        say("Checking file integrity and current references before removal...")
        _cleanup_result(remove_unused_releases(chosen, home), say)
        groups = _package_rows(home, say)


def _projects(home, ask, say):
    say(style_text("\nRegistered projects", "heading"))
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
            say(style_text(f"Unregistered: {path}", "success"))
        except NodePhellError as error:
            say(f"Skipped {path}: {error}")


def _cleanup_result(result, say):
    for path in result.removed:
        say(style_text(f"Removed: {path}", "success"))
    for path in result.skipped:
        say(style_text(f"Skipped (busy, protected, or no longer eligible): {path}", "warning"))
    if not result.removed and not result.skipped:
        say("Nothing was removed.")


def _check(home, say):
    say(style_text("\nShared package integrity", "heading"))
    say("Checking all package files and generated views; large stores can take time...")
    validation = validate_store(home)
    say(f"Checked {validation.checked_releases} stored releases.")
    if not validation.issues:
        say(style_text("The shared package store is healthy.", "success"))
    for issue in validation.issues:
        say(f"{issue.path}: {issue.message}")


def _clean(home, ask, say):
    say(style_text("\nCleanup candidates", "heading"))
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

    say(style_text("NodePhell management", "heading"))
    say(_wrapped(sys.executable, prefix="Management Python: "))
    while True:
        say(style_text("\nMain menu", "heading"))
        for key, label in (
            ("1", "Runtimes"), ("2", "Package releases"),
            ("3", "Registered projects"), ("4", "Embedded hosts"),
            ("5", "Check shared package integrity"),
            ("6", "Clean broken or unused store entries"), ("q", "Quit"),
        ):
            say(f"  {style_text(key + '.', 'option')} {style_text(label, 'label')}")
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
            say(style_text(f"Could not complete operation: {error}", "danger"))
