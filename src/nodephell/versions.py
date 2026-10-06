# SPDX-License-Identifier: GPL-3.0-only

"""Small bootstrap-safe version helpers.

The launcher intentionally has no third-party dependencies. Runtime ranges use
numeric Python release versions; exact package pins retain their complete
spelling, including suffixes such as ``.post0``.
"""

from __future__ import annotations

import re

from .errors import NodePhellError


_RUNTIME_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")
_CLAUSE = re.compile(r"^(==|!=|<=|>=|<|>|~=)\s*([0-9]+(?:\.[0-9]+)*)$")


def release_tuple(version: str) -> tuple[int, ...]:
    if _RUNTIME_VERSION.fullmatch(version) is None:
        raise NodePhellError(f"unsupported runtime version: {version!r}")
    return tuple(int(part) for part in version.split("."))


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    size = max(len(left), len(right))
    left += (0,) * (size - len(left))
    right += (0,) * (size - len(right))
    return (left > right) - (left < right)


def matches_runtime(version: str, specifier: str | None) -> bool:
    if not specifier:
        return True
    candidate = release_tuple(version)
    for text in specifier.split(","):
        match = _CLAUSE.fullmatch(text.strip())
        if match is None:
            raise NodePhellError(
                f"unsupported Python version requirement: {specifier!r}"
            )
        operator, required_text = match.groups()
        required = release_tuple(required_text)
        comparison = _compare(candidate, required)
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
            upper = (
                (required[0] + 1,)
                if len(required) == 1
                else required[:-2] + (required[-2] + 1,)
            )
            if comparison < 0 or _compare(candidate, upper) >= 0:
                return False
    return True
