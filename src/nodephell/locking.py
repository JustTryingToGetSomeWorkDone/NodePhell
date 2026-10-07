# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows support is future work.
    fcntl = None

from .errors import NodePhellError
from .runtime import data_root


STAGING_MANIFEST = ".nodephell-staging.json"


@contextmanager
def exclusive_store_lock(
    target: Path,
    user_home: Path | None = None,
    *,
    wait: bool = True,
) -> Iterator[bool]:
    """Hold the machine-local lock for one immutable store target."""
    if fcntl is None:
        raise NodePhellError(
            "safe concurrent store updates are not supported on this platform"
        )
    lock_root = data_root(user_home) / "locks"
    identity = os.path.abspath(os.fspath(target))
    name = hashlib.sha256(os.fsencode(identity)).hexdigest() + ".lock"
    path = lock_root / name
    try:
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_file = path.open("a+b")
    except OSError as error:
        raise NodePhellError(f"cannot open store lock {path}: {error}") from error

    operation = fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
    acquired = False
    try:
        try:
            fcntl.flock(lock_file.fileno(), operation)
            acquired = True
        except OSError as error:
            if not wait and error.errno in {errno.EACCES, errno.EAGAIN}:
                yield False
                return
            raise NodePhellError(
                f"cannot acquire store lock {path}: {error}"
            ) from error
        yield True
    finally:
        if acquired:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
