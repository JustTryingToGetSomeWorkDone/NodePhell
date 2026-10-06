# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform as platform_module
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from typing import Callable, Mapping
from urllib.request import Request, urlopen

from .errors import NodePhellError
from .versions import matches_runtime, release_tuple, runtime_version_key


_PROBE = """
import json, platform, sys, sysconfig
print(json.dumps({
    "implementation": sys.implementation.name,
    "version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI") or "",
    "platform": sysconfig.get_platform(),
}))
"""
_LATEST_RELEASE_URL = (
    "https://raw.githubusercontent.com/astral-sh/python-build-standalone/"
    "latest-release/latest-release.json"
)
_GITHUB_RELEASE_URL = (
    "https://api.github.com/repos/astral-sh/python-build-standalone/"
    "releases/tags/{tag}"
)
_ASSET = re.compile(
    r"^cpython-"
    r"(?P<version>[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?)"
    r"\+(?P<tag>[0-9]+)-"
    r"(?P<triple>[^/]+)-install_only\.tar\.gz$"
)


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
    override = os.environ.get("NODEPHELL_HOME")
    home = (
        Path(override)
        if user_home is None and override
        else Path.home() if user_home is None else user_home
    )
    return home / ".python"


def registry_path(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "runtimes" / "registry.json"


def interpreter_store(
    runtime_version: str,
    abi: str,
    user_home: Path | None = None,
) -> Path:
    version = release_tuple(runtime_version)
    if len(version) < 2:
        raise NodePhellError(
            f"runtime version has no minor component: {runtime_version}"
        )
    return (
        data_root(user_home)
        / f"python{version[0]}{version[1]}"
        / "interpreter"
        / runtime_version
        / abi
    )


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


def ensure_runtime(
    requires_python: str | None,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Runtime:
    registered = load_registry(user_home)
    try:
        return select_runtime(requires_python, registered, bootstrap_runtime())
    except NodePhellError:
        if not requires_python:
            raise
    runtime = install_runtime(requires_python, user_home, progress)
    registered = load_registry(user_home)
    return select_runtime(requires_python, registered, runtime)


def install_runtime(
    requires_python: str,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Runtime:
    asset = _select_standalone_asset(requires_python)
    announce = progress if progress is not None else lambda message: None
    announce(f"Downloading CPython {asset['version']} runtime")
    with tempfile.TemporaryDirectory(prefix="nodephell-runtime-") as temporary:
        temporary_path = Path(temporary)
        archive = temporary_path / asset["name"]
        _download(asset["url"], archive)
        extracted = temporary_path / "extracted"
        extracted.mkdir()
        _extract_tar(archive, extracted)
        prefix = _find_python_prefix(extracted)
        probed = probe_runtime(prefix / "bin" / "python3")
        target = interpreter_store(probed.version, probed.abi, user_home)
        if target.exists():
            runtime = probe_runtime(target / "bin" / "python3", (target / "lib",))
            return register_runtime(runtime.executable, runtime.library_paths, user_home)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{probed.version}-",
                    dir=target.parent,
                )
            )
            shutil.move(str(prefix), staging / "runtime")
            (staging / "runtime").rename(target)
        except OSError as error:
            raise NodePhellError(f"cannot install runtime into {target}: {error}") from error
        finally:
            if "staging" in locals() and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    announce(f"Installed CPython runtime at {target}")
    return register_runtime(target / "bin" / "python3", (target / "lib",), user_home)


def _select_standalone_asset(requires_python: str) -> dict[str, str]:
    triple = _platform_triple()
    release = _json_url(_LATEST_RELEASE_URL)
    tag = release.get("tag") if isinstance(release, dict) else None
    if not isinstance(tag, str):
        raise NodePhellError("python-build-standalone latest-release data is invalid")
    data = _json_url(_GITHUB_RELEASE_URL.format(tag=tag))
    assets = data.get("assets") if isinstance(data, dict) else None
    if not isinstance(assets, list):
        raise NodePhellError("python-build-standalone release data is invalid")

    candidates: list[dict[str, str]] = []
    for entry in assets:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        url = entry.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        match = _ASSET.fullmatch(name)
        if match is None or match.group("triple") != triple:
            continue
        version = match.group("version")
        if matches_runtime(version, requires_python):
            candidates.append({"name": name, "url": url, "version": version})
    if not candidates:
        raise NodePhellError(
            f"no downloadable CPython runtime satisfies {requires_python!r} "
            f"for {triple}"
        )
    return max(candidates, key=lambda item: runtime_version_key(item["version"]))


def _platform_triple() -> str:
    machine = platform_module.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "aarch64"
    else:
        raise NodePhellError(f"unsupported runtime-download architecture: {machine}")
    if sys.platform != "linux":
        raise NodePhellError("automatic runtime downloads are Linux-only for now")
    return f"{arch}-unknown-linux-gnu"


def _json_url(url: str) -> object:
    request = Request(url, headers={"User-Agent": "NodePhell"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (OSError, json.JSONDecodeError) as error:
        raise NodePhellError(f"cannot read {url}: {error}") from error


def _download(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": "NodePhell"})
    try:
        with urlopen(request, timeout=60) as response, target.open("wb") as file:
            shutil.copyfileobj(response, file)
    except OSError as error:
        raise NodePhellError(f"cannot download runtime archive {url}: {error}") from error


def _extract_tar(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(destination, filter="data")
    except (OSError, tarfile.TarError, tarfile.FilterError) as error:
        raise NodePhellError(f"cannot extract runtime archive {archive}: {error}") from error


def _find_python_prefix(root: Path) -> Path:
    candidates = [
        path.parent.parent
        for path in root.rglob("bin/python3")
        if path.is_file()
    ]
    if len(candidates) != 1:
        raise NodePhellError(
            f"runtime archive contained {len(candidates)} Python prefixes"
        )
    return candidates[0]


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
            runtime_version_key(runtime.version),
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
                    runtime_version_key(item.version),
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
