# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess
import tomllib

from .errors import NodePhellError
from .installer import install_project, lock_project
from .metadata import (
    LOCK_FILENAMES,
    discover_project,
    load_project,
    load_project_definition,
    lock_matches_project_definition,
    project_lock_path,
)
from .runtime import Runtime
from .versions import lowest_runtime_line, release_tuple


CommandRunner = Callable[[tuple[str, ...], Path], int]
KeepDecision = Callable[[Runtime], bool]


@dataclass(frozen=True)
class TroubleshootResult:
    root: Path
    command: tuple[str, ...]
    original_runtime: str | None
    baseline_status: int
    fallback_line: str | None = None
    trial_runtime: str | None = None
    trial_status: int | None = None
    kept: bool = False


def suggested_project_commands(start: Path | None = None) -> tuple[str, ...]:
    root = _project_root(start)
    load_project_definition(root)
    path = root / "pyproject.toml"
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise NodePhellError(
            f"cannot read project commands from {path}: {error}",
            guidance=(
                f"Correct {path}, then rerun 'nodephell troubleshoot'. You can "
                "also pass the reproducing command after '--'."
            ),
        ) from error

    names: set[str] = set()
    project = data.get("project")
    if isinstance(project, dict):
        scripts = project.get("scripts")
        if isinstance(scripts, dict):
            names.update(name for name in scripts if isinstance(name, str))
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        scripts = poetry.get("scripts")
        if isinstance(scripts, dict):
            names.update(name for name in scripts if isinstance(name, str))
    return tuple(sorted(names))


def troubleshoot_project(
    command: tuple[str, ...],
    start: Path | None = None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
    *,
    keep_trial: KeepDecision | None = None,
    runner: CommandRunner | None = None,
) -> TroubleshootResult:
    if not command:
        raise NodePhellError(
            "no smoke command was provided",
            guidance=(
                "Enter a command that currently fails, such as 'frogmouth "
                "--help', or rerun with 'nodephell troubleshoot -- COMMAND'."
            ),
        )
    root = _project_root(start)
    definition_path = root / "pyproject.toml"
    lock_path = project_lock_path(root)
    backup_path = lock_path.with_name(
        lock_path.name + ".nodephell-troubleshoot-backup"
    )
    if not definition_path.is_file():
        raise NodePhellError(
            f"troubleshooting needs a project definition: {definition_path}",
            guidance=(
                f"Create {definition_path} with 'nodephell init "
                f"{shlex.quote(str(root))}', or add a requires-python declaration "
                "before retrying."
            ),
        )
    if not lock_path.is_file() or lock_path.is_symlink():
        raise NodePhellError(
            f"troubleshooting needs a regular project lock: {lock_path}",
            guidance=(
                f"Run 'nodephell sync {shlex.quote(str(root))}' to create the "
                "lock, then rerun the failing command through troubleshoot."
            ),
        )
    if backup_path.exists() or backup_path.is_symlink():
        raise NodePhellError(
            f"a previous troubleshooting backup still exists: {backup_path}",
            guidance=(
                f"Restore it with 'mv {shlex.quote(str(backup_path))} "
                f"{shlex.quote(str(lock_path))}', then run 'nodephell install "
                f"{shlex.quote(str(root))}'. Inspect both files first if you "
                "intentionally kept the trial lock."
            ),
        )
    if not lock_matches_project_definition(root):
        raise NodePhellError(
            f"the project lock does not match {definition_path}",
            guidance=(
                f"Run 'nodephell sync {shlex.quote(str(root))}' first, then "
                "rerun troubleshoot so the comparison starts from current metadata."
            ),
        )

    definition = load_project_definition(root)
    locked = load_project(root)
    original_runtime = (
        locked.runtime_artifact.version
        if locked.runtime_artifact is not None
        else None
    )
    announce = progress if progress is not None else lambda message: None
    run = runner if runner is not None else _run_command
    announce(f"Testing current lock: {shlex.join(command)}")
    baseline_status = run(command, root)
    if baseline_status == 0:
        return TroubleshootResult(
            root,
            command,
            original_runtime,
            baseline_status,
        )

    fallback = lowest_runtime_line(definition.requires_python)
    if fallback is None:
        requirement = definition.requires_python or "no requires-python value"
        raise NodePhellError(
            f"the command failed with status {baseline_status}, but {requirement!r} "
            "does not name an earlier Python minor line to try",
            guidance=(
                f"Set a lower bound with a major and minor version in "
                f"{definition_path}, for example requires-python = \">=3.11,<4\", "
                f"run 'nodephell sync {shlex.quote(str(root))}', and retry. If "
                "the exact declared Python is intentional, inspect the command's "
                "traceback and correct the incompatible dependency instead."
            ),
        )
    fallback_line, fallback_requirement = fallback
    if original_runtime is not None:
        release = release_tuple(original_runtime)
        if len(release) >= 2 and release[:2] == tuple(
            int(part) for part in fallback_line.split(".")
        ):
            raise NodePhellError(
                f"the command failed with status {baseline_status} on Python "
                f"{original_runtime}, already the earliest declared line",
                guidance=(
                    "Inspect the traceback above and verify the failing package's "
                    "Python support. If another Python line is known to work, bound "
                    f"requires-python to that line in {definition_path}, then run "
                    f"'nodephell sync {shlex.quote(str(root))}'."
                ),
            )

    announce(
        f"Current command failed with status {baseline_status}; trying the "
        f"declared Python {fallback_line} line"
    )
    try:
        with backup_path.open("xb") as backup:
            backup.write(lock_path.read_bytes())
            backup.flush()
            os.fsync(backup.fileno())
    except OSError as error:
        raise NodePhellError(
            f"cannot preserve {lock_path} at {backup_path}: {error}",
            guidance=(
                "Check that the project directory is writable and remove a stale "
                "backup only after restoring or inspecting it, then retry."
            ),
        ) from error

    try:
        lock_result = lock_project(
            root,
            user_home,
            progress,
            update=True,
            runtime_requirement=fallback_requirement,
        )
        install_project(root, user_home, progress)
        announce(
            f"Testing Python {lock_result.runtime.version}: {shlex.join(command)}"
        )
        trial_status = run(command, root)
        keep = trial_status == 0 and keep_trial is not None and keep_trial(
            lock_result.runtime
        )
        if keep:
            try:
                backup_path.unlink()
            except OSError as error:
                raise NodePhellError(
                    f"kept the trial lock but could not remove {backup_path}: {error}",
                    guidance=(
                        f"The working lock is {lock_path}. Remove only "
                        f"{backup_path} after confirming the project still runs."
                    ),
                ) from error
        else:
            _restore_original(
                root,
                lock_path,
                backup_path,
                user_home,
                progress,
            )
        return TroubleshootResult(
            root,
            command,
            original_runtime,
            baseline_status,
            fallback_line,
            lock_result.runtime.version,
            trial_status,
            keep,
        )
    except BaseException as error:
        if backup_path.exists() or backup_path.is_symlink():
            try:
                _restore_original(
                    root,
                    lock_path,
                    backup_path,
                    user_home,
                    progress,
                )
            except NodePhellError:
                raise
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(error, NodePhellError):
            raise NodePhellError(
                f"could not complete the Python {fallback_line} trial: {error}",
                guidance=_trial_failure_guidance(
                    error,
                    fallback_line,
                    definition_path,
                    root,
                ),
            ) from error
        raise


