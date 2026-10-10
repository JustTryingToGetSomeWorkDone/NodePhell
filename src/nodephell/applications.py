# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .adapters import (
    HostAdapter,
    adapter_for_executable,
    discover_adapters,
    load_adapter,
)
from .adapters.base import EmbeddedHost
from .errors import NodePhellError, print_error
from .host import (
    execute_host,
    execute_host_gui,
    load_hosts,
    probe_host,
    register_probed_host,
    resolve_host,
)
from .installer import (
    InstallationResult,
    SyncResult,
    install_project,
    sync_project,
)
from .launchers import (
    LauncherChange,
    application_launcher_problem,
    application_launcher_path,
    check_application_launcher,
    install_application_launcher,
    remove_application_launcher,
)
from .locking import exclusive_store_lock
from .metadata import (
    LOCK_FILENAMES,
    discover_project,
    load_project_definition,
    project_lock_path,
)
from .plugins import PluginChange, add_plugin
from .runtime import data_root


_REGISTRY_VERSION = 1
_KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
_TABLE_HEADER = re.compile(r"^\[+[^]]+]\s*(?:#.*)?$")


@dataclass(frozen=True)
class Application:
    name: str
    kind: str
    project_root: Path
    executable: Path
    launch_mode: str


@dataclass(frozen=True)
class ApplicationCandidate:
    adapter: HostAdapter
    executable: Path


@dataclass(frozen=True)
class ApplicationPlan:
    application: Application
    host: EmbeddedHost
    launcher: Path
    project_update: bool


@dataclass(frozen=True)
class ApplicationSetup:
    application: Application
    host: EmbeddedHost
    sync: SyncResult
    launcher: LauncherChange
    project_updated: bool


@dataclass(frozen=True)
class DeclaredApplicationPlan:
    plugin: PluginChange
    application: ApplicationPlan


@dataclass(frozen=True)
class ApplicationInstallationSetup:
    application: Application
    host: EmbeddedHost
    installation: InstallationResult
    launcher: LauncherChange


