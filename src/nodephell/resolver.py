# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

from .activity import working
from .errors import NodePhellError
from .metadata import (
    HostArtifact,
    PackageArtifact,
    PackagePin,
    Project,
    normalize_name,
    project_definition_fingerprint,
)
from .runtime import (
    Runtime,
    native_build_failure_guidance,
    runtime_build_environment,
)


@dataclass(frozen=True)
class ResolvedPackage:
    pin: PackagePin
    filename: str
    url: str
    hashes: tuple[tuple[str, str], ...]


_SOURCE_SECTION = re.compile(
    r"(?ms)^\[tool\.nodephell\.source\]\n.*?(?=^\[|\Z)"
)
_SELECTION_SECTION = re.compile(
    r"(?ms)^\[tool\.nodephell\.selection\]\n.*?(?=^\[|\Z)"
)


def resolve_and_write_lock(
    project: Project,
    runtime: Runtime,
    host_artifact: HostArtifact | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    if project.metadata_file.name != "pyproject.toml":
        return project.metadata_file
    packages = _resolve(project, runtime, progress)
    return _write_lock(project, packages, runtime, host_artifact)


def _resolve(
    project: Project,
    runtime: Runtime,
    progress: Callable[[str], None] | None = None,
) -> tuple[ResolvedPackage, ...]:
    _validate_selected_options(project)
    root_request = None
    if project.selected_extras:
        if not project.has_build_system or project.name is None:
            raise NodePhellError(
                "project extras require a named project with [build-system]"
            )
        root_request = f".[{','.join(project.selected_extras)}]"
        requirements = [root_request]
    elif project.dynamic_dependencies:
        if not project.has_build_system or project.name is None:
            raise NodePhellError(
                "dynamic project dependencies require a named project with "
                "[build-system]"
            )
        root_request = "."
        requirements = [root_request]
    else:
        requirements = [requirement.text for requirement in project.requirements]
    requirements.extend(_selected_group_requirements(project))
    if not requirements:
        requirements = [
            f"{package.name}=={package.version}" for package in project.packages
        ]
    if not requirements:
        return ()
    environment = runtime_build_environment(runtime)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)

    with tempfile.TemporaryDirectory(prefix="nodephell-resolve-") as temporary:
        report = Path(temporary) / "report.json"
        target = Path(temporary) / "target"
        command = [
            str(runtime.executable),
            "-I",
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--target",
            str(target),
            "--disable-pip-version-check",
            "--no-input",
            "--report",
            str(report),
            *requirements,
        ]
        with working(
            progress,
            "Resolving the complete dependency closure with stock pip",
        ):
            try:
                result = subprocess.run(
                    command,
                    cwd=project.root,
                    env=environment,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            except OSError as error:
                raise NodePhellError(
                    f"cannot run pip resolver with {runtime.executable}: {error}"
                ) from error
        if result.returncode != 0:
            message = (
                f"stock pip could not resolve the project "
                f"(exit status {result.returncode})"
            )
            details = (result.stdout or "").strip()
            guidance = None
            if details:
                guidance = (
                    native_build_failure_guidance(details)
                    or _external_requirement_guidance(details)
                )
                message += f":\n{_bounded_pip_output(details)}"
            raise NodePhellError(message, guidance=guidance)
        try:
            with report.open(encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise NodePhellError(
                f"cannot read pip resolution report: {error}"
            ) from error
    packages = _parse_report(
        data,
        project.root if root_request is not None else None,
        project.name if root_request is not None else None,
    )
    resolved = {
        normalize_name(package.pin.name): package.pin.version
        for package in packages
    }
    for requirement in project.requirements:
        if (
            requirement.marker is None
            and normalize_name(requirement.name) not in resolved
        ):
            raise NodePhellError(
                f"pip report omitted the requested release "
                f"{requirement.text}"
            )
    return packages


def rewrite_lock_selection(project: Project) -> Path:
    """Update only option identity in an otherwise unchanged generated lock."""
    path = project.root / "pylock.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise NodePhellError(f"cannot read {path}: {error}") from error
    source = (
        "[tool.nodephell.source]\n"
        f"fingerprint = {_toml_string(project_definition_fingerprint(project))}\n\n"
    )
    text, source_count = _SOURCE_SECTION.subn(source, text, count=1)
    if source_count != 1:
        raise NodePhellError(
            f"cannot update options in non-generated project lock: {path}"
        )
    text, selection_count = _SELECTION_SECTION.subn("", text, count=1)
    if selection_count > 1:
        raise NodePhellError(f"invalid project option selection in {path}")
    if project.selected_extras or project.selected_groups:
        selection = (
            "[tool.nodephell.selection]\n"
            f"extras = {_toml_array(project.selected_extras)}\n"
            f"groups = {_toml_array(project.selected_groups)}\n\n"
        )
        source_end = text.index(source) + len(source)
        text = text[:source_end] + selection + text[source_end:]
    _write_lock_text(path, text)
    return path


def _bounded_pip_output(value: str, limit: int = 4000) -> str:
    routine_prefixes = (
        "Collecting ",
        "Downloading ",
        "Using cached ",
        "Requirement already satisfied:",
        "Installing build dependencies:",
    )
    useful = [
        line
        for line in value.splitlines()
        if not line.strip().startswith(routine_prefixes)
    ]
    result = "\n".join(useful).strip()
    if len(result) <= limit:
        return result
    return "...\n" + result[-limit:]


def _external_requirement_guidance(value: str) -> str | None:
    match = re.search(
        r"Error:\s+(?P<package>[A-Za-z0-9_.-]+).*?"
        r"cannot be built without\s+(?P<program>[A-Za-z0-9_.+-]+)\s+"
        r"in (?:the )?PATH",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    package = match.group("package")
    program = match.group("program")
    return (
        f"The Python package {package} requires an external program named "
        f"{program!r}, but that command was not found. External programs are "
        "separate system software rather than Python packages, so NodePhell "
        "cannot determine or install the correct operating-system package. "
        "If you need this option, use your system software manager to find "
        f"and install a package providing {program!r}, then run "
        '"nodephell options" again. '
        f"Otherwise, deselect the option that adds {package}. If you are "
        f"unsure which package is adding {package}, attempt adding one "
        "package at a time."
    )


def _validate_selected_options(project: Project) -> None:
    extras = {option.name for option in project.optional_dependencies}
    groups = {option.name for option in project.dependency_groups}
    missing_extra = next(
        (name for name in project.selected_extras if name not in extras),
        None,
    )
    if missing_extra is not None:
        raise NodePhellError(f"project does not declare extra {missing_extra!r}")
    missing_group = next(
        (name for name in project.selected_groups if name not in groups),
        None,
    )
    if missing_group is not None:
        raise NodePhellError(
            f"project does not declare dependency group {missing_group!r}"
        )


def _selected_group_requirements(project: Project) -> list[str]:
    groups = {group.name: group for group in project.dependency_groups}
    requirements: list[str] = []
    visited: set[str] = set()
    active: set[str] = set()

    def include(name: str) -> None:
        if name in visited:
            return
        if name in active:
            raise NodePhellError(
                f"dependency groups contain an include cycle at {name!r}"
            )
        active.add(name)
        group = groups[name]
        requirements.extend(group.requirements)
        for included in group.includes:
            include(included)
        active.remove(name)
        visited.add(name)

    for name in project.selected_groups:
        include(name)
    return requirements


def _parse_report(
    data: object,
    source_root: Path | None = None,
    source_name: str | None = None,
) -> tuple[ResolvedPackage, ...]:
    if not isinstance(data, dict) or not isinstance(data.get("install"), list):
        raise NodePhellError("pip returned an invalid resolution report")
    packages: dict[str, ResolvedPackage] = {}
    found_source = False
    for entry in data["install"]:
        if not isinstance(entry, dict):
            raise NodePhellError("pip returned an invalid package report entry")
        metadata = entry.get("metadata")
        download = entry.get("download_info")
        if not isinstance(metadata, dict) or not isinstance(download, dict):
            raise NodePhellError("pip report omitted package metadata or artifact")
        name = metadata.get("name")
        version = metadata.get("version")
        url = download.get("url")
        if not all(isinstance(value, str) for value in (name, version, url)):
            raise NodePhellError("pip report contained an invalid package identity")
        if source_root is not None and source_name is not None and (
            _is_source_project(entry, url, name, source_root, source_name)
        ):
            found_source = True
            continue
        pin = PackagePin(name, version)
        parsed_url = urlsplit(url)
        if parsed_url.username is not None or parsed_url.password is not None:
            raise NodePhellError(
                f"refusing to write credential-bearing artifact URL for {name}"
            )
        artifact = Path(unquote(parsed_url.path)).name
        if not artifact:
            raise NodePhellError(f"pip report omitted the filename for {name}")
        hashes = _report_hashes(download.get("archive_info"))
        PackageArtifact(
            "wheel" if artifact.endswith(".whl") else "sdist",
            artifact,
            url,
            hashes,
        )
        package = ResolvedPackage(pin, artifact, url, hashes)
        normalized = normalize_name(name)
        previous = packages.get(normalized)
        if previous is not None and previous.pin.version != version:
            raise NodePhellError(f"pip resolved conflicting versions for {name}")
        packages[normalized] = package
    if source_root is not None and not found_source:
        raise NodePhellError("pip report omitted the selected source project")
    return tuple(packages[name] for name in sorted(packages))


def _is_source_project(
    entry: dict,
    url: str,
    name: str,
    source_root: Path,
    source_name: str,
) -> bool:
    if normalize_name(name) != normalize_name(source_name):
        return False
    parsed = urlsplit(url)
    if parsed.scheme == "file":
        try:
            if Path(unquote(parsed.path)).resolve() == source_root.resolve():
                return True
        except OSError:
            pass
    return entry.get("is_direct") is True and entry.get("requested") is True


def _report_hashes(archive_info: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(archive_info, dict):
        return ()
    hashes = archive_info.get("hashes")
    if isinstance(hashes, dict):
        result = [
            (algorithm, digest)
            for algorithm, digest in hashes.items()
            if isinstance(algorithm, str) and isinstance(digest, str)
        ]
        return tuple(sorted(result))
    legacy = archive_info.get("hash")
    if isinstance(legacy, str) and "=" in legacy:
        algorithm, digest = legacy.split("=", 1)
        return ((algorithm, digest),)
    return ()


def _write_lock(
    project: Project,
    packages: tuple[ResolvedPackage, ...],
    runtime: Runtime,
    host_artifact: HostArtifact | None = None,
) -> Path:
    path = project.root / "pylock.toml"
    lines = [
        'lock-version = "1.0"',
        'created-by = "NodePhell with stock pip"',
    ]
    if project.requires_python:
        lines.append(f"requires-python = {_toml_string(project.requires_python)}")
    lines.extend(
        (
            "",
            "[tool.nodephell.source]",
            (
                "fingerprint = "
                f"{_toml_string(project_definition_fingerprint(project))}"
            ),
            "",
        )
    )
    if project.selected_extras or project.selected_groups:
        lines.extend(
            (
                "[tool.nodephell.selection]",
                f"extras = {_toml_array(project.selected_extras)}",
                f"groups = {_toml_array(project.selected_groups)}",
                "",
            )
        )
    if runtime.artifact is not None:
        artifact = runtime.artifact
        lines.extend(
            (
                "[tool.nodephell.runtime]",
                f"implementation = {_toml_string(artifact.implementation)}",
                f"version = {_toml_string(artifact.version)}",
                f"platform = {_toml_string(artifact.platform)}",
                f"name = {_toml_string(artifact.name)}",
                f"url = {_toml_string(artifact.url)}",
                "",
                "[tool.nodephell.runtime.hashes]",
            )
        )
        for algorithm, digest in artifact.hashes:
            lines.append(
                f"{_toml_string(algorithm)} = {_toml_string(digest)}"
            )
        lines.append("")
    if project.host is not None:
        artifact = host_artifact or project.host_artifact
        lines.extend(
            (
                "[tool.nodephell.host]",
                f"kind = {_toml_string(project.host.kind)}",
            )
        )
        if project.host.requires is not None:
            lines.append(
                f"requires = {_toml_string(project.host.requires)}"
            )
        if artifact is not None:
            lines.extend(
                (
                    f"version = {_toml_string(artifact.version)}",
                    f"platform = {_toml_string(artifact.platform)}",
                    f"name = {_toml_string(artifact.name)}",
                    f"url = {_toml_string(artifact.url)}",
                    "",
                    "[tool.nodephell.host.hashes]",
                )
            )
            for algorithm, digest in artifact.hashes:
                lines.append(
                    f"{_toml_string(algorithm)} = {_toml_string(digest)}"
                )
        lines.append("")
    for package in packages:
        lines.extend(
            (
                "[[packages]]",
                f"name = {_toml_string(package.pin.name)}",
                f"version = {_toml_string(package.pin.version)}",
                "",
            )
        )
        kind = "wheels" if package.filename.endswith(".whl") else "sdist"
        heading = f"[[packages.{kind}]]" if kind == "wheels" else "[packages.sdist]"
        lines.extend(
            (
                heading,
                f"name = {_toml_string(package.filename)}",
                f"url = {_toml_string(package.url)}",
                "",
            )
        )
        if package.hashes:
            hash_heading = (
                "[packages.wheels.hashes]"
                if kind == "wheels"
                else "[packages.sdist.hashes]"
            )
            lines.append(hash_heading)
            for algorithm, digest in package.hashes:
                lines.append(
                    f"{_toml_string(algorithm)} = {_toml_string(digest)}"
                )
            lines.append("")

    return _write_lock_text(path, "\n".join(lines))


def _write_lock_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix="pylock.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(text)
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
        raise NodePhellError(f"cannot write {path}: {error}") from error
    return path


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"
