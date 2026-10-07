# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import sys

from .errors import NodePhellError
from .metadata import (
    PackagePin,
    PackageRequirement,
    normalize_name,
    parse_package_requirement,
)
from .versions import matches_runtime, release_tuple


_SIMPLE_PYTHON = re.compile(
    r"^[0-9]+(?:\.[0-9]+){1,2}(?:(?:a|b|rc)[0-9]+)?$"
)


def initialize_project(
    start: Path | None = None,
    prompt: Callable[[str], str] | None = None,
    announce: Callable[[str], None] | None = None,
) -> Path:
    root = (Path.cwd() if start is None else start.expanduser()).resolve()
    if not root.is_dir():
        raise NodePhellError(f"project directory does not exist: {root}")
    path = root / "pyproject.toml"
    if path.exists() or path.is_symlink():
        raise NodePhellError(f"project definition already exists: {path}")

    ask = input if prompt is None else prompt
    say = print if announce is None else announce
    default_name = root.name
    name = _ask_project_name(ask, say, default_name)
    version = _ask_project_version(ask, say)
    default_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    requires_python = _ask_python_requirement(ask, say, default_python)
    requirements = _ask_dependencies(ask, say)

    say("")
    say(f"Project: {name} {version}")
    say(f"Python: {requires_python}")
    if requirements:
        say("Dependencies:")
        for requirement in requirements:
            say(f"  {requirement.text}")
    else:
        say("Dependencies: none")
    if not _confirmed(_read(ask, "Create and prepare this project? [Y/n]: ")):
        raise NodePhellError("initialization cancelled")

    text = _project_toml(name, version, requires_python, requirements)
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(text)
    except OSError as error:
        raise NodePhellError(f"cannot create {path}: {error}") from error
    return path


def _ask_project_name(
    prompt: Callable[[str], str],
    announce: Callable[[str], None],
    default: str,
) -> str:
    while True:
        value = _read(prompt, f"Project name [{default}]: ").strip() or default
        try:
            PackagePin(value, "0")
        except NodePhellError as error:
            announce(f"Invalid project name: {error}")
            continue
        return value


def _ask_project_version(
    prompt: Callable[[str], str],
    announce: Callable[[str], None],
) -> str:
    while True:
        value = _read(prompt, "Project version [0.1.0]: ").strip() or "0.1.0"
        try:
            PackagePin("project", value)
        except NodePhellError as error:
            announce(f"Invalid project version: {error}")
            continue
        return value


def _ask_python_requirement(
    prompt: Callable[[str], str],
    announce: Callable[[str], None],
    default: str,
) -> str:
    while True:
        value = _read(prompt, f"Target Python [{default}]: ").strip() or default
        try:
            return _python_requirement(value)
        except NodePhellError as error:
            announce(f"Invalid Python requirement: {error}")


def _python_requirement(value: str) -> str:
    if _SIMPLE_PYTHON.fullmatch(value):
        release = release_tuple(value)
        if len(release) == 2 and not any(level in value for level in ("a", "b", "rc")):
            major, minor = release
            return f">={major}.{minor},<{major}.{minor + 1}"
        return f"=={value}"
    matches_runtime("0.0.0", value)
    return value


def _ask_dependencies(
    prompt: Callable[[str], str],
    announce: Callable[[str], None],
) -> tuple[PackageRequirement, ...]:
    result: list[PackageRequirement] = []
    seen: set[str] = set()
    while True:
        name = _read(prompt, "Add dependency (blank to finish): ").strip()
        if not name:
            return tuple(result)
        try:
            base = parse_package_requirement(name)
            if base.specifiers:
                raise NodePhellError("enter the version at the next prompt")
        except NodePhellError as error:
            announce(f"Invalid dependency: {error}")
            continue
        normalized = normalize_name(base.name)
        if normalized in seen:
            announce(f"Dependency {base.name!r} was already added.")
            continue
        requirement = _ask_dependency_version(prompt, announce, base)
        seen.add(normalized)
        result.append(requirement)


def _ask_dependency_version(
    prompt: Callable[[str], str],
    announce: Callable[[str], None],
    base: PackageRequirement,
) -> PackageRequirement:
    while True:
        version = _read(
            prompt,
            f"Version for {base.name} [latest compatible]: ",
        ).strip()
        text = base.text
        if version:
            text += version if version[0] in "<>=!~" else f"=={version}"
        try:
            return parse_package_requirement(text)
        except NodePhellError as error:
            announce(f"Invalid dependency version: {error}")


def _project_toml(
    name: str,
    version: str,
    requires_python: str,
    requirements: tuple[PackageRequirement, ...],
) -> str:
    lines = [
        "[project]",
        f"name = {json.dumps(name)}",
        f"version = {json.dumps(version)}",
        f"requires-python = {json.dumps(requires_python)}",
    ]
    if requirements:
        lines.append("dependencies = [")
        lines.extend(f"    {json.dumps(item.text)}," for item in requirements)
        lines.append("]")
    else:
        lines.append("dependencies = []")
    return "\n".join(lines) + "\n"


def _confirmed(value: str) -> bool:
    return value.strip().lower() in {"", "y", "yes"}


def _read(prompt: Callable[[str], str], text: str) -> str:
    try:
        return prompt(text)
    except EOFError as error:
        raise NodePhellError("initialization cancelled") from error