def application_registry_path(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "applications" / "registry.json"


def application_project_root(start: Path | None = None) -> Path:
    location = Path.cwd() if start is None else start.expanduser()
    if start is not None and not location.is_dir():
        raise NodePhellError(f"project directory does not exist: {location}")
    root = discover_project(location)
    if root is None:
        raise NodePhellError(
            f"no NodePhell project was found from {location}; "
            "run from a project or pass --project"
        )
    if not (root / "pyproject.toml").is_file():
        raise NodePhellError(
            f"application setup requires a pyproject.toml in {root}"
        )
    return root


def discover_application_candidates(
    project_root: Path,
) -> tuple[ApplicationCandidate, ...]:
    root = project_root.expanduser().resolve(strict=False)
    candidates: dict[Path, ApplicationCandidate] = {}
    for adapter in discover_adapters():
        for pattern in adapter.project_search_patterns:
            try:
                matches = tuple(root.glob(pattern))
            except (OSError, ValueError):
                continue
            for path in matches:
                try:
                    if not path.is_file() or not adapter.accepts_executable(path):
                        continue
                    resolved = path.resolve()
                except OSError:
                    continue
                candidates[resolved] = ApplicationCandidate(adapter, resolved)
    return tuple(
        candidates[path]
        for path in sorted(candidates, key=lambda item: str(item))
    )


def plan_application(
    executable: Path,
    project_root: Path,
    name: str | None = None,
    user_home: Path | None = None,
    *,
    replace: bool = False,
) -> ApplicationPlan:
    root = application_project_root(project_root)
    target = executable.expanduser().resolve(strict=False)
    adapter = adapter_for_executable(target)
    host = probe_host(target, adapter.kind)
    application_name = adapter.launcher_name if name is None else name
    launcher = check_application_launcher(application_name, user_home)
    existing = _application_named(application_name, user_home)
    if existing is not None and not replace:
        raise NodePhellError(
            f"application {application_name!r} is already registered; "
            f"run 'nodephell app refresh {application_name}'"
        )
    application = Application(
        application_name,
        adapter.kind,
        root,
        host.executable,
        adapter.launch_mode,
    )
    definition = load_project_definition(root)
    requirement = f"=={host.version}"
    update = (
        definition.host is None
        or definition.host.kind != host.kind
        or definition.host.requires != requirement
    )
    return ApplicationPlan(application, host, launcher, update)


def plan_declared_application(
    start: Path | None = None,
    user_home: Path | None = None,
) -> DeclaredApplicationPlan | None:
    location = Path.cwd() if start is None else start.expanduser()
    root = discover_project(location)
    if root is None:
        return None
    if not (root / "pyproject.toml").is_file():
        return None
    declaration = load_project_definition(root).application
    if declaration is None:
        return None
    plugin_source = (root / declaration.adapter).resolve(strict=False)
    if not plugin_source.is_relative_to(root):
        raise NodePhellError(
            f"declared application adapter leaves the project: "
            f"{declaration.adapter}"
        )
    plugin = add_plugin(plugin_source, user_home)

    if declaration.executable is not None:
        executable = (root / declaration.executable).resolve(strict=False)
        if not executable.is_file():
            raise NodePhellError(
                f"declared application executable is unavailable: {executable}"
            )
        if not plugin.adapter.accepts_executable(executable):
            raise NodePhellError(
                f"declared plugin {plugin.adapter.kind!r} does not recognize "
                f"{executable}"
            )
    else:
        candidates = tuple(
            candidate
            for candidate in discover_application_candidates(root)
            if candidate.adapter.kind == plugin.adapter.kind
        )
        if not candidates:
            raise NodePhellError(
                f"declared plugin {plugin.adapter.kind!r} found no application "
                "executable; add 'executable' to "
                "[tool.nodephell.application]"
            )
        if len(candidates) > 1:
            locations = ", ".join(
                str(candidate.executable) for candidate in candidates
            )
            raise NodePhellError(
                f"declared plugin {plugin.adapter.kind!r} found multiple "
                f"application executables: {locations}; add 'executable' to "
                "[tool.nodephell.application]"
            )
        executable = candidates[0].executable

    plan = plan_application(
        executable,
        root,
        declaration.name,
        user_home,
        replace=True,
    )
    if plan.application.kind != plugin.adapter.kind:
        raise NodePhellError(
            f"declared plugin is {plugin.adapter.kind!r}, but the executable "
            f"selected adapter {plan.application.kind!r}"
        )
    return DeclaredApplicationPlan(plugin, plan)


def install_declared_application(
    declared: DeclaredApplicationPlan,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> ApplicationInstallationSetup:
    plan = declared.application
    if plan.project_update:
        raise NodePhellError(
            "the declared application does not match the locked host; "
            "run 'nodephell sync' to update the project deliberately"
        )
    register_probed_host(plan.host, user_home)
    installation = install_project(
        plan.application.project_root,
        user_home,
        progress,
    )
    launcher = _record_application(plan.application, user_home)
    return ApplicationInstallationSetup(
        plan.application,
        plan.host,
        installation,
        launcher,
    )


def apply_application(
    plan: ApplicationPlan,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> ApplicationSetup:
    application = plan.application
    register_probed_host(plan.host, user_home)
    project_path = application.project_root / "pyproject.toml"
    lock_paths = tuple(application.project_root / name for name in LOCK_FILENAMES)
    project_before = _read_file(project_path)
    locks_before = {path: _read_file(path) for path in lock_paths}
    updated = False
    try:
        updated = _set_project_host(
            application.project_root,
            plan.host.kind,
            plan.host.version,
        )
        synchronized = sync_project(
            application.project_root,
            user_home,
            progress,
        )
    except Exception:
        if updated:
            _restore_file(project_path, project_before)
            for path, contents in locks_before.items():
                _restore_file(path, contents)
        raise

    launcher = _record_application(application, user_home)
    return ApplicationSetup(
        application,
        plan.host,
        synchronized,
        launcher,
        updated,
    )


def _record_application(
    application: Application,
    user_home: Path | None,
) -> LauncherChange:
    applications_before = load_applications(user_home)
    _save_application(application, applications_before, user_home)
    try:
        return install_application_launcher(application.name, user_home)
    except Exception:
        _save_applications(applications_before, user_home)
        raise


def load_applications(
    user_home: Path | None = None,
) -> tuple[Application, ...]:
    path = application_registry_path(user_home)
    if not path.exists():
        return ()
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise NodePhellError(
            f"cannot read application registry {path}: {error}"
        ) from error
    if not isinstance(data, dict) or data.get("version") != _REGISTRY_VERSION:
        raise NodePhellError(f"unsupported application registry format: {path}")
    records = data.get("applications")
    if not isinstance(records, list):
        raise NodePhellError(f"invalid application registry: {path}")
    applications = tuple(_application_from_record(record, path) for record in records)
    names = [application.name for application in applications]
    if len(names) != len(set(names)):
        raise NodePhellError(f"duplicate application name in {path}")
    return tuple(sorted(applications, key=lambda item: item.name.lower()))


def get_application(
    name: str,
    user_home: Path | None = None,
) -> Application:
    application = _application_named(name, user_home)
    if application is None:
        raise NodePhellError(f"application is not registered: {name!r}")
    return application


def remove_application(
    name: str,
    user_home: Path | None = None,
) -> tuple[Application, LauncherChange]:
    applications = load_applications(user_home)
    matches = tuple(item for item in applications if item.name == name)
    if not matches:
        raise NodePhellError(f"application is not registered: {name!r}")
    launcher = remove_application_launcher(name, user_home)
    _save_applications(
        tuple(item for item in applications if item.name != name),
        user_home,
    )
    return matches[0], launcher


def move_application_projects(
    old_root: Path,
    new_root: Path,
    user_home: Path | None = None,
) -> int:
    old = old_root.expanduser().resolve(strict=False)
    new = new_root.expanduser().resolve(strict=False)
    applications = load_applications(user_home)
    changed = tuple(
        Application(
            application.name,
            application.kind,
            (
                new
                if application.project_root == old
                else application.project_root
            ),
            (
                new / application.executable.relative_to(old)
                if application.project_root == old
                and application.executable.is_relative_to(old)
                else application.executable
            ),
            application.launch_mode,
        )
        for application in applications
    )
    count = sum(
        application.project_root == old for application in applications
    )
    if count:
        _save_applications(changed, user_home)
    return count


def application_problem(
    application: Application,
    user_home: Path | None = None,
) -> str | None:
    try:
        load_adapter(application.kind)
    except NodePhellError as error:
        return f"adapter is unavailable: {error}"
    if not application.project_root.is_dir():
        return f"project is unavailable: {application.project_root}"
    try:
        lock_path = project_lock_path(application.project_root)
    except NodePhellError as error:
        return str(error)
    if not lock_path.is_file():
        return f"project lock is missing in: {application.project_root}"
    if not application.executable.is_file():
        return f"entry executable is missing: {application.executable}"
    try:
        registered = load_hosts(user_home)
    except NodePhellError as error:
        return f"host registry is unavailable: {error}"
    if not any(
        host.kind == application.kind
        and host.executable == application.executable
        for host in registered
    ):
        return (
            f"entry executable is not registered; run "
            f"'nodephell app refresh {application.name}'"
        )
    return application_launcher_problem(application.name, user_home)


def app_main(name: str, arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    try:
        application = _application_named(name)
        if application is None:
            raise NodePhellError(
                f"application is not registered: {name!r}; "
                "run 'nodephell app add'"
            )
        resolution = resolve_host(
            [],
            cwd=application.project_root,
            host_executable=application.executable,
        )
        if resolution.host.kind != application.kind:
            raise NodePhellError(
                f"application {name!r} expected adapter "
                f"{application.kind!r}, got {resolution.host.kind!r}"
            )
        if application.launch_mode == "gui":
            execute_host_gui(values, resolution)
        else:
            execute_host(values, resolution)
    except NodePhellError as error:
        print_error(error)
        return 2


def _application_named(
    name: str,
    user_home: Path | None = None,
) -> Application | None:
    return next(
        (item for item in load_applications(user_home) if item.name == name),
        None,
    )


def _save_application(
    application: Application,
    existing: tuple[Application, ...],
    user_home: Path | None,
) -> None:
    applications = tuple(
        item for item in existing if item.name != application.name
    ) + (application,)
    _save_applications(applications, user_home)


def _save_applications(
    applications: tuple[Application, ...],
    user_home: Path | None,
) -> None:
    path = application_registry_path(user_home)
    data = {
        "version": _REGISTRY_VERSION,
        "applications": [
            {
                "name": application.name,
                "kind": application.kind,
                "project": str(application.project_root),
                "executable": str(application.executable),
                "launch_mode": application.launch_mode,
            }
            for application in sorted(
                applications, key=lambda item: item.name.lower()
            )
        ],
    }
    with exclusive_store_lock(path, user_home) as acquired:
        assert acquired
        if not applications and not path.exists():
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, json.dumps(data, indent=2) + "\n")
        except OSError as error:
            raise NodePhellError(
                f"cannot write application registry {path}: {error}"
            ) from error


def _application_from_record(record: object, path: Path) -> Application:
    if not isinstance(record, dict):
        raise NodePhellError(f"invalid application entry in {path}")
    fields = ("name", "kind", "project", "executable", "launch_mode")
    if not all(isinstance(record.get(field), str) for field in fields):
        raise NodePhellError(f"invalid application entry in {path}")
    if record["launch_mode"] not in {"gui", "console"}:
        raise NodePhellError(f"invalid application launch mode in {path}")
    if _KIND.fullmatch(record["kind"]) is None:
        raise NodePhellError(f"invalid application adapter kind in {path}")
    project = Path(record["project"]).expanduser()
    executable = Path(record["executable"]).expanduser()
    if not project.is_absolute() or not executable.is_absolute():
        raise NodePhellError(f"application paths are not absolute in {path}")
    try:
        application_launcher_path(record["name"])
    except NodePhellError as error:
        raise NodePhellError(f"invalid application entry in {path}: {error}") from error
    return Application(
        record["name"],
        record["kind"],
        project.resolve(strict=False),
        executable.resolve(strict=False),
        record["launch_mode"],
    )


def _set_project_host(root: Path, kind: str, version: str) -> bool:
    path = root / "pyproject.toml"
    definition = load_project_definition(root)
    requirement = f"=={version}"
    if (
        definition.host is not None
        and definition.host.kind == kind
        and definition.host.requires == requirement
    ):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise NodePhellError(
            f"cannot read project definition {path}: {error}"
        ) from error
    lines = text.splitlines(keepends=True)
    headings = [
        index
        for index, line in enumerate(lines)
        if line.split("#", 1)[0].strip() == "[tool.nodephell.host]"
    ]
    if len(headings) > 1:
        raise NodePhellError(f"duplicate [tool.nodephell.host] table in {path}")
    block = (
        "[tool.nodephell.host]\n"
        f"kind = {json.dumps(kind)}\n"
        f"requires = {json.dumps(requirement)}\n\n"
    )
    if headings:
        start = headings[0]
        end = start + 1
        while (
            end < len(lines)
            and _TABLE_HEADER.fullmatch(lines[end].strip()) is None
        ):
            end += 1
        lines[start:end] = [block]
        updated = "".join(lines)
    else:
        separator = "" if not text or text.endswith("\n\n") else "\n"
        updated = text + separator + block
    try:
        _write_atomic(path, updated)
        load_project_definition(root)
    except Exception as error:
        try:
            _write_atomic(path, text)
        except OSError as restore_error:
            raise NodePhellError(
                f"cannot restore project definition {path}: {restore_error}"
            ) from restore_error
        if isinstance(error, NodePhellError):
            raise
        raise NodePhellError(
            f"cannot update project definition {path}: {error}"
        ) from error
    return True


def _read_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError as error:
        raise NodePhellError(f"cannot back up {path}: {error}") from error


def _restore_file(path: Path, content: bytes | None) -> None:
    try:
        if content is None:
            path.unlink(missing_ok=True)
        else:
            _write_atomic_bytes(path, content)
    except OSError as error:
        raise NodePhellError(f"cannot restore {path}: {error}") from error


def _write_atomic(path: Path, text: str) -> None:
    _write_atomic_bytes(path, text.encode("utf-8"))


def _write_atomic_bytes(path: Path, content: bytes) -> None:
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}-",
            dir=path.parent,
        )
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
        temporary = Path(temporary_name)
        if path.exists():
            temporary.chmod(path.stat().st_mode)
        temporary.replace(path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
