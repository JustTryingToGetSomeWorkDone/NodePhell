# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform as platform_module
import subprocess
import sys
import sysconfig
import tempfile
from typing import Mapping

from .errors import NodePhellError
from .versions import matches_runtime, release_tuple


_PROBE = """
import json, platform, sys, sysconfig
print(json.dumps({
    "implementation": sys.implementation.name,
    "version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI") or "",
    "platform": sysconfig.get_platform(),
}))
"""


@dataclass(frozen=True)
class Runtime:
    implementation: str
    version: str
    executable: Path
    abi: str
    platform: str
    library_paths: tuple[Path, ...] = ()

    @property
    def identifier(self) -> str:
        return "-".join(
            (
                self.implementation,
                self.version,
                self.abi or "unknown-abi",
                self.platform,
            )
        )

    @property
    def python_store_name(self) -> str:
        version = release_tuple(self.version)
        if len(version) < 2:
            raise NodePhellError(
                f"runtime version has no minor component: {self.version}"
            )
        return f"python{version[0]}{version[1]}"


def data_root(user_home: Path | None = None) -> Path:
    home = Path.home() if user_home is None else user_home
    return home / ".python"


def registry_path(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "runtimes" / "registry.json"


def bootstrap_runtime() -> Runtime:
    return Runtime(
        implementation=sys.implementation.name,
        version=platform_module.python_version(),
        executable=Path(sys.executable).resolve(),
        abi=sysconfig.get_config_var("SOABI") or "",
        platform=sysconfig.get_platform(),
    )


def runtime_environment(
    runtime: Runtime,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    if runtime.library_paths:
        paths = [str(path) for path in runtime.library_paths]
        current = environment.get("LD_LIBRARY_PATH")
        if current:
            paths.append(current)
        environment["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
    return environment


def probe_runtime(
    executable: Path,
    library_paths: tuple[Path, ...] = (),
) -> Runtime:
    executable = executable.expanduser().resolve(strict=False)
    if not executable.is_file():
        raise NodePhellError(f"Python runtime does not exist: {executable}")
    provisional = Runtime("cpython", "0.0", executable, "", "", library_paths)
    environment = runtime_environment(provisional)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    try:
        result = subprocess.run(
            [str(executable), "-c", _PROBE],
            cwd=executable.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NodePhellError(f"cannot inspect {executable}: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise NodePhellError(f"cannot inspect {executable}: {detail}")
    try:
        details = json.loads(result.stdout.strip())
        implementation = details["implementation"]
        version = details["version"]
        abi = details["abi"]
        platform = details["platform"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise NodePhellError(
            f"runtime returned invalid identity information: {executable}"
        ) from error
    if not all(isinstance(item, str) for item in details.values()):
        raise NodePhellError(
            f"runtime returned invalid identity information: {executable}"
        )
    release_tuple(version)
    return Runtime(
        implementation.lower(),
        version,
        executable,
        abi,
        platform,
        tuple(path.expanduser().resolve(strict=False) for path in library_paths),
    )


def load_registry(user_home: Path | None = None) -> tuple[Runtime, ...]:
    path = registry_path(user_home)
    if not path.exists():
        return ()
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise NodePhellError(f"cannot read runtime registry {path}: {error}") from error
    if not isinstance(data, dict) or data.get("version") != 1:
        raise NodePhellError(f"unsupported runtime registry format: {path}")
    entries = data.get("runtimes")
    if not isinstance(entries, list):
        raise NodePhellError(f"invalid runtime registry: {path}")
    return tuple(_runtime_from_record(entry, path) for entry in entries)


def register_runtime(
    executable: Path,
    library_paths: tuple[Path, ...] = (),
    user_home: Path | None = None,
) -> Runtime:
    runtime = probe_runtime(executable, library_paths)
    runtimes = [
        item
        for item in load_registry(user_home)
        if item.executable != runtime.executable
        and item.identifier != runtime.identifier
    ]
    runtimes.append(runtime)
    _save_registry(tuple(runtimes), user_home)
    return runtime


def select_runtime(
    requires_python: str | None,
    registered: tuple[Runtime, ...],
    bootstrap: Runtime | None = None,
) -> Runtime:
    current = bootstrap_runtime() if bootstrap is None else bootstrap
    if not requires_python:
        return current

    by_executable = {current.executable: current}
    by_executable.update({runtime.executable: runtime for runtime in registered})
    registered_executables = {runtime.executable for runtime in registered}
    candidates = [
        runtime
        for runtime in by_executable.values()
        if runtime.implementation == "cpython"
        and matches_runtime(runtime.version, requires_python)
    ]
    if not candidates:
        raise NodePhellError(
            f"no registered CPython runtime satisfies {requires_python!r}; "
            "add one with 'nodephell runtime add /path/to/python'"
        )
    return max(
        candidates,
        key=lambda runtime: (
            release_tuple(runtime.version),
            runtime.executable in registered_executables,
            str(runtime.executable),
        ),
    )


def _runtime_from_record(record: object, path: Path) -> Runtime:
    if not isinstance(record, dict):
        raise NodePhellError(f"invalid runtime entry in {path}")
    required = ("implementation", "version", "executable", "abi", "platform")
    if not all(isinstance(record.get(key), str) for key in required):
        raise NodePhellError(f"invalid runtime entry in {path}")
    raw_library_paths = record.get("library_paths", [])
    if not isinstance(raw_library_paths, list) or not all(
        isinstance(item, str) for item in raw_library_paths
    ):
        raise NodePhellError(f"invalid library paths in {path}")
    executable = Path(record["executable"]).expanduser().resolve(strict=False)
    if not executable.is_file():
        raise NodePhellError(f"registered runtime is missing: {executable}")
    runtime = Runtime(
        record["implementation"].lower(),
        record["version"],
        executable,
        record["abi"],
        record["platform"],
        tuple(
            Path(item).expanduser().resolve(strict=False)
            for item in raw_library_paths
        ),
    )
    release_tuple(runtime.version)
    return runtime


def _save_registry(
    runtimes: tuple[Runtime, ...],
    user_home: Path | None,
) -> None:
    path = registry_path(user_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "runtimes": [
            {
                "implementation": runtime.implementation,
                "version": runtime.version,
                "executable": str(runtime.executable),
                "abi": runtime.abi,
                "platform": runtime.platform,
                "library_paths": [str(item) for item in runtime.library_paths],
            }
            for runtime in sorted(
                runtimes,
                key=lambda item: (
                    item.implementation,
                    release_tuple(item.version),
                    str(item.executable),
                ),
            )
        ],
    }
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix="registry.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(data, temporary, indent=2)
            temporary.write("\n")
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
        raise NodePhellError(
            f"cannot write runtime registry {path}: {error}"
        ) from error
