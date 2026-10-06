# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit

from .errors import NodePhellError
from .metadata import PackagePin, Project, normalize_name
from .runtime import Runtime, runtime_environment


@dataclass(frozen=True)
class ResolvedPackage:
    pin: PackagePin
    filename: str
    url: str
    hashes: tuple[tuple[str, str], ...]


def resolve_and_write_lock(project: Project, runtime: Runtime) -> Path:
    if project.metadata_file.name != "pyproject.toml":
        return project.metadata_file
    packages = _resolve(project, runtime)
    return _write_lock(project, packages, runtime)


def _resolve(project: Project, runtime: Runtime) -> tuple[ResolvedPackage, ...]:
    requirements = [
        f"{package.name}=={package.version}" for package in project.packages
    ]
    if not requirements:
        return ()
    environment = runtime_environment(runtime)
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
        try:
            result = subprocess.run(
                command,
                cwd=project.root,
                env=environment,
                check=False,
            )
        except OSError as error:
            raise NodePhellError(
                f"cannot run pip resolver with {runtime.executable}: {error}"
            ) from error
        if result.returncode != 0:
            raise NodePhellError(
                f"stock pip could not resolve the project "
                f"(exit status {result.returncode})"
            )
        try:
            with report.open(encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise NodePhellError(
                f"cannot read pip resolution report: {error}"
            ) from error
    packages = _parse_report(data)
    resolved = {
        normalize_name(package.pin.name): package.pin.version
        for package in packages
    }
    for requirement in project.packages:
        if resolved.get(normalize_name(requirement.name)) != requirement.version:
            raise NodePhellError(
                f"pip report omitted the requested release "
                f"{requirement.name}=={requirement.version}"
            )
    return packages


def _parse_report(data: object) -> tuple[ResolvedPackage, ...]:
    if not isinstance(data, dict) or not isinstance(data.get("install"), list):
        raise NodePhellError("pip returned an invalid resolution report")
    packages: dict[str, ResolvedPackage] = {}
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
        package = ResolvedPackage(pin, artifact, url, hashes)
        normalized = normalize_name(name)
        previous = packages.get(normalized)
        if previous is not None and previous.pin.version != version:
            raise NodePhellError(f"pip resolved conflicting versions for {name}")
        packages[normalized] = package
    return tuple(packages[name] for name in sorted(packages))


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
) -> Path:
    path = project.root / "pylock.toml"
    lines = [
        'lock-version = "1.0"',
        'created-by = "NodePhell with stock pip"',
    ]
    if project.requires_python:
        lines.append(f"requires-python = {_toml_string(project.requires_python)}")
    lines.append("")
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
            temporary.write("\n".join(lines))
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
