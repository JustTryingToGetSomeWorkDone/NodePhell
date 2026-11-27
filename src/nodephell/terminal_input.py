# SPDX-License-Identifier: GPL-3.0-only

"""Read immediate package-browser keys while keeping normal line-input fallback."""

from __future__ import annotations

from collections.abc import Callable
import os
import select
import sys


def read_browser_choice(message: str, fallback: Callable[[str], str] = input) -> str:
    try:
        import termios
        import tty
    except ImportError:
        return fallback(message)
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return fallback(message)
        descriptor = sys.stdin.fileno()
        original = termios.tcgetattr(descriptor)
        tty.setcbreak(descriptor, termios.TCSANOW)
    except (AttributeError, OSError, ValueError, termios.error):
        return fallback(message)

    def echo(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    try:
        echo(message)
        entered: list[str] = []
        while True:
            key = os.read(descriptor, 1)
            if key in {b"", b"\x04"}:
                raise EOFError
            if key == b"\x03":
                raise KeyboardInterrupt
            if key == b"\x1b":
                sequence = b""
                for _ in range(8):
                    if not select.select([descriptor], [], [], 0.1)[0]:
                        break
                    byte = os.read(descriptor, 1)
                    if not byte:
                        break
                    sequence += byte
                    if len(sequence) >= 2 and 64 <= byte[0] <= 126:
                        break
                if sequence in {b"[C", b"OC", b"[D", b"OD"}:
                    echo("\n")
                    return "right" if sequence.endswith(b"C") else "left"
                if not sequence:
                    echo("\n")
                    return ""
                continue
            if key in {b"\r", b"\n"}:
                echo("\n")
                return "".join(entered)
            if key in {b"\x7f", b"\x08"}:
                if entered:
                    entered.pop()
                    echo("\b \b")
                continue
            if key.isascii() and key.isalpha() and not entered:
                echo(key.decode() + "\n")
                return key.decode().lower()
            if key.isascii() and key.isalnum():
                entered.append(key.decode())
                echo(key.decode())
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, original)
