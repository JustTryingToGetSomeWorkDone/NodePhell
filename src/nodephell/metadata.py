# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import shlex
import tomllib
from urllib.parse import unquote, urlsplit

from .errors import NodePhellError
from .versions import matches_runtime, release_tuple


_PACKAGE_NAME = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$"
)
_PACKAGE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]*$")
_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\[([A-Za-z0-9._-]+(?:\s*,\s*[A-Za-z0-9._-]+)*)\])?"
    r"\s*(.*?)\s*$"
)
_REQUIREMENT_CLAUSE = re.compile(
    r"^(===|==|!=|<=|>=|~=|<|>)\s*([A-Za-z0-9][A-Za-z0-9._+!*-]*)$"
)
_ARTIFACT_PLATFORM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HOST_KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_POETRY_RELEASE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")
_POETRY_WILDCARD = re.compile(r"^([0-9]+(?:\.[0-9]+)*)\.\*$")

STANDARD_LOCK_FILENAME = "pylock.toml"
NODEPHELL_LOCK_FILENAME = "nodephell.lock.toml"
LOCK_FILENAMES = (NODEPHELL_LOCK_FILENAME, STANDARD_LOCK_FILENAME)


@dataclass(frozen=True)
class PackageArtifact:
    kind: str
    name: str
    url: str
    hashes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.kind not in {"wheel", "sdist"}:
            raise NodePhellError(f"invalid package artifact kind: {self.kind!r}")
        if (
            not self.name
            or Path(self.name).name != self.name
            or any(character.isspace() for character in self.name)
        ):
            raise NodePhellError(f"invalid package artifact name: {self.name!r}")
        parsed_url = urlsplit(self.url)
        if (
            not parsed_url.scheme
            or any(character.isspace() for character in self.url)
            or parsed_url.username is not None
            or parsed_url.password is not None
            or Path(unquote(parsed_url.path)).name != self.name
        ):
            raise NodePhellError(f"invalid package artifact URL: {self.url!r}")
        hashes = dict(self.hashes)
        if len(hashes) != len(self.hashes):
            raise NodePhellError("duplicate package artifact hash algorithm")
        if "sha256" not in hashes or _SHA256.fullmatch(hashes["sha256"]) is None:
            raise NodePhellError(
                f"package artifact {self.name!r} requires a valid SHA-256 hash"
            )

    @property
    def sha256(self) -> str:
        return dict(self.hashes)["sha256"]


@dataclass(frozen=True)
class PackagePin:
    name: str
    version: str
    artifacts: tuple[PackageArtifact, ...] = ()

    def __post_init__(self) -> None:
        if _PACKAGE_NAME.fullmatch(self.name) is None:
            raise NodePhellError(f"invalid package name: {self.name!r}")
        if _PACKAGE_VERSION.fullmatch(self.version) is None:
            raise NodePhellError(f"invalid package version: {self.version!r}")

    @property
    def hashes(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                {
                    item
                    for artifact in self.artifacts
                    for item in artifact.hashes
                }
            )
        )


@dataclass(frozen=True)
class PackageRequirement:
    name: str
    extras: tuple[str, ...] = ()
    specifiers: tuple[tuple[str, str], ...] = ()
    marker: str | None = None
    url: str | None = None

    @property
    def text(self) -> str:
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        if self.url is None:
            suffix = ",".join(
                f"{operator}{version}" for operator, version in self.specifiers
            )
        else:
            suffix = f" @ {self.url}"
        requirement = f"{self.name}{extras}{suffix}"
        if self.marker is not None:
            requirement += f"; {self.marker}"
        return requirement

    @property
    def fingerprint_text(self) -> str:
        extras = tuple(sorted(extra.lower() for extra in self.extras))
        normalized = PackageRequirement(
            normalize_name(self.name),
            extras,
            self.specifiers,
            self.marker,
            self.url,
        )
        return normalized.text


@dataclass(frozen=True)
class PackageIndex:
    name: str
    url: str
    explicit: bool = False


@dataclass(frozen=True)
class PackageSource:
    name: str
    index: str | None = None
    path: Path | None = None
    marker: str | None = None


@dataclass(frozen=True)
class ApplicationDeclaration:
    adapter: Path
    executable: Path | None = None
    name: str | None = None


@dataclass(frozen=True)
class DependencyOption:
    name: str
    requirements: tuple[str, ...]
    includes: tuple[str, ...] = ()
    available: bool = True


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
        if _HOST_KIND.fullmatch(self.kind) is None:
            raise NodePhellError(f"invalid embedded host kind: {self.kind!r}")
        if self.requires is not None:
            try:
                for clause in self.requires.split(","):
                    matches_runtime("0.0.0", clause)
            except NodePhellError as error:
                raise NodePhellError(
                    f"unsupported embedded host version requirement: "
                    f"{self.requires!r}"
                ) from error


