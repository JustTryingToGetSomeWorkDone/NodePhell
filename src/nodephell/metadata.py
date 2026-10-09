# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
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

    @property
    def text(self) -> str:
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        specifiers = ",".join(
            f"{operator}{version}" for operator, version in self.specifiers
        )
        return f"{self.name}{extras}{specifiers}"

    @property
    def fingerprint_text(self) -> str:
        extras = tuple(sorted(extra.lower() for extra in self.extras))
        normalized = PackageRequirement(
            normalize_name(self.name),
            extras,
            self.specifiers,
        )
        return normalized.text


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

    @property
    def runtime_requirement(self) -> str | None:
        if self.runtime_artifact is not None:
            return f"=={self.runtime_artifact.version}"
        return self.requires_python


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_package_requirement(
    value: str,
    path: Path | None = None,
) -> PackageRequirement:
    match = _REQUIREMENT.fullmatch(value)
    location = f" in {path}" if path is not None else ""
    if match is None:
        raise NodePhellError(f"unsupported package requirement {value!r}{location}")
    name, extras_text, specifier_text = match.groups()
    extras = (
        tuple(part.strip() for part in extras_text.split(","))
        if extras_text
        else ()
    )
    specifiers: list[tuple[str, str]] = []
    if specifier_text:
        for clause in specifier_text.split(","):
            clause_match = _REQUIREMENT_CLAUSE.fullmatch(clause.strip())
            if clause_match is None:
                raise NodePhellError(
                    f"unsupported package requirement {value!r}{location}"
                )
            specifiers.append(clause_match.groups())
    return PackageRequirement(name, extras, tuple(specifiers))


def project_definition_fingerprint(project: Project) -> str:
    host = None
    if project.host is not None:
        host = {
            "kind": project.host.kind,
            "requires": project.host.requires,
        }
    data = {
        "requires-python": project.requires_python,
        "dependencies": sorted(
            requirement.fingerprint_text for requirement in project.requirements
        ),
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
    lock_path = root / "pylock.toml"
    if not project_path.is_file() or not lock_path.is_file():
        return False
    locked = load_project(root)
    if locked.source_fingerprint is None:
        return False
    definition = replace(
        load_project_definition(root),
        selected_extras=locked.selected_extras,
        selected_groups=locked.selected_groups,
    )
    return locked.source_fingerprint == project_definition_fingerprint(definition)


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
    application = _application_declaration(project_data, project_path)
    optional_dependencies = _optional_dependencies(project_table, project_path)
    dependency_groups = _dependency_groups(project_data, project_path)
    project_name = _project_name(project_table, project_path)

    if lock_path.is_file():
        lock_data = _read_toml(lock_path)
        if lock_data.get("lock-version") != "1.0":
            raise NodePhellError(
                f"unsupported lock version in {lock_path}; expected 1.0"
            )
        packages = _locked_packages(lock_data, lock_path)
        selected_extras, selected_groups = _locked_selection(lock_data, lock_path)
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
            has_build_system=_has_build_system(project_data, project_path),
            name=project_name,
            optional_dependencies=optional_dependencies,
            dependency_groups=dependency_groups,
            selected_extras=selected_extras,
            selected_groups=selected_groups,
        )

    return load_project_definition(root)


def load_project_definition(root: Path) -> Project:
    project_path = root / "pyproject.toml"
    if not project_path.is_file():
        raise NodePhellError(f"no pyproject.toml found in {root}")
    project_data = _read_toml(project_path)
    if "project" in project_data:
        project_table = project_data["project"]
        if not isinstance(project_table, dict):
            raise NodePhellError(f"invalid [project] table in {project_path}")
        requirements = _project_requirements(
            project_table.get("dependencies", ()), project_path
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
    return Project(
        root,
        project_path,
        requires_python,
        (),
        host=_host_requirement(project_data, project_path),
        requirements=requirements,
        application=_application_declaration(project_data, project_path),
        has_build_system=_has_build_system(project_data, project_path),
        name=_project_name(project_table, project_path),
        optional_dependencies=_optional_dependencies(project_table, project_path),
        dependency_groups=_dependency_groups(project_data, project_path),
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
    for name, entries in value.items():
        requirements = _option_requirements(entries, name, path)
        options.append(DependencyOption(name, requirements))
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
    for name, entries in value.items():
        if (
            not isinstance(name, str)
            or _PACKAGE_NAME.fullmatch(name) is None
            or not isinstance(entries, list)
        ):
            raise NodePhellError(f"invalid dependency group in {path}")
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
                includes.append(entry["include-group"])
            else:
                raise NodePhellError(
                    f"invalid entry in dependency group {name!r} in {path}"
                )
        options.append(
            DependencyOption(name, tuple(requirements), tuple(includes))
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
                name,
                _poetry_group_requirements(dependencies, name, path),
                tuple(includes),
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
        raise NodePhellError(
            f"invalid application {field} path in {path}"
        )
    result = Path(value)
    if result.is_absolute() or ".." in result.parts:
        raise NodePhellError(
            f"application {field} must be a project-relative path in {path}"
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
            artifacts = _locked_artifacts(package, path)
            result.append(PackagePin(name, version, artifacts))
    return tuple(result)


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
    return tuple(sorted(extras)), tuple(sorted(groups))


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
    name = value.get("name")
    url = value.get("url")
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
    seen: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise NodePhellError(f"invalid dependency in {path}")
        requirement = parse_package_requirement(dependency, path)
        normalized = normalize_name(requirement.name)
        if normalized in seen:
            raise NodePhellError(
                f"duplicate requirement for {requirement.name} in {path}"
            )
        seen.add(normalized)
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
