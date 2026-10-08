# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
import sys
from typing import TextIO


class NodePhellError(Exception):
    """A user-facing NodePhell error."""


_ERROR_STYLE = "\033[1;91m"
_WARNING_STYLE = "\033[1;93m"
_DETAIL_STYLE = "\033[1;96m"
_RESET_STYLE = "\033[0m"


def print_error(error: BaseException, stream: TextIO | None = None) -> None:
    """Write a clearly labelled error, using color only on capable terminals."""
    _print_labelled("error", str(error), _ERROR_STYLE, stream)


def print_warning(message: str, stream: TextIO | None = None) -> None:
    """Write a clearly labelled warning without relying on color alone."""
    _print_labelled("warning", message, _WARNING_STYLE, stream)


def highlight_detail(value: object, stream: TextIO | None = None) -> str:
    """Highlight a filename or other important value on an interactive stream."""
    destination = sys.stdout if stream is None else stream
    text = str(value)
    if _supports_color(destination):
        return f"{_DETAIL_STYLE}{text}{_RESET_STYLE}"
    return text


def _print_labelled(
    label: str,
    message: str,
    style: str,
    stream: TextIO | None,
) -> None:
    destination = sys.stderr if stream is None else stream
    text = f"nodephell: {label}: {message}"
    if _supports_color(destination):
        text = f"{style}{text}{_RESET_STYLE}"
    print(text, file=destination)


def _supports_color(stream: TextIO) -> bool:
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False