@dataclass(frozen=True)
class HostArtifact:
    kind: str
    version: str
    platform: str
    name: str
    url: str
    hashes: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if _HOST_KIND.fullmatch(self.kind) is None:
            raise NodePhellError(f"invalid embedded host kind: {self.kind!r}")
        release_tuple(self.version)
        if _ARTIFACT_PLATFORM.fullmatch(self.platform) is None:
            raise NodePhellError(
                f"invalid embedded host artifact platform: {self.platform!r}"
            )
        if not self.name or Path(self.name).name != self.name:
            raise NodePhellError(
                f"invalid embedded host artifact name: {self.name!r}"
            )
        parsed_url = urlsplit(self.url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise NodePhellError(
                f"invalid embedded host artifact URL: {self.url!r}"
            )
        if Path(unquote(parsed_url.path)).name != self.name:
            raise NodePhellError(
                "embedded host artifact URL does not match its archive name"
            )
        hashes = dict(self.hashes)
        if len(hashes) != len(self.hashes):
            raise NodePhellError("duplicate embedded host artifact hash algorithm")
        if set(hashes) != {"sha256"} or _SHA256.fullmatch(hashes["sha256"]) is None:
            raise NodePhellError(
                "embedded host artifact requires one valid SHA-256 hash"
            )

    @property
    def sha256(self) -> str:
        return dict(self.hashes)["sha256"]


@dataclass(frozen=True)
class Project:
    root: Path
    metadata_file: Path
    requires_python: str | None
    packages: tuple[PackagePin, ...]
    runtime_artifact: RuntimeArtifact | None = None
    host: HostRequirement | None = None
    host_artifact: HostArtifact | None = None
    requirements: tuple[PackageRequirement, ...] = ()
    source_fingerprint: str | None = None
    application: ApplicationDeclaration | None = None
    has_build_system: bool = False
    name: str | None = None
    optional_dependencies: tuple[DependencyOption, ...] = ()
    dependency_groups: tuple[DependencyOption, ...] = ()
    selected_extras: tuple[str, ...] = ()
    selected_groups: tuple[str, ...] = ()
    dynamic_dependencies: bool = False
    package_indexes: tuple[PackageIndex, ...] = ()
    package_sources: tuple[PackageSource, ...] = ()
    requirement_files: tuple[Path, ...] = ()
    replace_requirements: bool = False
    local_projects: tuple[Path, ...] = ()

    @property
    def runtime_requirement(self) -> str | None:
        if self.runtime_artifact is not None:
            return f"=={self.runtime_artifact.version}"
        return self.requires_python


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def project_lock_path(root: Path) -> Path:
    candidates = tuple(
        root / name
        for name in LOCK_FILENAMES
        if (root / name).exists() or (root / name).is_symlink()
    )
    if len(candidates) > 1:
        names = " and ".join(path.name for path in candidates)
        raise NodePhellError(
            f"project has multiple lock files: {names}; keep only the lock "
            "that should control this project"
        )
    if candidates:
        return candidates[0]
    return root / STANDARD_LOCK_FILENAME


def is_project_lock_path(path: Path, root: Path) -> bool:
    return path.parent == root and path.name in LOCK_FILENAMES


def lock_needs_migration(root: Path) -> bool:
    path = project_lock_path(root)
    if not path.is_file() or path.is_symlink():
        return False
    data = _read_toml(path)
    custom = _lock_has_nodephell_install_data(data, path)
    expected = NODEPHELL_LOCK_FILENAME if custom else STANDARD_LOCK_FILENAME
    if path.name != expected:
        return True
    return path.name == STANDARD_LOCK_FILENAME and (
        data.get("created-by") != "nodephell" or "packages" not in data
    )


def parse_package_requirement(
    value: str,
    path: Path | None = None,
) -> PackageRequirement:
    match = _REQUIREMENT.fullmatch(value)
    location = f" in {path}" if path is not None else ""
    if match is None:
        raise NodePhellError(f"unsupported package requirement {value!r}{location}")
    name, extras_text, requirement_text = match.groups()
    specifier_text, separator, marker_text = requirement_text.partition(";")
    marker = marker_text.strip() if separator else None
    if separator and not marker:
        raise NodePhellError(f"unsupported package requirement {value!r}{location}")
    extras = ()
    if extras_text:
        extras = tuple(
            normalize_name(part.strip()) for part in extras_text.split(",")
        )
        if len(set(extras)) != len(extras):
            raise NodePhellError(
                f"duplicate normalized extra in package requirement "
                f"{value!r}{location}"
            )
    specifiers: list[tuple[str, str]] = []
    direct_url = None
    specifier_text = specifier_text.strip()
    if specifier_text.startswith("@"):
        direct_url = specifier_text[1:].strip()
        parsed = urlsplit(direct_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or any(character.isspace() for character in direct_url)
        ):
            raise NodePhellError(
                f"unsupported package requirement {value!r}{location}"
            )
    elif specifier_text:
        for clause in specifier_text.split(","):
            clause_match = _REQUIREMENT_CLAUSE.fullmatch(clause.strip())
            if clause_match is None:
                raise NodePhellError(
                    f"unsupported package requirement {value!r}{location}"
                )
            specifiers.append(clause_match.groups())
    return PackageRequirement(
        name,
        extras,
        tuple(specifiers),
        marker,
        direct_url,
    )


def normalize_requirement_files(
    root: Path,
    values: tuple[Path, ...],
) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        path = value.expanduser()
        if not path.is_absolute():
            path = root / path
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise NodePhellError(
                f"requirements file must be a project-relative file: {value}"
            ) from error
        if not resolved.is_file():
            raise NodePhellError(f"requirements file is not a file: {value}")
        if relative not in seen:
            seen.add(relative)
            result.append(relative)
    return tuple(result)


def project_definition_fingerprint(project: Project) -> str:
    host = None
    if project.host is not None:
        host = {
            "kind": project.host.kind,
            "requires": project.host.requires,
        }
    data = {
        "requires-python": project.requires_python,
        "dynamic-dependencies": project.dynamic_dependencies,
        "dependencies": sorted(
            requirement.fingerprint_text for requirement in project.requirements
        ),
        "package-indexes": [
            {
                "name": index.name,
                "url": index.url,
                "explicit": index.explicit,
            }
            for index in project.package_indexes
        ],
        "package-sources": [
            {
                "name": source.name,
                "index": source.index,
                "path": source.path.as_posix() if source.path is not None else None,
                "marker": source.marker,
                "fingerprint": (
                    _local_project_fingerprint(project.root / source.path)
                    if source.path is not None
                    else None
                ),
            }
            for source in project.package_sources
        ],
        "requirements-profile": {
            "replace": project.replace_requirements,
            "files": _requirement_file_fingerprints(
                project.root,
                project.requirement_files,
            ),
        },
        "host": host,
        "application": (
            {
                "adapter": project.application.adapter.as_posix(),
                "executable": (
                    project.application.executable.as_posix()
                    if project.application.executable is not None
                    else None
                ),
                "name": project.application.name,
            }
            if project.application is not None
            else None
        ),
    }
    if project.selected_extras or project.selected_groups:
        data["selection"] = {
            "extras": sorted(project.selected_extras),
            "groups": sorted(project.selected_groups),
            "optional-dependencies": (
                _option_fingerprint(project.optional_dependencies)
                if project.selected_extras
                else []
            ),
            "dependency-groups": (
                _option_fingerprint(project.dependency_groups)
                if project.selected_groups
                else []
            ),
        }
    encoded = json.dumps(
        data,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def lock_matches_project_definition(root: Path) -> bool:
    project_path = root / "pyproject.toml"
    lock_path = project_lock_path(root)
    if not project_path.is_file() or not lock_path.is_file():
        return False
    locked = load_project(root)
    if locked.source_fingerprint is None:
        return False
    definition = replace(
        load_project_definition(root),
        selected_extras=locked.selected_extras,
        selected_groups=locked.selected_groups,
        requirement_files=locked.requirement_files,
        replace_requirements=locked.replace_requirements,
    )
    return locked.source_fingerprint == project_definition_fingerprint(definition)


def _requirement_file_fingerprints(
    root: Path,
    files: tuple[Path, ...],
) -> list[dict[str, str]]:
    records: dict[Path, str] = {}
    active: set[Path] = set()

    def visit(relative: Path) -> None:
        if relative in active:
            raise NodePhellError(
                f"requirements files contain an include cycle at {relative}"
            )
        if relative in records:
            return
        active.add(relative)
        path = root / relative
        try:
            contents = path.read_bytes()
            text = contents.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise NodePhellError(f"cannot read requirements file {path}: {error}")
        records[relative] = hashlib.sha256(contents).hexdigest()
        logical = text.replace("\\\r\n", "").replace("\\\n", "")
        for line in logical.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                parts = shlex.split(stripped, comments=True)
            except ValueError as error:
                raise NodePhellError(
                    f"invalid requirements line in {path}: {error}"
                ) from error
            include = _requirements_include(parts)
            if include is None:
                continue
            nested = Path(include).expanduser()
            if not nested.is_absolute():
                nested = path.parent / nested
            try:
                nested_relative = nested.resolve(strict=True).relative_to(
                    root.resolve(strict=True)
                )
            except (OSError, ValueError) as error:
                raise NodePhellError(
                    f"included requirements file must remain inside the project: "
                    f"{include} in {path}"
                ) from error
            visit(nested_relative)
        active.remove(relative)

    for relative in files:
        visit(relative)
    return [
        {"path": path.as_posix(), "sha256": records[path]}
        for path in sorted(records, key=lambda item: item.as_posix())
    ]


def _local_project_fingerprint(root: Path) -> str:
    hasher = hashlib.sha256()
    found = False
    for name in ("pyproject.toml", "setup.cfg", "setup.py"):
        path = root / name
        if not path.is_file():
            continue
        found = True
        try:
            contents = path.read_bytes()
        except OSError as error:
            raise NodePhellError(f"cannot read local project metadata {path}: {error}")
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(contents)
        hasher.update(b"\0")
    if not found:
        raise NodePhellError(f"local source project has no build metadata: {root}")
    return hasher.hexdigest()


def _requirements_include(parts: list[str]) -> str | None:
    if len(parts) == 2 and parts[0] in {
        "-r",
        "--requirement",
        "-c",
        "--constraint",
    }:
        return parts[1]
    if len(parts) == 1:
        for prefix in ("--requirement=", "--constraint="):
            if parts[0].startswith(prefix):
                return parts[0][len(prefix) :]
        for prefix in ("-r", "-c"):
            if parts[0].startswith(prefix) and len(parts[0]) > len(prefix):
                return parts[0][len(prefix) :]
    return None


def _option_fingerprint(
    options: tuple[DependencyOption, ...],
) -> list[dict[str, object]]:
    return [
        {
            "name": option.name,
            "requirements": sorted(option.requirements),
            "includes": sorted(option.includes),
        }
        for option in sorted(options, key=lambda item: item.name)
    ]


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
        if any((directory / name).is_file() for name in LOCK_FILENAMES) or (
            directory / "pyproject.toml"
        ).is_file():
            return directory
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


def load_project(root: Path) -> Project:
    lock_path = project_lock_path(root)
    project_path = root / "pyproject.toml"
    project_data = _read_toml(project_path) if project_path.is_file() else {}
    project_table = project_data.get("project", {})
    if not isinstance(project_table, dict):
        raise NodePhellError(f"invalid [project] table in {project_path}")
    project_host = _host_requirement(project_data, project_path)
    application = _application_declaration(project_data, project_path)
    optional_dependencies = _optional_dependencies(project_table, project_path)
    dependency_groups = _dependency_groups(project_data, project_path)
    project_name = _project_name(project_table, project_path)
    dynamic_fields = _project_dynamic_fields(project_table, project_path)
    has_build_system = _has_build_system(project_data, project_path)
    dynamic_dependencies = "dependencies" in dynamic_fields
    package_indexes, package_sources = _uv_configuration(
        project_data,
        root,
        project_path,
    )
    _validate_dynamic_dependencies(
        dynamic_dependencies,
        project_name,
        has_build_system,
        project_path,
    )

    if lock_path.is_file():
        lock_data = _read_toml(lock_path)
        if lock_data.get("lock-version") != "1.0":
            raise NodePhellError(
                f"unsupported lock version in {lock_path}; expected 1.0"
            )
        _validate_lock_document(lock_data, lock_path)
        packages = _locked_packages(lock_data, lock_path)
        selected_extras, selected_groups = _locked_selection(lock_data, lock_path)
        requirement_files, replace_requirements, local_projects = (
            _locked_source_settings(lock_data, root, lock_path)
        )
        runtime_artifact = _locked_runtime(lock_data, lock_path)
        host = _host_requirement(lock_data, lock_path) or project_host
        host_artifact = _locked_host_artifact(lock_data, lock_path)
        if host_artifact is not None:
            if host is None or host.requires is None:
                host = HostRequirement(
                    host_artifact.kind,
                    f"=={host_artifact.version}",
                )
            elif not matches_runtime(host_artifact.version, host.requires):
                raise NodePhellError(
                    f"locked embedded host {host_artifact.version} does not "
                    f"satisfy {host.requires!r} in {lock_path}"
                )
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
            host_artifact,
            source_fingerprint=_locked_source_fingerprint(lock_data, lock_path),
            application=application,
            has_build_system=has_build_system,
            name=project_name,
            optional_dependencies=optional_dependencies,
            dependency_groups=dependency_groups,
            selected_extras=selected_extras,
            selected_groups=selected_groups,
            dynamic_dependencies=dynamic_dependencies,
            package_indexes=package_indexes,
            package_sources=package_sources,
            requirement_files=requirement_files,
            replace_requirements=replace_requirements,
            local_projects=local_projects,
        )

    return load_project_definition(root)


def load_project_definition(root: Path) -> Project:
    project_path = root / "pyproject.toml"
    if not project_path.is_file():
        raise NodePhellError(f"no pyproject.toml found in {root}")
    project_data = _read_toml(project_path)
    dynamic_dependencies = False
    if "project" in project_data:
        project_table = project_data["project"]
        if not isinstance(project_table, dict):
            raise NodePhellError(f"invalid [project] table in {project_path}")
        dynamic_fields = _project_dynamic_fields(project_table, project_path)
        dynamic_dependencies = "dependencies" in dynamic_fields
        requirements = (
            ()
            if dynamic_dependencies
            else _project_requirements(
                project_table.get("dependencies", ()), project_path
            )
        )
        requires_python = project_table.get("requires-python")
    else:
        project_table = {}
        poetry = _poetry_requirements(project_data, project_path)
        if poetry is None:
            requirements = ()
            requires_python = None
        else:
            requires_python, requirements = poetry
    _validate_requires_python(requires_python, project_path)
    has_build_system = _has_build_system(project_data, project_path)
    project_name = _project_name(project_table, project_path)
    _validate_dynamic_dependencies(
        dynamic_dependencies,
        project_name,
        has_build_system,
        project_path,
    )
    package_indexes, package_sources = _uv_configuration(
        project_data,
        root,
        project_path,
    )
    return Project(
        root,
        project_path,
        requires_python,
        (),
        host=_host_requirement(project_data, project_path),
        requirements=requirements,
        application=_application_declaration(project_data, project_path),
        has_build_system=has_build_system,
        name=project_name,
        optional_dependencies=_optional_dependencies(project_table, project_path),
        dependency_groups=_dependency_groups(project_data, project_path),
        dynamic_dependencies=dynamic_dependencies,
        package_indexes=package_indexes,
        package_sources=package_sources,
    )


def _uv_configuration(
    data: dict,
    root: Path,
    path: Path,
) -> tuple[tuple[PackageIndex, ...], tuple[PackageSource, ...]]:
    tool = data.get("tool")
    if tool is None:
        return (), ()
    if not isinstance(tool, dict):
        raise NodePhellError(f"invalid [tool] table in {path}")
    uv = tool.get("uv")
    if uv is None:
        return (), ()
    if not isinstance(uv, dict):
        raise NodePhellError(f"invalid [tool.uv] table in {path}")

    indexes_value = uv.get("index", ())
    if not isinstance(indexes_value, (list, tuple)):
        raise NodePhellError(f"invalid [[tool.uv.index]] entries in {path}")
    indexes: list[PackageIndex] = []
    index_names: set[str] = set()
    for value in indexes_value:
        if not isinstance(value, dict):
            raise NodePhellError(f"invalid [[tool.uv.index]] entry in {path}")
        unsupported = set(value) - {"name", "url", "explicit", "default"}
        if unsupported:
            field = sorted(unsupported)[0]
            raise NodePhellError(
                f"unsupported uv index field {field!r} in {path}"
            )
        name = value.get("name")
        url = value.get("url")
        explicit = value.get("explicit", False)
        default = value.get("default", False)
        if (
            not isinstance(name, str)
            or _PACKAGE_NAME.fullmatch(name) is None
            or not isinstance(url, str)
            or not isinstance(explicit, bool)
            or not isinstance(default, bool)
            or (explicit and default)
        ):
            raise NodePhellError(f"invalid uv index in {path}")
        if default:
            raise NodePhellError(
                f"uv default indexes are not supported in {path}"
            )
        normalized = normalize_name(name)
        if normalized in index_names:
            raise NodePhellError(f"duplicate uv index name {name!r} in {path}")
        index_names.add(normalized)
        _validate_package_index_url(url, path)
        indexes.append(PackageIndex(normalized, url.rstrip("/"), explicit))

    sources_value = uv.get("sources", {})
    if not isinstance(sources_value, dict):
        raise NodePhellError(f"invalid [tool.uv.sources] table in {path}")
    sources: list[PackageSource] = []
    for package_name, raw_entries in sources_value.items():
        if (
            not isinstance(package_name, str)
            or _PACKAGE_NAME.fullmatch(package_name) is None
        ):
            raise NodePhellError(f"invalid uv source package name in {path}")
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        if not entries:
            raise NodePhellError(
                f"empty uv source list for {package_name!r} in {path}"
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise NodePhellError(
                    f"invalid uv source for {package_name!r} in {path}"
                )
            unsupported = set(entry) - {"index", "path", "marker", "editable"}
            if unsupported:
                field = sorted(unsupported)[0]
                raise NodePhellError(
                    f"unsupported uv source field {field!r} for "
                    f"{package_name!r} in {path}"
                )
            index = entry.get("index")
            source_path = entry.get("path")
            marker = entry.get("marker")
            editable = entry.get("editable", True)
            if marker is not None and (
                not isinstance(marker, str) or not marker.strip()
            ):
                raise NodePhellError(
                    f"invalid uv source marker for {package_name!r} in {path}"
                )
            if not isinstance(editable, bool):
                raise NodePhellError(
                    f"invalid uv editable setting for {package_name!r} in {path}"
                )
            if (index is None) == (source_path is None):
                raise NodePhellError(
                    f"uv source for {package_name!r} must name exactly one "
                    f"index or path in {path}"
                )
            normalized_index = None
            relative_path = None
            if index is not None:
                if not isinstance(index, str):
                    raise NodePhellError(
                        f"invalid uv index source for {package_name!r} in {path}"
                    )
                normalized_index = normalize_name(index)
                if normalized_index not in index_names:
                    raise NodePhellError(
                        f"uv source for {package_name!r} references missing "
                        f"index {index!r} in {path}"
                    )
                if "editable" in entry:
                    raise NodePhellError(
                        f"uv index source for {package_name!r} cannot be "
                        f"editable in {path}"
                    )
            else:
                relative_path = _project_relative_path(
                    source_path,
                    f"uv source path for {package_name!r}",
                    path,
                )
                try:
                    local_root = (root / relative_path).resolve(strict=True)
                    relative_path = local_root.relative_to(
                        root.resolve(strict=True)
                    )
                except (OSError, ValueError) as error:
                    raise NodePhellError(
                        f"uv source path for {package_name!r} must remain "
                        f"inside the project: {source_path!r}"
                    ) from error
                if (
                    not local_root.is_dir()
                    or not (local_root / "pyproject.toml").is_file()
                ):
                    raise NodePhellError(
                        f"uv source path for {package_name!r} has no "
                        f"pyproject.toml: {local_root}"
                    )
                if not editable:
                    raise NodePhellError(
                        f"non-editable uv path source for {package_name!r} is "
                        f"not supported in {path}"
                    )
            sources.append(
                PackageSource(
                    normalize_name(package_name),
                    normalized_index,
                    relative_path,
                    marker.strip() if isinstance(marker, str) else None,
                )
            )
    return tuple(indexes), tuple(sources)


def _validate_package_index_url(value: str, path: Path) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in value)
    ):
        raise NodePhellError(f"invalid HTTPS package index URL in {path}: {value!r}")


