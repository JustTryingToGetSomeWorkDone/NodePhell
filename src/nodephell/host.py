# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Mapping, NoReturn
from urllib.request import Request, urlopen

from .errors import NodePhellError
from .launcher import Resolution, resolve
from .metadata import (
    HostArtifact,
    HostRequirement,
    host_artifact_from_mapping,
)
from .runtime import Runtime, data_root
from .store import PackageSelection, package_environment
from .versions import matches_runtime, release_tuple, runtime_version_key


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
_FREECAD_RELEASES_URL = (
    "https://api.github.com/repos/FreeCAD/FreeCAD/releases?per_page=100"
)
_FREECAD_ASSET = re.compile(
    r"^FreeCAD_(?P<version>[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?)"
    r"-Linux-(?P<arch>x86_64|aarch64)-py(?P<python>[0-9]+)\.AppImage$"
)


@dataclass(frozen=True)
class EmbeddedHost:
    kind: str
    version: str
    executable: Path
    runtime: Runtime
    environment: tuple[tuple[str, str], ...] = ()
    artifact: HostArtifact | None = None

    @property
    def identifier(self) -> str:
        return "-".join((self.kind, self.version, self.runtime.abi))


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
    artifact: HostArtifact | None = None,
) -> EmbeddedHost:
    probed = probe_host(executable)
    if artifact is not None:
        _validate_probed_artifact(probed, artifact)
    host = EmbeddedHost(
        probed.kind,
        probed.version,
        probed.executable,
        probed.runtime,
        probed.environment,
        artifact,
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
    asset = artifact or resolve_host_artifact(requirement, runtime)
    _validate_host_artifact(asset, requirement, runtime)
    target = host_store(asset, user_home)
    if target.exists():
        return _register_installed_host(target, asset, user_home)

    announce = progress if progress is not None else lambda message: None
    announce(f"Downloading FreeCAD {asset.version} host")
    with tempfile.TemporaryDirectory(prefix="nodephell-host-") as temporary:
        temporary_path = Path(temporary)
        appimage = temporary_path / asset.name
        _download(asset.url, appimage)
        _verify_host_artifact(appimage, asset)
        extracted = temporary_path / "extracted"
        extracted.mkdir()
        _extract_appimage(appimage, extracted)
        root = extracted / "squashfs-root"
        executable = root / "usr" / "bin" / "freecadcmd"
        probed = probe_host(executable)
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
    announce(f"Installed FreeCAD host at {target}")
    return _register_installed_host(target, asset, user_home)


def resolve_host_artifact(
    requirement: HostRequirement,
    runtime: Runtime,
) -> HostArtifact:
    if requirement.kind != "freecad":
        raise NodePhellError(
            f"automatic host acquisition does not support {requirement.kind!r}"
        )
    arch, python_tag = _asset_parameters(runtime)
    data = _json_url(_FREECAD_RELEASES_URL)
    if not isinstance(data, list):
        raise NodePhellError("FreeCAD release data is invalid")

    candidates: list[HostArtifact] = []
    for release in data:
        if not isinstance(release, dict) or release.get("draft") is True:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        for entry in assets:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            url = entry.get("browser_download_url")
            digest = entry.get("digest")
            if not all(isinstance(item, str) for item in (name, url, digest)):
                continue
            match = _FREECAD_ASSET.fullmatch(name)
            if (
                match is None
                or match.group("arch") != arch
                or match.group("python") != python_tag
            ):
                continue
            version = match.group("version")
            if not matches_runtime(version, requirement.requires):
                continue
            algorithm, separator, hash_value = digest.partition(":")
            if separator != ":":
                continue
            try:
                candidates.append(
                    HostArtifact(
                        requirement.kind,
                        version,
                        runtime.platform,
                        name,
                        url,
                        ((algorithm, hash_value),),
                    )
                )
            except NodePhellError:
                continue
    if not candidates:
        requirement_text = requirement.requires or "any version"
        raise NodePhellError(
            f"no downloadable FreeCAD host satisfies {requirement_text!r} "
            f"for {runtime.platform} and Python {python_tag}"
        )
    return max(candidates, key=lambda item: runtime_version_key(item.version))


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
            else "add one with 'nodephell host add /path/to/freecadcmd'"
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
        project.host_artifact,
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


def gui_executable(host: EmbeddedHost) -> Path:
    names = {
        "freecadcmd": "freecad",
        "FreeCADCmd": "FreeCAD",
    }
    name = names.get(host.executable.name)
    if name is None:
        raise NodePhellError(
            f"cannot derive FreeCAD GUI executable from {host.executable}"
        )
    executable = host.executable.with_name(name)
    if not executable.is_file():
        raise NodePhellError(f"FreeCAD GUI executable is missing: {executable}")
    return executable


def _execute_host(
    executable_path: Path,
    arguments: list[str],
    resolution: HostResolution,
) -> NoReturn:
    executable = str(executable_path)
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


def _asset_parameters(runtime: Runtime) -> tuple[str, str]:
    if sys.platform != "linux":
        raise NodePhellError("automatic FreeCAD downloads are Linux-only for now")
    platforms = {
        "linux-x86_64": "x86_64",
        "linux-aarch64": "aarch64",
    }
    arch = platforms.get(runtime.platform)
    if arch is None:
        raise NodePhellError(
            f"unsupported FreeCAD download platform: {runtime.platform}"
        )
    release = release_tuple(runtime.version)
    if len(release) < 2:
        raise NodePhellError(
            f"runtime version has no minor component: {runtime.version}"
        )
    return arch, f"{release[0]}{release[1]}"


def _validate_host_artifact(
    artifact: HostArtifact,
    requirement: HostRequirement,
    runtime: Runtime,
) -> None:
    arch, python_tag = _asset_parameters(runtime)
    match = _FREECAD_ASSET.fullmatch(artifact.name)
    if (
        artifact.kind != requirement.kind
        or artifact.platform != runtime.platform
        or match is None
        or match.group("version") != artifact.version
        or match.group("arch") != arch
        or match.group("python") != python_tag
    ):
        raise NodePhellError(
            f"embedded host artifact {artifact.name!r} does not match "
            f"{runtime.platform} with Python {python_tag}"
        )
    if not matches_runtime(artifact.version, requirement.requires):
        raise NodePhellError(
            f"locked embedded host {artifact.version} does not satisfy "
            f"{requirement.requires!r}"
        )


def _validate_probed_artifact(
    host: EmbeddedHost,
    artifact: HostArtifact,
) -> None:
    match = _FREECAD_ASSET.fullmatch(artifact.name)
    if (
        host.kind != artifact.kind
        or host.version != artifact.version
        or host.runtime.platform != artifact.platform
        or match is None
    ):
        raise NodePhellError(
            f"embedded host artifact identity mismatch: expected "
            f"{artifact.kind} {artifact.version} for {artifact.platform}, got "
            f"{host.kind} {host.version} for {host.runtime.platform}"
        )
    python_release = release_tuple(host.runtime.version)
    python_tag = "".join(str(part) for part in python_release[:2])
    if match.group("python") != python_tag:
        raise NodePhellError(
            f"embedded host artifact Python mismatch: expected "
            f"py{match.group('python')}, got Python {host.runtime.version}"
        )


def _register_installed_host(
    target: Path,
    artifact: HostArtifact,
    user_home: Path | None,
) -> EmbeddedHost:
    executable = target / "usr" / "bin" / "freecadcmd"
    if not executable.is_file():
        raise NodePhellError(
            f"installed FreeCAD host is incomplete: missing {executable}"
        )
    return register_host(executable, user_home, artifact)


def _json_url(url: str) -> object:
    request = Request(url, headers={"User-Agent": "NodePhell"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (OSError, json.JSONDecodeError) as error:
        raise NodePhellError(f"cannot read {url}: {error}") from error


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


def _extract_appimage(appimage: Path, destination: Path) -> None:
    try:
        appimage.chmod(appimage.stat().st_mode | stat.S_IXUSR)
        result = subprocess.run(
            [str(appimage), "--appimage-extract"],
            cwd=destination,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NodePhellError(
            f"cannot extract FreeCAD AppImage {appimage}: {error}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise NodePhellError(
            f"cannot extract FreeCAD AppImage {appimage}: {detail}"
        )
    if not (destination / "squashfs-root" / "AppRun").is_file():
        raise NodePhellError(
            f"FreeCAD AppImage produced no application root: {appimage}"
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
        )
        _validate_probed_artifact(provisional, artifact)
    return EmbeddedHost(
        record["kind"].lower(),
        record["version"],
        executable,
        runtime,
        tuple(sorted(raw_environment.items())),
        artifact,
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
