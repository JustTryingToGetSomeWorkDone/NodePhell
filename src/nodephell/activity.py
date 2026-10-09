# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import os
import sys
from threading import Event, Thread
from typing import Iterator, TextIO


_FRAMES = (
    "⠋",
    "⠙",
    "⠹",
    "⠸",
    "⠼",
    "⠴",
    "⠦",
    "⠧",
    "⠇",
    "⠏",
)


class TerminalProgress:
    """Print milestones and animate work that may otherwise look stalled."""

    def __call__(self, message: str) -> None:
        print(message, flush=True)

    def working(self, message: str):
        return activity(message)


@contextmanager
def working(
    progress: Callable[[str], None] | None,
    message: str,
) -> Iterator[None]:
    """Use a rich activity scope when supplied, or a plain progress event."""
    if progress is None:
        yield
        return
    scope = getattr(progress, "working", None)
    if callable(scope):
        with scope(message):
            yield
        return
    progress(message)
    yield


@contextmanager
def activity(
    message: str,
    stream: TextIO | None = None,
) -> Iterator[None]:
    """Show continuing activity without hiding useful command output."""
    destination = sys.stdout if stream is None else stream
    plain_text = f"{message}. This may take a moment."
    if not _supports_animation(destination):
        print(plain_text, file=destination, flush=True)
        yield
        return

    stopped = Event()
    width = 0

    def animate() -> None:
        nonlocal width
        index = 0
        while not stopped.is_set():
            text = _fit_terminal(message, destination)
            line = f"{_FRAMES[index % len(_FRAMES)]} {text}"
            padding = " " * max(0, width - len(line))
            destination.write(f"\r{line}{padding}")
            destination.flush()
            width = len(line)
            index += 1
            stopped.wait(0.1)

    worker = Thread(target=animate, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join()
        destination.write("\r" + (" " * width) + "\r")
        destination.flush()


def _supports_animation(stream: TextIO) -> bool:
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False


def _fit_terminal(message: str, stream: TextIO) -> str:
    try:
        columns = os.get_terminal_size(stream.fileno()).columns
    except (AttributeError, OSError, ValueError):
        columns = 80
    available = max(1, columns - 3)
    if len(message) <= available:
        return message
    if available == 1:
        return "…"
    return message[: available - 1] + "…"