def _project_dynamic_fields(project: dict, path: Path) -> frozenset[str]:
    value = project.get("dynamic")
    if value is None:
        return frozenset()
    if not isinstance(value, list) or not all(
        isinstance(field, str) and field.strip() for field in value
    ):
        raise NodePhellError(f"invalid project dynamic fields in {path}")
    fields = frozenset(value)
    if len(fields) != len(value):
        raise NodePhellError(f"duplicate project dynamic field in {path}")
    conflict = next((field for field in fields if field in project), None)
    if conflict is not None:
        raise NodePhellError(
            f"project field {conflict!r} is both static and dynamic in {path}"
        )
    unsupported = next(
        (
            field
            for field in ("name", "requires-python", "optional-dependencies")
            if field in fields
        ),
        None,
    )
    if unsupported is not None:
        raise NodePhellError(
            f"dynamic project field {unsupported!r} is not supported; "
            f"declare it statically in {path} so NodePhell can inspect it"
        )
    return fields


def _validate_dynamic_dependencies(
    dynamic: bool,
    project_name: str | None,
    has_build_system: bool,
    path: Path,
) -> None:
    if not dynamic:
        return
    if project_name is None or not has_build_system:
        raise NodePhellError(
            f"dynamic project dependencies in {path} require a project name "
            "and [build-system] so the declared backend can provide metadata"
        )


