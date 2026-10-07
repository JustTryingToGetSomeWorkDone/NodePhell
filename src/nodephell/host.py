# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Mapping, NoReturn
from urllib.request import Request, urlopen

from .adapters import EmbeddedHost, adapter_for_executable, load_adapter
from .errors import NodePhellError
from .launcher import (
    Resolution,
    _package_command_arguments,
    _select_package_command,
    register_resolution,
    resolve_project,
)
from .metadata import (
    HostArtifact,
    HostRequirement,
    host_artifact_from_mapping,
    load_project,
)
from .runtime import Runtime, data_root
from .store import PackageSelection, package_environment, resolve_packages
from .versions import matches_runtime, runtime_version_key


@dataclass(frozen=True)
class HostResolution:
    host: EmbeddedHost
    project: Resolution


def host_registry_path(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "hosts" / "registry.json"


def host_store(
    artifact: HostArtifact,
    user_home: Path | None = None,
) -> Path:
    return (
        data_root(user_home)
        / "hosts"
        / artifact.kind
        / artifact.version
        / artifact.platform
        / artifact.sha256
    )


def probe_host(
    executable: Path,
    kind: str | None = None,
) -> EmbeddedHost:
    adapter = (
        load_adapter(kind)
        if kind is not None
        else adapter_for_executable(executable)
    )
    return adapter.probe(executable)


def register_host(
    executable: Path,
    user_home: Path | None = None,
    artifact: HostArtifact | None = None,
    kind: str | None = None,
) -> EmbeddedHost:
    adapter_kind = artifact.kind if artifact is not None else kind
    probed = probe_host(executable, adapter_kind)
    if artifact is not None:
        _validate_probed_artifact(probed, artifact)
    host = EmbeddedHost(
        probed.kind,
        probed.version,
        probed.executable,
        probed.runtime,
        probed.environment,
        artifact,
        probed.package_roots,
    )
    hosts = [
        item
        for item in load_hosts(user_home)
        if item.executable != host.executable
        and _registry_identity(item) != _registry_identity(host)
    ]
    hosts.append(host)
    _save_hosts(tuple(hosts), user_home)
    return host


def ensure_host(
    requirement: HostRequirement,
    runtime: Runtime,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
    artifact: HostArtifact | None = None,
) -> EmbeddedHost:
    hosts = load_hosts(user_home)
    try:
        return select_host(requirement, hosts, runtime, artifact)
    except NodePhellError:
        if artifact is None:
            raise
    installed = install_host(requirement, runtime, user_home, progress, artifact)
    return select_host(
        requirement,
        load_hosts(user_home),
        runtime,
        installed.artifact,
    )


def install_host(
    requirement: HostRequirement,
    runtime: Runtime,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
    artifact: HostArtifact | None = None,
) -> EmbeddedHost:
    adapter = load_adapter(requirement.kind)
    asset = artifact or adapter.resolve_artifact(requirement, runtime)
    _validate_host_artifact(asset, requirement, runtime)
    target = host_store(asset, user_home)
    if target.exists():
        return _register_installed_host(target, asset, user_home)

    announce = progress if progress is not None else lambda message: None
    announce(f"Downloading {adapter.display_name} {asset.version} host")
    with tempfile.TemporaryDirectory(prefix="nodephell-host-") as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / asset.name
        _download(asset.url, archive)
        _verify_host_artifact(archive, asset)
        extracted = temporary_path / "extracted"
        extracted.mkdir()
        root = adapter.extract(archive, extracted)
        executable = adapter.installed_executable(root)
        probed = probe_host(executable, adapter.kind)
        _validate_probed_artifact(probed, asset)

        staging: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{asset.version}-",
                    dir=target.parent,
                )
            )
            shutil.move(str(root), staging / "host")
            try:
                (staging / "host").rename(target)
            except FileExistsError:
                pass
        except OSError as error:
            raise NodePhellError(
                f"cannot install embedded host into {target}: {error}"
            ) from error
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    announce(f"Installed {adapter.display_name} host at {target}")
    return _register_installed_host(target, asset, user_home)


