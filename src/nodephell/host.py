# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Mapping, NoReturn

from .errors import NodePhellError
from .launcher import Resolution, resolve
from .metadata import HostRequirement
from .runtime import Runtime, data_root
from .store import PackageSelection, package_environment
from .versions import matches_runtime, runtime_version_key


_PROBE_MARKER = "__NODEPHELL_FREECAD_HOST__"
_PROBE = f"""
import FreeCAD, json, platform, sys, sysconfig
print({_PROBE_MARKER!r} + json.dumps({{
    "host_version": FreeCAD.Version()[:3],
    "implementation": sys.implementation.name,
    "python_version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI") or "",
    "platform": sysconfig.get_platform(),
}}))
"""


@dataclass(frozen=True)
class EmbeddedHost:
    kind: str
    version: str
    executable: Path
    runtime: Runtime
    environment: tuple[tuple[str, str], ...] = ()

    @property
    def identifier(self) -> str:
        return "-".join((self.kind, self.version, self.runtime.abi))


@dataclass(frozen=True)
class HostResolution:
    host: EmbeddedHost
    project: Resolution


def host_registry_path(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "hosts" / "registry.json"


def probe_host(executable: Path) -> EmbeddedHost:
    executable = executable.expanduser().resolve(strict=False)
    if not executable.is_file():
        raise NodePhellError(f"embedded host does not exist: {executable}")
    host_environment, library_paths = _candidate_environment(executable)
    environment = dict(os.environ)
    environment.update(host_environment)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory(prefix="nodephell-host-probe-") as temporary:
        script = Path(temporary) / "probe.py"
        script.write_text(_PROBE, encoding="utf-8")
        try:
            result = subprocess.run(
                [str(executable), str(script)],
                cwd=executable.parent,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NodePhellError(
                f"cannot inspect embedded host {executable}: {error}"
            ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise NodePhellError(
            f"cannot inspect embedded host {executable}: {detail}"
        )
    details = _probe_details(result.stdout, executable)
    host_version = details["host_version"]
    if not isinstance(host_version, list) or len(host_version) < 3 or not all(
        isinstance(part, str) for part in host_version[:3]
    ):
        raise NodePhellError(
            f"embedded host returned invalid version information: {executable}"
        )
    version = ".".join(host_version[:3])
    runtime_fields = (
        details.get("implementation"),
        details.get("python_version"),
        details.get("abi"),
        details.get("platform"),
    )
    if not all(isinstance(value, str) for value in runtime_fields):
        raise NodePhellError(
            f"embedded host returned invalid runtime information: {executable}"
        )
    runtime = Runtime(
        details["implementation"].lower(),
        details["python_version"],
        executable,
        details["abi"],
        details["platform"],
        library_paths,
    )
    runtime_version_key(runtime.version)
    runtime_version_key(version)
    return EmbeddedHost(
        "freecad",
        version,
        executable,
        runtime,
        tuple(sorted(host_environment.items())),
    )


def register_host(
    executable: Path,
    user_home: Path | None = None,
) -> EmbeddedHost:
    host = probe_host(executable)
    hosts = [
        item
        for item in load_hosts(user_home)
        if item.executable != host.executable and item.identifier != host.identifier
    ]
    hosts.append(host)
    _save_hosts(tuple(hosts), user_home)
    return host


def load_hosts(user_home: Path | None = None) -> tuple[EmbeddedHost, ...]:
    path = host_registry_path(user_home)
    if not path.exists():
        return ()
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise NodePhellError(f"cannot read host registry {path}: {error}") from error
    if not isinstance(data, dict) or data.get("version") != 1:
        raise NodePhellError(f"unsupported host registry format: {path}")
    entries = data.get("hosts")
    if not isinstance(entries, list):
        raise NodePhellError(f"invalid host registry: {path}")
    return tuple(_host_from_record(entry, path) for entry in entries)


def select_host(
    requirement: HostRequirement,
    hosts: tuple[EmbeddedHost, ...],
    runtime: Runtime,
) -> EmbeddedHost:
    candidates = [
        host
        for host in hosts
        if host.kind == requirement.kind
        and matches_runtime(host.version, requirement.requires)
        and _compatible_runtime(host.runtime, runtime)
    ]
    if not candidates:
        requirement_text = requirement.requires or "any version"
        raise NodePhellError(
            f"no registered {requirement.kind} host satisfies "
            f"{requirement_text!r} with Python ABI {runtime.abi}; "
            "add one with 'nodephell host add /path/to/freecadcmd'"
        )
    return max(
        candidates,
        key=lambda host: (
            runtime_version_key(host.version),
            str(host.executable),
        ),
    )


def resolve_host(
    arguments: list[str],
    cwd: Path | None = None,
    user_home: Path | None = None,
) -> HostResolution:
    project_resolution = resolve(arguments, cwd, user_home)
    project = project_resolution.project
    if project is None:
        raise NodePhellError("no NodePhell project was found for embedded host run")
    if project.host is None:
        raise NodePhellError(
            f"project {project.root} does not declare [tool.nodephell.host]"
        )
    host = select_host(
        project.host,
        load_hosts(user_home),
        project_resolution.runtime,
    )
    return HostResolution(host, project_resolution)


def host_environment(
    host: EmbeddedHost,
    packages: PackageSelection,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = package_environment(host.runtime, packages, base)
    environment.update(dict(host.environment))
    return environment


def execute_host(arguments: list[str], resolution: HostResolution) -> NoReturn:
    executable = str(resolution.host.executable)
    try:
        os.execvpe(
            executable,
            [executable, *arguments],
            host_environment(
                resolution.host,
                resolution.project.packages,
            ),
        )
    except OSError as error:
        raise NodePhellError(f"cannot execute embedded host {executable}: {error}") from error


def _probe_details(stdout: str, executable: Path) -> dict:
    for line in stdout.splitlines():
        if not line.startswith(_PROBE_MARKER):
            continue
        try:
            details = json.loads(line.removeprefix(_PROBE_MARKER))
        except json.JSONDecodeError as error:
            raise NodePhellError(
                f"embedded host returned invalid probe data: {executable}"
            ) from error
        if isinstance(details, dict):
            return details
    raise NodePhellError(f"embedded host returned no probe data: {executable}")


def _candidate_environment(
    executable: Path,
) -> tuple[dict[str, str], tuple[Path, ...]]:
    app_dir = executable.parent.parent.parent
    if (
        executable.parent.name == "bin"
        and executable.parent.parent.name == "usr"
        and (app_dir / "AppRun").is_file()
    ):
        library = app_dir / "usr" / "lib"
        libraries = (library.resolve(),) if library.is_dir() else ()
        return {"APPDIR": str(app_dir)}, libraries
    return {}, ()


def _compatible_runtime(host: Runtime, runtime: Runtime) -> bool:
    return (
        host.implementation == runtime.implementation
        and host.abi == runtime.abi
        and host.platform == runtime.platform
    )


def _host_from_record(record: object, path: Path) -> EmbeddedHost:
    if not isinstance(record, dict):
        raise NodePhellError(f"invalid host entry in {path}")
    required = (
        "kind",
        "version",
        "executable",
        "implementation",
        "python_version",
        "abi",
        "platform",
    )
    if not all(isinstance(record.get(key), str) for key in required):
        raise NodePhellError(f"invalid host entry in {path}")
    executable = Path(record["executable"]).expanduser().resolve(strict=False)
    if not executable.is_file():
        raise NodePhellError(f"registered embedded host is missing: {executable}")
    raw_libraries = record.get("library_paths", [])
    raw_environment = record.get("environment", {})
    if not isinstance(raw_libraries, list) or not all(
        isinstance(item, str) for item in raw_libraries
    ):
        raise NodePhellError(f"invalid host library paths in {path}")
    if not isinstance(raw_environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_environment.items()
    ):
        raise NodePhellError(f"invalid host environment in {path}")
    runtime = Runtime(
        record["implementation"].lower(),
        record["python_version"],
        executable,
        record["abi"],
        record["platform"],
        tuple(Path(item).expanduser().resolve(strict=False) for item in raw_libraries),
    )
    runtime_version_key(runtime.version)
    runtime_version_key(record["version"])
    return EmbeddedHost(
        record["kind"].lower(),
        record["version"],
        executable,
        runtime,
        tuple(sorted(raw_environment.items())),
    )


def _save_hosts(
    hosts: tuple[EmbeddedHost, ...],
    user_home: Path | None,
) -> None:
    path = host_registry_path(user_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "hosts": [
            {
                "kind": host.kind,
                "version": host.version,
                "executable": str(host.executable),
                "implementation": host.runtime.implementation,
                "python_version": host.runtime.version,
                "abi": host.runtime.abi,
                "platform": host.runtime.platform,
                "library_paths": [str(item) for item in host.runtime.library_paths],
                "environment": dict(host.environment),
            }
            for host in sorted(
                hosts,
                key=lambda item: (
                    item.kind,
                    runtime_version_key(item.version),
                    str(item.executable),
                ),
            )
        ],
    }
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix="registry.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
        raise NodePhellError(f"cannot write host registry {path}: {error}") from error
