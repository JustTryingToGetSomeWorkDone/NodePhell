# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote, urlsplit

from .errors import NodePhellError
from .versions import matches_runtime, release_tuple


_PACKAGE_NAME = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
)
_PACKAGE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")
_ARTIFACT_PLATFORM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXACT_DEPENDENCY = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\[[^]]+\])?\s*==\s*"
    r"([A-Za-z0-9][A-Za-z0-9._+!-]*)\s*$"
)


@dataclass(frozen=True)
class PackagePin:
    name: str
    version: str
    hashes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if _PACKAGE_NAME.fullmatch(self.name) is None:
            raise NodePhellError(f"invalid package name: {self.name!r}")
        if _PACKAGE_VERSION.fullmatch(self.version) is None:
            raise NodePhellError(f"invalid package version: {self.version!r}")
        for algorithm, digest in self.hashes:
            if not algorithm or not digest:
                raise NodePhellError(
                    f"invalid package hash for {self.name}=={self.version}"
                )


@dataclass(frozen=True)
class RuntimeArtifact:
    implementation: str
    version: str
    platform: str
    name: str
    url: str
    hashes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.implementation != "cpython":
            raise NodePhellError(
                f"unsupported runtime implementation: {self.implementation!r}"
            )
        release_tuple(self.version)
        if _ARTIFACT_PLATFORM.fullmatch(self.platform) is None:
            raise NodePhellError(
                f"invalid runtime artifact platform: {self.platform!r}"
            )
        if not self.name or Path(self.name).name != self.name:
            raise NodePhellError(f"invalid runtime artifact name: {self.name!r}")
        parsed_url = urlsplit(self.url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise NodePhellError(f"invalid runtime artifact URL: {self.url!r}")
        if Path(unquote(parsed_url.path)).name != self.name:
            raise NodePhellError(
                "runtime artifact URL does not match its archive name"
            )
        hashes = dict(self.hashes)
        if len(hashes) != len(self.hashes):
            raise NodePhellError("duplicate runtime artifact hash algorithm")
        if set(hashes) != {"sha256"} or _SHA256.fullmatch(hashes["sha256"]) is None:
            raise NodePhellError("runtime artifact requires one valid SHA-256 hash")

    @property
    def sha256(self) -> str:
        return dict(self.hashes)["sha256"]


@dataclass(frozen=True)
class HostRequirement:
    kind: str
    requires: str | None = None

    def __post_init__(self) -> None:
        if self.kind != "freecad":
            raise NodePhellError(f"unsupported embedded host: {self.kind!r}")
        if self.requires is not None:
            matches_runtime("0.0.0", self.requires)


@dataclass(frozen=True)
class Project:
    root: Path
    metadata_file: Path
    requires_python: str | None
    packages: tuple[PackagePin, ...]
    runtime_artifact: RuntimeArtifact | None = None
    host: HostRequirement | None = None

    @property
    def runtime_requirement(self) -> str | None:
        if self.runtime_artifact is not None:
            return f"=={self.runtime_artifact.version}"
        return self.requires_python


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def invocation_start(arguments: list[str], cwd: Path) -> Path:
    """Return the best project-discovery start for Python-style arguments."""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            index += 1
            if index < len(arguments) and arguments[index] != "-":
                return _script_start(arguments[index], cwd)
            return cwd
        if argument in {"-c", "-m"}:
            return cwd
        if argument in {"-W", "-X", "--check-hash-based-pycs"}:
            index += 2
            continue
        if argument.startswith("-") and argument != "-":
            index += 1
            continue
        if argument == "-":
            return cwd
        return _script_start(argument, cwd)
    return cwd


def _script_start(argument: str, cwd: Path) -> Path:
    script = Path(argument).expanduser()
    if not script.is_absolute():
        script = cwd / script
    return script.resolve(strict=False).parent


def discover_project(start: Path) -> Path | None:
    directory = start.expanduser().resolve(strict=False)
    if directory.is_file():
        directory = directory.parent
    while True:
        if (directory / "pylock.toml").is_file() or (
            directory / "pyproject.toml"
        ).is_file():
            return directory
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


def load_project(root: Path) -> Project:
    lock_path = root / "pylock.toml"
    project_path = root / "pyproject.toml"
    project_data = _read_toml(project_path) if project_path.is_file() else {}
    project_table = project_data.get("project", {})
    if not isinstance(project_table, dict):
        raise NodePhellError(f"invalid [project] table in {project_path}")
    project_host = _host_requirement(project_data, project_path)

    if lock_path.is_file():
        lock_data = _read_toml(lock_path)
        if lock_data.get("lock-version") != "1.0":
            raise NodePhellError(
                f"unsupported lock version in {lock_path}; expected 1.0"
            )
        packages = _locked_packages(lock_data, lock_path)
        runtime_artifact = _locked_runtime(lock_data, lock_path)
        host = _host_requirement(lock_data, lock_path) or project_host
        requires_python = lock_data.get("requires-python")
        if requires_python is None:
            requires_python = project_table.get("requires-python")
        _validate_requires_python(requires_python, lock_path)
        if (
            runtime_artifact is not None
            and requires_python is not None
            and not matches_runtime(runtime_artifact.version, requires_python)
        ):
            raise NodePhellError(
                f"locked runtime {runtime_artifact.version} does not satisfy "
                f"{requires_python!r} in {lock_path}"
            )
        return Project(
            root,
            lock_path,
            requires_python,
            packages,
            runtime_artifact,
            host,
        )

    if not project_path.is_file():
        raise NodePhellError(f"no project metadata found below {root}")
    packages = _project_packages(
        project_table.get("dependencies", ()), project_path
    )
    requires_python = project_table.get("requires-python")
    _validate_requires_python(requires_python, project_path)
    return Project(
        root,
        project_path,
        requires_python,
        packages,
        host=project_host,
    )


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise NodePhellError(f"cannot read {path}: {error}") from error


def _locked_packages(data: dict, path: Path) -> tuple[PackagePin, ...]:
    result: list[PackagePin] = []
    seen: dict[str, str] = {}
    entries = data.get("packages", ())
    if not isinstance(entries, (list, tuple)):
        raise NodePhellError(f"invalid packages list in {path}")
    for package in entries:
        if not isinstance(package, dict):
            raise NodePhellError(f"invalid package entry in {path}")
        if package.get("marker"):
            raise NodePhellError(
                f"environment markers are not supported yet: {path}"
            )
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise NodePhellError(f"unversioned package entry in {path}")
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None and previous != version:
            raise NodePhellError(
                f"{name} has conflicting locked versions in {path}"
            )
        if previous is None:
            seen[normalized] = version
            result.append(PackagePin(name, version, _locked_hashes(package, path)))
    return tuple(result)


def _locked_runtime(data: dict, path: Path) -> RuntimeArtifact | None:
    nodephell = _nodephell_table(data, path)
    runtime = nodephell.get("runtime")
    if runtime is None:
        return None
    return runtime_artifact_from_mapping(runtime, path)


def _host_requirement(data: dict, path: Path) -> HostRequirement | None:
    nodephell = _nodephell_table(data, path)
    host = nodephell.get("host")
    if host is None:
        return None
    if not isinstance(host, dict):
        raise NodePhellError(f"invalid embedded host in {path}")
    kind = host.get("kind")
    requires = host.get("requires")
    if not isinstance(kind, str) or (
        requires is not None and not isinstance(requires, str)
    ):
        raise NodePhellError(f"invalid embedded host in {path}")
    try:
        return HostRequirement(kind.lower(), requires)
    except NodePhellError as error:
        raise NodePhellError(f"invalid embedded host in {path}: {error}") from error


def _nodephell_table(data: dict, path: Path) -> dict:
    tool = data.get("tool")
    if tool is None:
        return {}
    if not isinstance(tool, dict):
        raise NodePhellError(f"invalid [tool] table in {path}")
    nodephell = tool.get("nodephell")
    if nodephell is None:
        return {}
    if not isinstance(nodephell, dict):
        raise NodePhellError(f"invalid [tool.nodephell] table in {path}")
    return nodephell


def runtime_artifact_from_mapping(
    value: object,
    path: Path,
) -> RuntimeArtifact:
    if not isinstance(value, dict):
        raise NodePhellError(f"invalid runtime artifact in {path}")
    required = ("implementation", "version", "platform", "name", "url")
    if not all(isinstance(value.get(key), str) for key in required):
        raise NodePhellError(f"incomplete runtime artifact in {path}")
    hashes = _hash_table(value.get("hashes"), path)
    try:
        return RuntimeArtifact(
            value["implementation"].lower(),
            value["version"],
            value["platform"],
            value["name"],
            value["url"],
            hashes,
        )
    except NodePhellError as error:
        raise NodePhellError(f"invalid runtime artifact in {path}: {error}") from error


def _locked_hashes(package: dict, path: Path) -> tuple[tuple[str, str], ...]:
    result: set[tuple[str, str]] = set()
    wheels = package.get("wheels", ())
    if wheels is None:
        wheels = ()
    if not isinstance(wheels, (list, tuple)):
        raise NodePhellError(f"invalid wheel entries in {path}")
    for wheel in wheels:
        if not isinstance(wheel, dict):
            raise NodePhellError(f"invalid wheel entry in {path}")
        result.update(_hash_table(wheel.get("hashes"), path))
    sdist = package.get("sdist")
    if sdist is not None:
        if not isinstance(sdist, dict):
            raise NodePhellError(f"invalid sdist entry in {path}")
        result.update(_hash_table(sdist.get("hashes"), path))
    return tuple(sorted(result))


def _hash_table(value: object, path: Path) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise NodePhellError(f"invalid hash table in {path}")
    result = []
    for algorithm, digest in value.items():
        if not isinstance(algorithm, str) or not isinstance(digest, str):
            raise NodePhellError(f"invalid hash entry in {path}")
        result.append((algorithm, digest))
    return tuple(result)


def _project_packages(dependencies: object, path: Path) -> tuple[PackagePin, ...]:
    if not isinstance(dependencies, (list, tuple)):
        raise NodePhellError(f"invalid project dependencies in {path}")
    result: list[PackagePin] = []
    seen: dict[str, str] = {}
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise NodePhellError(f"invalid dependency in {path}")
        match = _EXACT_DEPENDENCY.fullmatch(dependency)
        if match is None:
            raise NodePhellError(
                f"prototype requires exact dependency pins; found "
                f"{dependency!r} in {path}"
            )
        name, version = match.groups()
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None and previous != version:
            raise NodePhellError(
                f"{name} has conflicting pinned versions in {path}"
            )
        if previous is None:
            seen[normalized] = version
            result.append(PackagePin(name, version))
    return tuple(result)


def _validate_requires_python(value: object, path: Path) -> None:
    if value is not None and not isinstance(value, str):
        raise NodePhellError(f"invalid requires-python value in {path}")
