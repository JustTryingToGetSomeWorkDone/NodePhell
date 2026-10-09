# SPDX-License-Identifier: GPL-3.0-only

"""Small bootstrap-safe version helpers.

The launcher intentionally has no third-party dependencies. Runtime ranges
support Python final, alpha, beta, and release-candidate versions; exact package
pins retain their complete spelling, including suffixes such as ``.post0``.
"""

from __future__ import annotations

import re

from .errors import NodePhellError


_RUNTIME_VERSION = re.compile(
    r"^([0-9]+(?:\.[0-9]+)*)(?:(a|b|rc)([0-9]+))?$"
)
_CLAUSE = re.compile(
    r"^(==|!=|<=|>=|<|>|~=)\s*"
    r"([0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?)$"
)
_RELEASE_LEVEL = {"a": 0, "b": 1, "rc": 2, None: 3}


def _parsed_version(version: str) -> tuple[tuple[int, ...], int, int]:
    match = _RUNTIME_VERSION.fullmatch(version)
    if match is None:
        raise NodePhellError(f"unsupported runtime version: {version!r}")
    release, level, serial = match.groups()
    return (
        tuple(int(part) for part in release.split(".")),
        _RELEASE_LEVEL[level],
        int(serial or 0),
    )


def release_tuple(version: str) -> tuple[int, ...]:
    return _parsed_version(version)[0]


def runtime_version_key(version: str) -> tuple[tuple[int, ...], int, int]:
    return _parsed_version(version)


def lowest_runtime_line(specifier: str | None) -> tuple[str, str] | None:
    """Return the earliest named minor line and a requirement constrained to it."""
    if not specifier:
        return None
    lower_bounds: list[tuple[tuple[int, ...], int, int]] = []
    for text in specifier.split(","):
        match = _CLAUSE.fullmatch(text.strip())
        if match is None:
            raise NodePhellError(
                f"unsupported Python version requirement: {specifier!r}"
            )
        operator, required_text = match.groups()
        if operator == "==":
            return None
        if operator in {">", ">=", "~="}:
            lower_bounds.append(_parsed_version(required_text))
    if not lower_bounds:
        return None
    floor = max(lower_bounds)
    if len(floor[0]) < 2:
        return None
    major, minor = floor[0][:2]
    line = f"{major}.{minor}"
    return line, f"{specifier},<{major}.{minor + 1}"


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    size = max(len(left), len(right))
    left += (0,) * (size - len(left))
    right += (0,) * (size - len(right))
    return (left > right) - (left < right)


def _compare_versions(
    left: tuple[tuple[int, ...], int, int],
    right: tuple[tuple[int, ...], int, int],
) -> int:
    release_comparison = _compare(left[0], right[0])
    if release_comparison:
        return release_comparison
    return (left[1:] > right[1:]) - (left[1:] < right[1:])


def matches_runtime(version: str, specifier: str | None) -> bool:
    if not specifier:
        return True
    candidate = _parsed_version(version)
    clauses: list[tuple[str, str]] = []
    for text in specifier.split(","):
        match = _CLAUSE.fullmatch(text.strip())
        if match is None:
            raise NodePhellError(
                f"unsupported Python version requirement: {specifier!r}"
            )
        operator, required_text = match.groups()
        clauses.append((operator, required_text))

    if candidate[1] != _RELEASE_LEVEL[None] and not any(
        _parsed_version(required)[1] != _RELEASE_LEVEL[None]
        for _operator, required in clauses
    ):
        return False

    for operator, required_text in clauses:
        required = _parsed_version(required_text)
        comparison = _compare_versions(candidate, required)
        if operator == "==" and comparison != 0:
            return False
        if operator == "!=" and comparison == 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == ">=" and comparison < 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "~=":
            required_release = required[0]
            upper = (
                (required_release[0] + 1,)
                if len(required_release) == 1
                else required_release[:-2] + (required_release[-2] + 1,)
            )
            upper_version = (upper, _RELEASE_LEVEL[None], 0)
            if comparison < 0 or _compare_versions(candidate, upper_version) >= 0:
                return False
    return True