def _project_name(data: dict, path: Path) -> str | None:
    name = data.get("name")
    if name is None:
        return None
    if not isinstance(name, str) or not name.strip():
        raise NodePhellError(f"invalid project name in {path}")
    return name


def _optional_dependencies(
    project: dict,
    path: Path,
) -> tuple[DependencyOption, ...]:
    value = project.get("optional-dependencies")
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise NodePhellError(f"invalid [project.optional-dependencies] in {path}")
    options: list[DependencyOption] = []
    seen: dict[str, str] = {}
    for name, entries in value.items():
        if not isinstance(name, str) or _PACKAGE_NAME.fullmatch(name) is None:
            raise NodePhellError(f"invalid optional dependency name in {path}")
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None:
            raise NodePhellError(
                f"optional dependency names {previous!r} and {name!r} "
                f"normalize to the same name in {path}"
            )
        seen[normalized] = name
        requirements = _option_requirements(entries, normalized, path)
        options.append(DependencyOption(normalized, requirements))
    return tuple(sorted(options, key=lambda option: option.name))


def _dependency_groups(data: dict, path: Path) -> tuple[DependencyOption, ...]:
    groups: dict[str, DependencyOption] = {}
    for option in (
        *_standard_dependency_groups(data, path),
        *_poetry_dependency_groups(data, path),
    ):
        previous = groups.get(option.name)
        if previous is None:
            groups[option.name] = option
            continue
        groups[option.name] = DependencyOption(
            option.name,
            tuple(dict.fromkeys(previous.requirements + option.requirements)),
            tuple(dict.fromkeys(previous.includes + option.includes)),
        )
    names = set(groups)
    for option in groups.values():
        missing = next((name for name in option.includes if name not in names), None)
        if missing is not None:
            raise NodePhellError(
                f"dependency group {option.name!r} includes missing group "
                f"{missing!r} in {path}"
            )
    return tuple(groups[name] for name in sorted(groups))