def _restore_original(
    root: Path,
    lock_path: Path,
    backup_path: Path,
    user_home: Path | None,
    progress: Callable[[str], None] | None,
) -> None:
    try:
        for name in LOCK_FILENAMES:
            candidate = root / name
            if candidate != lock_path:
                candidate.unlink(missing_ok=True)
        os.replace(backup_path, lock_path)
    except OSError as error:
        raise NodePhellError(
            f"cannot restore the original project lock: {error}",
            guidance=(
                f"Restore it manually with 'mv {shlex.quote(str(backup_path))} "
                f"{shlex.quote(str(lock_path))}', then run 'nodephell install "
                f"{shlex.quote(str(root))}'."
            ),
        ) from error
    try:
        install_project(root, user_home, progress)
    except NodePhellError as error:
        raise NodePhellError(
            f"the original lock was restored, but its project state could not be "
            f"reinstalled: {error}",
            guidance=(
                f"Run 'nodephell install {shlex.quote(str(root))}' after correcting "
                f"the reported installation problem. The original "
                f"{lock_path.name} is intact."
            ),
        ) from error


def _trial_failure_guidance(
    error: NodePhellError,
    fallback_line: str,
    definition_path: Path,
    root: Path,
) -> str:
    if "no downloadable CPython runtime satisfies" in str(error):
        return (
            f"The original lock was restored. No provider build is available for "
            f"the declared floor, Python {fallback_line}, on this platform. Check "
            "the project's supported Python versions and choose its next supported "
            f"minor line. Bound [project].requires-python (or Poetry's python "
            f"dependency) to that line in {definition_path}, run 'nodephell sync "
            f"{shlex.quote(str(root))}', and retry the smoke command."
        )
    return (
        f"The original lock was restored. Correct the download, resolution, or "
        f"installation error shown above, then rerun 'nodephell troubleshoot "
        f"{shlex.quote(str(root))}'. Run 'nodephell install "
        f"{shlex.quote(str(root))}' first if a launcher still reports the trial "
        "runtime."
    )


def _run_command(command: tuple[str, ...], root: Path) -> int:
    try:
        return subprocess.run(command, cwd=root, check=False).returncode
    except FileNotFoundError as error:
        raise NodePhellError(
            f"smoke command was not found: {command[0]}",
            guidance=(
                f"Run 'nodephell install {shlex.quote(str(root))}' to create package "
                "launchers, then retry. For a non-package command, pass its "
                "absolute path."
            ),
        ) from error
    except OSError as error:
        raise NodePhellError(
            f"cannot run smoke command {shlex.join(command)}: {error}",
            guidance=(
                "Check that the executable exists and is runnable, then retry with "
                "its absolute path after '--'."
            ),
        ) from error


def _project_root(start: Path | None) -> Path:
    location = Path.cwd() if start is None else start.expanduser()
    if start is not None and not location.exists():
        raise NodePhellError(
            f"project path does not exist: {location}",
            guidance="Pass an existing project directory to 'nodephell troubleshoot'.",
        )
    root = discover_project(location)
    if root is None:
        raise NodePhellError(
            f"no project lock or pyproject.toml found from {location}",
            guidance=(
                "Run the command inside the project tree, or pass the project "
                "directory before '--'."
            ),
        )
    return root