def resolve_host_artifact(
    requirement: HostRequirement,
    runtime: Runtime,
) -> HostArtifact:
    return load_adapter(requirement.kind).resolve_artifact(requirement, runtime)


def load_hosts(user_home: Path | None = None) -> tuple[EmbeddedHost, ...]:
    return _load_hosts(user_home, require_executables=True)


def _load_hosts(
    user_home: Path | None = None,
    *,
    require_executables: bool,
) -> tuple[EmbeddedHost, ...]:
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
    return tuple(
        _host_from_record(entry, path, require_executables)
        for entry in entries
    )


def unregister_host(
    executable: Path,
    user_home: Path | None = None,
) -> EmbeddedHost:
    target = executable.expanduser().resolve(strict=False)
    hosts = _load_hosts(user_home, require_executables=False)
    matches = tuple(host for host in hosts if host.executable == target)
    if not matches:
        raise NodePhellError(f"embedded host is not registered: {target}")
    remaining = tuple(host for host in hosts if host.executable != target)
    _save_hosts(remaining, user_home)
    return matches[0]


def delete_host(
    executable: Path,
    user_home: Path | None = None,
) -> tuple[EmbeddedHost, Path, bool]:
    target_executable = executable.expanduser().resolve(strict=False)
    hosts = _load_hosts(user_home, require_executables=False)
    matches = tuple(host for host in hosts if host.executable == target_executable)
    if not matches:
        raise NodePhellError(f"embedded host is not registered: {target_executable}")
    host = matches[0]
    if host.artifact is None:
        raise NodePhellError(
            f"refusing to delete externally managed host: {host.executable}"
        )
    managed = host_store(host.artifact, user_home).resolve(strict=False)
    if not host.executable.is_relative_to(managed):
        raise NodePhellError(
            f"registered host is outside its managed store: {host.executable}"
        )

    from .references import inspect_project_references, reference_problem

    references, issues = inspect_project_references(user_home)
    if issues:
        raise NodePhellError(
            "cannot prove the host is unused while project records are invalid"
        )
    for reference in references:
        problem = reference_problem(reference)
        if problem is not None and problem[1]:
            continue
        project = load_project(reference.project_root)
        if project.host is None or project.host.kind != host.kind:
            continue
        if not matches_runtime(host.version, project.host.requires):
            continue
        if (
            project.host_artifact is not None
            and project.host_artifact != host.artifact
        ):
            continue
        if (
            host.runtime.implementation == reference.runtime_identity[0]
            and host.runtime.abi == reference.runtime_identity[2]
            and host.runtime.platform == reference.runtime_identity[3]
        ):
            raise NodePhellError(
                f"host is still used by registered project: {reference.project_root}"
            )
    existed = managed.exists()
    unregister_host(host.executable, user_home)
    if existed:
        try:
            shutil.rmtree(managed)
        except OSError as error:
            raise NodePhellError(f"cannot delete managed host {managed}: {error}") from error
    return host, managed, existed