def _standard_dependency_groups(
    data: dict,
    path: Path,
) -> tuple[DependencyOption, ...]:
    value = data.get("dependency-groups")
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise NodePhellError(f"invalid [dependency-groups] in {path}")
    options: list[DependencyOption] = []
    seen: dict[str, str] = {}
    for name, entries in value.items():
        if (
            not isinstance(name, str)
            or _PACKAGE_NAME.fullmatch(name) is None
            or not isinstance(entries, list)
        ):
            raise NodePhellError(f"invalid dependency group in {path}")
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None:
            raise NodePhellError(
                f"dependency group names {previous!r} and {name!r} normalize "
                f"to the same name in {path}"
            )
        seen[normalized] = name
        requirements: list[str] = []
        includes: list[str] = []
        for entry in entries:
            if isinstance(entry, str) and entry.strip():
                requirements.append(entry)
            elif (
                isinstance(entry, dict)
                and set(entry) == {"include-group"}
                and isinstance(entry["include-group"], str)
                and entry["include-group"].strip()
            ):
                includes.append(normalize_name(entry["include-group"]))
            else:
                raise NodePhellError(
                    f"invalid entry in dependency group {name!r} in {path}"
                )
        options.append(
            DependencyOption(normalized, tuple(requirements), tuple(includes))
        )
    return tuple(sorted(options, key=lambda option: option.name))


def _poetry_dependency_groups(
    data: dict,
    path: Path,
) -> tuple[DependencyOption, ...]:
    tool = data.get("tool")
    if tool is None:
        return ()
    if not isinstance(tool, dict):
        raise NodePhellError(f"invalid [tool] table in {path}")
    poetry = tool.get("poetry")
    if poetry is None:
        return ()
    if not isinstance(poetry, dict):
        raise NodePhellError(f"invalid [tool.poetry] table in {path}")

    options: list[DependencyOption] = []
    seen: dict[str, str] = {}
    legacy = poetry.get("dev-dependencies")
    if legacy is not None:
        options.append(
            DependencyOption(
                "dev",
                _poetry_group_requirements(legacy, "dev", path),
            )
        )

    groups = poetry.get("group")
    if groups is None:
        return tuple(options)
    if not isinstance(groups, dict):
        raise NodePhellError(f"invalid [tool.poetry.group] table in {path}")
    for name, definition in groups.items():
        if (
            not isinstance(name, str)
            or _PACKAGE_NAME.fullmatch(name) is None
            or not isinstance(definition, dict)
        ):
            raise NodePhellError(f"invalid Poetry dependency group in {path}")
        normalized = normalize_name(name)
        previous = seen.get(normalized)
        if previous is not None:
            raise NodePhellError(
                f"Poetry group names {previous!r} and {name!r} normalize to "
                f"the same name in {path}"
            )
        seen[normalized] = name
        unsupported = set(definition) - {
            "dependencies",
            "include-groups",
            "optional",
        }
        if unsupported:
            field = sorted(unsupported)[0]
            raise NodePhellError(
                f"unsupported Poetry group field {field!r} for "
                f"{name!r} in {path}"
            )
        optional = definition.get("optional", False)
        includes = definition.get("include-groups", [])
        if not isinstance(optional, bool):
            raise NodePhellError(
                f"invalid optional setting for Poetry group {name!r} in {path}"
            )
        if not isinstance(includes, list) or not all(
            isinstance(included, str)
            and _PACKAGE_NAME.fullmatch(included) is not None
            for included in includes
        ):
            raise NodePhellError(
                f"invalid include-groups for Poetry group {name!r} in {path}"
            )
        dependencies = definition.get("dependencies", {})
        options.append(
            DependencyOption(
                normalized,
                _poetry_group_requirements(dependencies, name, path),
                tuple(normalize_name(included) for included in includes),
            )
        )
    return tuple(options)


def _poetry_group_requirements(
    dependencies: object,
    group: str,
    path: Path,
) -> tuple[str, ...]:
    if not isinstance(dependencies, dict):
        raise NodePhellError(
            f"invalid dependencies for Poetry group {group!r} in {path}"
        )
    result: list[str] = []
    seen: set[str] = set()
    for name, value in dependencies.items():
        if not isinstance(name, str):
            raise NodePhellError(
                f"invalid dependency name in Poetry group {group!r} in {path}"
            )
        constraint, extras, optional = _poetry_dependency(name, value, path)
        if optional:
            raise NodePhellError(
                f"optional dependency {name!r} is invalid inside Poetry "
                f"group {group!r} in {path}"
            )
        requirement_name = name
        if extras:
            requirement_name += f"[{','.join(extras)}]"
        requirement = parse_package_requirement(
            requirement_name + constraint,
            path,
        )
        normalized = normalize_name(requirement.name)
        if normalized in seen:
            raise NodePhellError(
                f"duplicate dependency {requirement.name!r} in Poetry "
                f"group {group!r} in {path}"
            )
        seen.add(normalized)
        result.append(requirement.text)
    return tuple(result)