def select_host(
    requirement: HostRequirement,
    hosts: tuple[EmbeddedHost, ...],
    runtime: Runtime,
    artifact: HostArtifact | None = None,
) -> EmbeddedHost:
    candidates = [
        host
        for host in hosts
        if host.kind == requirement.kind
        and matches_runtime(host.version, requirement.requires)
        and _compatible_runtime(host.runtime, runtime)
        and (artifact is None or host.artifact == artifact)
    ]
    if not candidates:
        requirement_text = requirement.requires or "any version"
        remedy = (
            "run 'nodephell install'"
            if artifact is not None
            else (
                "add one with 'nodephell host add --kind "
                f"{requirement.kind} /path/to/executable'"
            )
        )
        raise NodePhellError(
            f"no registered {requirement.kind} host satisfies "
            f"{requirement_text!r} with Python ABI {runtime.abi}; "
            f"{remedy}"
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
    runtime, project = resolve_project(arguments, cwd, user_home)
    if project is None:
        raise NodePhellError("no NodePhell project was found for embedded host run")
    if project.host is None:
        raise NodePhellError(
            f"project {project.root} does not declare [tool.nodephell.host]"
        )
    host = select_host(
        project.host,
        load_hosts(user_home),
        runtime,
        project.host_artifact,
    )
    packages = resolve_packages(
        project,
        runtime,
        user_home,
        host.package_roots,
        include_ordinary=False,
    )
    return HostResolution(
        host,
        Resolution(runtime, project, packages, user_home),
    )


def host_environment(
    host: EmbeddedHost,
    packages: PackageSelection,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = package_environment(host.runtime, packages, base)
    environment.update(dict(host.environment))
    return load_adapter(host.kind).augment_environment(host, environment)


def execute_host(arguments: list[str], resolution: HostResolution) -> NoReturn:
    _execute_host(
        resolution.host.executable,
        arguments,
        resolution,
    )


def execute_host_gui(arguments: list[str], resolution: HostResolution) -> NoReturn:
    _execute_host(
        gui_executable(resolution.host),
        arguments,
        resolution,
    )


def execute_host_package_command(
    command: str,
    arguments: list[str],
    resolution: HostResolution,
) -> NoReturn:
    project = resolution.project
    assert project.project is not None
    selected = _select_package_command(
        command,
        project.project,
        project.runtime,
        project.packages,
        project.user_home,
    )
    _execute_host(
        resolution.host.executable,
        _package_command_arguments(selected, arguments),
        resolution,
    )


def gui_executable(host: EmbeddedHost) -> Path:
    return load_adapter(host.kind).gui_executable(host)


def _execute_host(
    executable_path: Path,
    arguments: list[str],
    resolution: HostResolution,
) -> NoReturn:
    register_resolution(resolution.project)
    executable = str(executable_path)
    host_arguments = load_adapter(resolution.host.kind).launch_arguments(
        resolution.project.packages
    )
    try:
        os.execvpe(
            executable,
            [executable, *host_arguments, *arguments],
            host_environment(
                resolution.host,
                resolution.project.packages,
            ),
        )
    except OSError as error:
        raise NodePhellError(f"cannot execute embedded host {executable}: {error}") from error


def _compatible_runtime(host: Runtime, runtime: Runtime) -> bool:
    return (
        host.implementation == runtime.implementation
        and host.abi == runtime.abi
        and host.platform == runtime.platform
    )


def _validate_host_artifact(
    artifact: HostArtifact,
    requirement: HostRequirement,
    runtime: Runtime,
) -> None:
    if artifact.kind != requirement.kind or artifact.platform != runtime.platform:
        raise NodePhellError(
            f"embedded host artifact {artifact.name!r} does not match "
            f"{requirement.kind} on {runtime.platform}"
        )
    if not matches_runtime(artifact.version, requirement.requires):
        raise NodePhellError(
            f"locked embedded host {artifact.version} does not satisfy "
            f"{requirement.requires!r}"
        )
    load_adapter(requirement.kind).validate_artifact(artifact, runtime)


def _validate_probed_artifact(
    host: EmbeddedHost,
    artifact: HostArtifact,
) -> None:
    if (
        host.kind != artifact.kind
        or host.version != artifact.version
        or host.runtime.platform != artifact.platform
    ):
        raise NodePhellError(
            f"embedded host artifact identity mismatch: expected "
            f"{artifact.kind} {artifact.version} for {artifact.platform}, got "
            f"{host.kind} {host.version} for {host.runtime.platform}"
        )
    load_adapter(host.kind).validate_probed_artifact(host, artifact)


def _register_installed_host(
    target: Path,
    artifact: HostArtifact,
    user_home: Path | None,
) -> EmbeddedHost:
    adapter = load_adapter(artifact.kind)
    executable = adapter.installed_executable(target)
    if not executable.is_file():
        raise NodePhellError(
            f"installed {adapter.display_name} host is incomplete: "
            f"missing {executable}"
        )
    return register_host(executable, user_home, artifact, adapter.kind)


def _download(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": "NodePhell"})
    try:
        with urlopen(request, timeout=60) as response, target.open("wb") as file:
            shutil.copyfileobj(response, file)
    except OSError as error:
        raise NodePhellError(
            f"cannot download embedded host artifact {url}: {error}"
        ) from error


def _verify_host_artifact(archive: Path, artifact: HostArtifact) -> None:
    hasher = hashlib.sha256()
    try:
        with archive.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                hasher.update(chunk)
    except OSError as error:
        raise NodePhellError(
            f"cannot hash embedded host artifact {archive}: {error}"
        ) from error
    actual = hasher.hexdigest()
    if actual != artifact.sha256:
        raise NodePhellError(
            f"embedded host artifact SHA-256 mismatch for {artifact.name}: "
            f"expected {artifact.sha256}, got {actual}"
        )


def _registry_identity(
    host: EmbeddedHost,
) -> tuple[str, str, str, str, str | None]:
    return (
        host.kind,
        host.version,
        host.runtime.abi,
        host.runtime.platform,
        host.artifact.sha256 if host.artifact is not None else None,
    )


def _artifact_record(artifact: HostArtifact) -> dict[str, object]:
    return {
        "kind": artifact.kind,
        "version": artifact.version,
        "platform": artifact.platform,
        "name": artifact.name,
        "url": artifact.url,
        "hashes": dict(artifact.hashes),
    }


def _host_from_record(
    record: object,
    path: Path,
    require_executable: bool = True,
) -> EmbeddedHost:
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
    if require_executable and not executable.is_file():
        raise NodePhellError(f"registered embedded host is missing: {executable}")
    raw_libraries = record.get("library_paths", [])
    raw_environment = record.get("environment", {})
    raw_package_roots = record.get("package_roots", [])
    if not isinstance(raw_libraries, list) or not all(
        isinstance(item, str) for item in raw_libraries
    ):
        raise NodePhellError(f"invalid host library paths in {path}")
    if not isinstance(raw_environment, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_environment.items()
    ):
        raise NodePhellError(f"invalid host environment in {path}")
    if not isinstance(raw_package_roots, list) or not all(
        isinstance(item, str) for item in raw_package_roots
    ):
        raise NodePhellError(f"invalid host package roots in {path}")
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
    artifact_record = record.get("artifact")
    artifact = (
        host_artifact_from_mapping(artifact_record, path)
        if artifact_record is not None
        else None
    )
    if artifact is not None:
        provisional = EmbeddedHost(
            record["kind"].lower(),
            record["version"],
            executable,
            runtime,
            tuple(sorted(raw_environment.items())),
            package_roots=tuple(
                Path(item).expanduser().resolve(strict=False)
                for item in raw_package_roots
            ),
        )
        _validate_probed_artifact(provisional, artifact)
    return EmbeddedHost(
        record["kind"].lower(),
        record["version"],
        executable,
        runtime,
        tuple(sorted(raw_environment.items())),
        artifact,
        tuple(
            Path(item).expanduser().resolve(strict=False)
            for item in raw_package_roots
        ),
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
                "package_roots": [str(item) for item in host.package_roots],
                **(
                    {"artifact": _artifact_record(host.artifact)}
                    if host.artifact is not None
                    else {}
                ),
            }
            for host in sorted(
                hosts,
                key=lambda item: (
                    item.kind,
                    runtime_version_key(item.version),
                    item.artifact.sha256 if item.artifact is not None else "",
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