def _option_requirements(
    value: object,
    name: object,
    path: Path,
) -> tuple[str, ...]:
    if (
        not isinstance(name, str)
        or _PACKAGE_NAME.fullmatch(name) is None
        or not isinstance(value, list)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise NodePhellError(f"invalid optional dependency {name!r} in {path}")
    return tuple(value)


def _has_build_system(data: dict, path: Path) -> bool:
    build_system = data.get("build-system")
    if build_system is None:
        return False
    if not isinstance(build_system, dict):
        raise NodePhellError(f"invalid [build-system] table in {path}")
    return True


def _application_declaration(
    data: dict,
    path: Path,
) -> ApplicationDeclaration | None:
    value = _nodephell_table(data, path).get("application")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NodePhellError(
            f"invalid [tool.nodephell.application] table in {path}"
        )
    adapter = _project_relative_path(value.get("adapter"), "adapter", path)
    executable_value = value.get("executable")
    executable = (
        _project_relative_path(executable_value, "executable", path)
        if executable_value is not None
        else None
    )
    name = value.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise NodePhellError(
            f"invalid application name in {path}"
        )
    return ApplicationDeclaration(adapter, executable, name)


def _project_relative_path(value: object, field: str, path: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise NodePhellError(f"invalid {field} path in {path}")
    result = Path(value)
    if result.is_absolute() or ".." in result.parts:
        raise NodePhellError(
            f"{field} must be a project-relative path in {path}"
        )
    return result


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
        unsupported_source = next(
            (key for key in ("vcs", "directory", "archive") if key in package),
            None,
        )
        if unsupported_source is not None:
            raise NodePhellError(
                f"NodePhell does not yet support {unsupported_source} package "
                f"sources from {path}"
            )
        if package.get("marker"):
            raise NodePhellError(
                f"NodePhell does not yet support package markers in {path}"
            )
        if package.get("requires-python"):
            raise NodePhellError(
                f"NodePhell does not yet support per-package requires-python "
                f"in {path}"
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
            artifacts = _locked_artifacts(package, path)
            if path.name == STANDARD_LOCK_FILENAME and len(artifacts) != 1:
                raise NodePhellError(
                    f"NodePhell currently requires exactly one wheel or sdist "
                    f"for {name}=={version} in standard {path.name}"
                )
            result.append(PackagePin(name, version, artifacts))
    return tuple(result)


def _validate_lock_document(data: dict, path: Path) -> None:
    if path.name != STANDARD_LOCK_FILENAME or _lock_has_nodephell_install_data(
        data, path
    ):
        return
    nodephell = _nodephell_table(data, path)
    legacy_nodephell = data.get("created-by") == "NodePhell with stock pip" or (
        "source" in nodephell or "selection" in nodephell
    )
    if legacy_nodephell and (
        data.get("created-by") != "nodephell" or "packages" not in data
    ):
        return
    if not isinstance(data.get("created-by"), str):
        raise NodePhellError(f"standard {path.name} has no valid created-by value")
    if not isinstance(data.get("packages"), list):
        raise NodePhellError(f"standard {path.name} has no packages array")
    environments = data.get("environments")
    if environments:
        raise NodePhellError(
            f"NodePhell does not yet support multi-environment standard locks: "
            f"{path}"
        )


def _lock_has_nodephell_install_data(data: dict, path: Path) -> bool:
    nodephell = _nodephell_table(data, path)
    return "runtime" in nodephell or "host" in nodephell


def _locked_runtime(data: dict, path: Path) -> RuntimeArtifact | None:
    nodephell = _nodephell_table(data, path)
    runtime = nodephell.get("runtime")
    if runtime is None:
        return None
    return runtime_artifact_from_mapping(runtime, path)


def _locked_source_fingerprint(data: dict, path: Path) -> str | None:
    source = _nodephell_table(data, path).get("source")
    if source is None:
        return None
    if not isinstance(source, dict):
        raise NodePhellError(f"invalid project source identity in {path}")
    fingerprint = source.get("fingerprint")
    if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
        raise NodePhellError(f"invalid project source identity in {path}")
    return fingerprint


def _locked_source_settings(
    data: dict,
    root: Path,
    path: Path,
) -> tuple[tuple[Path, ...], bool, tuple[Path, ...]]:
    source = _nodephell_table(data, path).get("source")
    if source is None:
        return (), False, ()
    if not isinstance(source, dict):
        raise NodePhellError(f"invalid project source identity in {path}")
    requirements = source.get("requirements", [])
    replace_requirements = source.get("replace-dependencies", False)
    local_projects = source.get("local-projects", [])
    if (
        not isinstance(requirements, list)
        or not all(isinstance(item, str) and item.strip() for item in requirements)
        or not isinstance(replace_requirements, bool)
        or not isinstance(local_projects, list)
        or not all(isinstance(item, str) and item.strip() for item in local_projects)
    ):
        raise NodePhellError(f"invalid project source settings in {path}")
    requirement_files = normalize_requirement_files(
        root,
        tuple(Path(item) for item in requirements),
    )
    selected_projects: list[Path] = []
    seen: set[Path] = set()
    for item in local_projects:
        relative = _project_relative_path(
            item,
            "locked local project",
            path,
        )
        try:
            local_root = (root / relative).resolve(strict=True)
            relative = local_root.relative_to(root.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise NodePhellError(
                f"locked local project must remain inside the project: {item}"
            ) from error
        if (
            not local_root.is_dir()
            or not (local_root / "pyproject.toml").is_file()
        ):
            raise NodePhellError(
                f"locked local project has no pyproject.toml: {local_root}"
            )
        if relative not in seen:
            seen.add(relative)
            selected_projects.append(relative)
    return requirement_files, replace_requirements, tuple(selected_projects)


def _locked_selection(
    data: dict,
    path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selection = _nodephell_table(data, path).get("selection")
    if selection is None:
        return (), ()
    if not isinstance(selection, dict) or set(selection) != {"extras", "groups"}:
        raise NodePhellError(f"invalid project option selection in {path}")
    extras = selection.get("extras")
    groups = selection.get("groups")
    if (
        not isinstance(extras, list)
        or not isinstance(groups, list)
        or not all(isinstance(name, str) and name.strip() for name in extras)
        or not all(isinstance(name, str) and name.strip() for name in groups)
        or len(set(extras)) != len(extras)
        or len(set(groups)) != len(groups)
    ):
        raise NodePhellError(f"invalid project option selection in {path}")
    normalized_extras = tuple(sorted(normalize_name(name) for name in extras))
    normalized_groups = tuple(sorted(normalize_name(name) for name in groups))
    if len(set(normalized_extras)) != len(normalized_extras) or len(
        set(normalized_groups)
    ) != len(normalized_groups):
        raise NodePhellError(f"duplicate normalized project option in {path}")
    return normalized_extras, normalized_groups


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


def _locked_host_artifact(data: dict, path: Path) -> HostArtifact | None:
    host = _nodephell_table(data, path).get("host")
    if not isinstance(host, dict):
        return None
    artifact_keys = {"version", "platform", "name", "url", "hashes"}
    if not artifact_keys.intersection(host):
        return None
    return host_artifact_from_mapping(host, path)


def host_artifact_from_mapping(
    host: object,
    path: Path,
) -> HostArtifact:
    if not isinstance(host, dict):
        raise NodePhellError(f"invalid embedded host artifact in {path}")
    required = ("kind", "version", "platform", "name", "url")
    if not all(isinstance(host.get(key), str) for key in required):
        raise NodePhellError(f"incomplete embedded host artifact in {path}")
    hashes = _hash_table(host.get("hashes"), path)
    try:
        return HostArtifact(
            host["kind"].lower(),
            host["version"],
            host["platform"],
            host["name"],
            host["url"],
            hashes,
        )
    except NodePhellError as error:
        raise NodePhellError(
            f"invalid embedded host artifact in {path}: {error}"
        ) from error


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


def _locked_artifacts(
    package: dict,
    path: Path,
) -> tuple[PackageArtifact, ...]:
    result: list[PackageArtifact] = []
    wheels = package.get("wheels", ())
    if wheels is None:
        wheels = ()
    if not isinstance(wheels, (list, tuple)):
        raise NodePhellError(f"invalid wheel entries in {path}")
    for wheel in wheels:
        if not isinstance(wheel, dict):
            raise NodePhellError(f"invalid wheel entry in {path}")
        result.append(_package_artifact("wheel", wheel, path))
    sdist = package.get("sdist")
    if sdist is not None:
        if not isinstance(sdist, dict):
            raise NodePhellError(f"invalid sdist entry in {path}")
        result.append(_package_artifact("sdist", sdist, path))
    return tuple(result)


def _package_artifact(
    kind: str,
    value: dict,
    path: Path,
) -> PackageArtifact:
    url = value.get("url")
    name = value.get("name")
    if name is None and isinstance(url, str):
        name = Path(unquote(urlsplit(url).path)).name
    if not isinstance(name, str) or not isinstance(url, str):
        raise NodePhellError(f"incomplete package artifact in {path}")
    try:
        return PackageArtifact(
            kind,
            name,
            url,
            _hash_table(value.get("hashes"), path),
        )
    except NodePhellError as error:
        raise NodePhellError(
            f"invalid package artifact in {path}: {error}"
        ) from error


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


def _project_requirements(
    dependencies: object,
    path: Path,
) -> tuple[PackageRequirement, ...]:
    if not isinstance(dependencies, (list, tuple)):
        raise NodePhellError(f"invalid project dependencies in {path}")
    result: list[PackageRequirement] = []
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise NodePhellError(f"invalid dependency in {path}")
        requirement = parse_package_requirement(dependency, path)
        result.append(requirement)
    return tuple(result)


def _poetry_requirements(
    data: dict,
    path: Path,
) -> tuple[str | None, tuple[PackageRequirement, ...]] | None:
    tool = data.get("tool")
    if tool is None:
        return None
    if not isinstance(tool, dict):
        raise NodePhellError(f"invalid [tool] table in {path}")
    poetry = tool.get("poetry")
    if poetry is None:
        return None
    if not isinstance(poetry, dict):
        raise NodePhellError(f"invalid [tool.poetry] table in {path}")
    dependencies = poetry.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise NodePhellError(
            f"invalid [tool.poetry.dependencies] table in {path}"
        )

    requires_python = None
    result: list[PackageRequirement] = []
    seen: set[str] = set()
    for name, value in dependencies.items():
        if not isinstance(name, str):
            raise NodePhellError(f"invalid Poetry dependency name in {path}")
        if normalize_name(name) == "python":
            constraint, extras, optional = _poetry_dependency(
                name, value, path
            )
            if extras or optional:
                raise NodePhellError(
                    f"invalid Poetry Python requirement in {path}"
                )
            requires_python = constraint or None
            continue

        constraint, extras, optional = _poetry_dependency(name, value, path)
        if optional:
            continue
        requirement_name = name
        if extras:
            requirement_name += f"[{','.join(extras)}]"
        requirement = parse_package_requirement(
            requirement_name + constraint,
            path,
        )
        normalized = normalize_name(requirement.name)
        if normalized in seen:
            raise NodePhellError(
                f"duplicate Poetry requirement for {requirement.name} in {path}"
            )
        seen.add(normalized)
        result.append(requirement)
    return requires_python, tuple(result)


def _poetry_dependency(
    name: str,
    value: object,
    path: Path,
) -> tuple[str, tuple[str, ...], bool]:
    if isinstance(value, str):
        return _poetry_constraint(value, name, path), (), False
    if not isinstance(value, dict):
        raise NodePhellError(
            f"unsupported Poetry dependency for {name!r} in {path}"
        )
    unsupported = {
        key
        for key in value
        if key not in {"version", "extras", "optional", "allow-prereleases"}
    }
    if unsupported:
        feature = sorted(unsupported)[0]
        raise NodePhellError(
            f"unsupported Poetry dependency field {feature!r} for "
            f"{name!r} in {path}"
        )
    version = value.get("version", "*")
    extras = value.get("extras", ())
    optional = value.get("optional", False)
    prereleases = value.get("allow-prereleases", False)
    if not isinstance(version, str):
        raise NodePhellError(
            f"invalid Poetry version for {name!r} in {path}"
        )
    if not isinstance(extras, (list, tuple)) or not all(
        isinstance(extra, str) and extra for extra in extras
    ):
        raise NodePhellError(
            f"invalid Poetry extras for {name!r} in {path}"
        )
    if not isinstance(optional, bool) or not isinstance(prereleases, bool):
        raise NodePhellError(
            f"invalid Poetry dependency options for {name!r} in {path}"
        )
    if prereleases:
        raise NodePhellError(
            f"Poetry prerelease opt-in is not supported for {name!r} in {path}"
        )
    return (
        _poetry_constraint(version, name, path),
        tuple(extras),
        optional,
    )


def _poetry_constraint(value: str, name: str, path: Path) -> str:
    constraint = value.strip()
    if constraint in {"", "*"}:
        return ""
    if "||" in constraint or " " in constraint:
        raise NodePhellError(
            f"unsupported Poetry version constraint {value!r} for "
            f"{name!r} in {path}"
        )
    if constraint.startswith("^"):
        lower = constraint[1:]
        parts = _poetry_release_parts(lower, name, path)
        first_nonzero = next(
            (index for index, part in enumerate(parts) if part != 0),
            len(parts) - 1,
        )
        upper = list(parts)
        upper[first_nonzero] += 1
        upper[first_nonzero + 1 :] = [0] * (len(parts) - first_nonzero - 1)
        return f">={lower},<{'.'.join(str(part) for part in upper)}"
    if constraint.startswith("~") and not constraint.startswith("~="):
        lower = constraint[1:]
        parts = _poetry_release_parts(lower, name, path)
        upper_index = 0 if len(parts) == 1 else 1
        upper = list(parts)
        upper[upper_index] += 1
        upper[upper_index + 1 :] = [0] * (len(parts) - upper_index - 1)
        return f">={lower},<{'.'.join(str(part) for part in upper)}"
    wildcard = _POETRY_WILDCARD.fullmatch(constraint)
    if wildcard is not None:
        lower = wildcard.group(1)
        parts = _poetry_release_parts(lower, name, path)
        upper = list(parts)
        upper[-1] += 1
        return f">={lower},<{'.'.join(str(part) for part in upper)}"
    if _POETRY_RELEASE.fullmatch(constraint):
        return f"=={constraint}"
    try:
        parse_package_requirement(f"placeholder{constraint}", path)
    except NodePhellError as error:
        raise NodePhellError(
            f"unsupported Poetry version constraint {value!r} for "
            f"{name!r} in {path}"
        ) from error
    return constraint


def _poetry_release_parts(
    value: str,
    name: str,
    path: Path,
) -> tuple[int, ...]:
    if _POETRY_RELEASE.fullmatch(value) is None:
        raise NodePhellError(
            f"unsupported Poetry version constraint {value!r} for "
            f"{name!r} in {path}"
        )
    return tuple(int(part) for part in value.split("."))


def _validate_requires_python(value: object, path: Path) -> None:
    if value is not None and not isinstance(value, str):
        raise NodePhellError(f"invalid requires-python value in {path}")
