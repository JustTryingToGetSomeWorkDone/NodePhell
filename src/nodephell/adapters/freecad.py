# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

from ..errors import NodePhellError
from ..metadata import HostArtifact, HostRequirement
from ..runtime import Runtime, data_root
from ..store import PackageSelection
from ..versions import matches_runtime, release_tuple, runtime_version_key
from .base import EmbeddedHost


_PROBE_MARKER = "__NODEPHELL_FREECAD_HOST__"
_PROBE = f"""
import FreeCAD, json, os, platform, sys, sysconfig
from pathlib import Path
major, minor = sys.version_info[:2]
managed = Path(FreeCAD.getUserAppDataDir()) / "AdditionalPythonPackages"
package_roots = [managed / f"py{{major}}{{minor}}", managed]
app_dir = os.environ.get("APPDIR")
if app_dir:
    app_root = Path(app_dir).resolve()
    for entry in sys.path:
        try:
            candidate = Path(entry).resolve()
            inside = candidate.is_relative_to(app_root)
        except (OSError, ValueError):
            continue
        if inside and candidate.name in ("site-packages", "dist-packages"):
            package_roots.append(candidate)
print({_PROBE_MARKER!r} + json.dumps({{
    "host_version": FreeCAD.Version()[:3],
    "implementation": sys.implementation.name,
    "python_version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI") or "",
    "platform": sysconfig.get_platform(),
    "package_roots": list(dict.fromkeys(
        str(path.resolve()) for path in package_roots if path.is_dir()
    )),
}}))
"""
_RELEASES_URL = (
    "https://api.github.com/repos/FreeCAD/FreeCAD/releases?per_page=100"
)
_ASSET = re.compile(
    r"^FreeCAD_(?P<version>[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?)"
    r"-Linux-(?P<arch>x86_64|aarch64)-py(?P<python>[0-9]+)\.AppImage$"
)


class FreeCADAdapter:
    kind = "freecad"
    display_name = "FreeCAD"

    def accepts_executable(self, executable: Path) -> bool:
        return executable.name.lower() == "freecadcmd"

    def probe(self, executable: Path) -> EmbeddedHost:
        executable = executable.expanduser().resolve(strict=False)
        if not executable.is_file():
            raise NodePhellError(f"embedded host does not exist: {executable}")
        host_environment, library_paths = self._candidate_environment(executable)
        environment = dict(os.environ)
        environment.update(host_environment)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        with tempfile.TemporaryDirectory(
            prefix="nodephell-host-probe-"
        ) as temporary:
            script = Path(temporary) / "probe.py"
            script.write_text(_PROBE, encoding="utf-8")
            try:
                result = subprocess.run(
                    [str(executable), str(script)],
                    cwd=executable.parent,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise NodePhellError(
                    f"cannot inspect embedded host {executable}: {error}"
                ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise NodePhellError(
                f"cannot inspect embedded host {executable}: {detail}"
            )
        details = self._probe_details(result.stdout, executable)
        host_version = details.get("host_version")
        if not isinstance(host_version, list) or len(host_version) < 3 or not all(
            isinstance(part, str) for part in host_version[:3]
        ):
            raise NodePhellError(
                f"embedded host returned invalid version information: {executable}"
            )
        version = ".".join(host_version[:3])
        runtime_fields = (
            details.get("implementation"),
            details.get("python_version"),
            details.get("abi"),
            details.get("platform"),
        )
        if not all(isinstance(value, str) for value in runtime_fields):
            raise NodePhellError(
                f"embedded host returned invalid runtime information: {executable}"
            )
        runtime = Runtime(
            details["implementation"].lower(),
            details["python_version"],
            executable,
            details["abi"],
            details["platform"],
            library_paths,
        )
        runtime_version_key(runtime.version)
        runtime_version_key(version)
        raw_package_roots = details.get("package_roots", [])
        if not isinstance(raw_package_roots, list) or not all(
            isinstance(item, str) for item in raw_package_roots
        ):
            raise NodePhellError(
                f"embedded host returned invalid package roots: {executable}"
            )
        return EmbeddedHost(
            self.kind,
            version,
            executable,
            runtime,
            tuple(sorted(host_environment.items())),
            package_roots=tuple(
                Path(item).expanduser().resolve(strict=False)
                for item in raw_package_roots
            ),
        )

    def resolve_artifact(
        self,
        requirement: HostRequirement,
        runtime: Runtime,
    ) -> HostArtifact:
        arch, python_tag = self._asset_parameters(runtime)
        data = self._json_url(_RELEASES_URL)
        if not isinstance(data, list):
            raise NodePhellError("FreeCAD release data is invalid")

        candidates: list[HostArtifact] = []
        for release in data:
            if not isinstance(release, dict) or release.get("draft") is True:
                continue
            assets = release.get("assets")
            if not isinstance(assets, list):
                continue
            for entry in assets:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                url = entry.get("browser_download_url")
                digest = entry.get("digest")
                if not all(
                    isinstance(item, str) for item in (name, url, digest)
                ):
                    continue
                match = _ASSET.fullmatch(name)
                if (
                    match is None
                    or match.group("arch") != arch
                    or match.group("python") != python_tag
                ):
                    continue
                version = match.group("version")
                if not matches_runtime(version, requirement.requires):
                    continue
                algorithm, separator, hash_value = digest.partition(":")
                if separator != ":":
                    continue
                try:
                    candidates.append(
                        HostArtifact(
                            self.kind,
                            version,
                            runtime.platform,
                            name,
                            url,
                            ((algorithm, hash_value),),
                        )
                    )
                except NodePhellError:
                    continue
        if not candidates:
            requirement_text = requirement.requires or "any version"
            raise NodePhellError(
                f"no downloadable FreeCAD host satisfies {requirement_text!r} "
                f"for {runtime.platform} and Python {python_tag}"
            )
        return max(candidates, key=lambda item: runtime_version_key(item.version))

    def validate_artifact(
        self,
        artifact: HostArtifact,
        runtime: Runtime,
    ) -> None:
        arch, python_tag = self._asset_parameters(runtime)
        match = _ASSET.fullmatch(artifact.name)
        if (
            match is None
            or match.group("version") != artifact.version
            or match.group("arch") != arch
            or match.group("python") != python_tag
        ):
            raise NodePhellError(
                f"embedded host artifact {artifact.name!r} does not match "
                f"{runtime.platform} with Python {python_tag}"
            )

    def validate_probed_artifact(
        self,
        host: EmbeddedHost,
        artifact: HostArtifact,
    ) -> None:
        match = _ASSET.fullmatch(artifact.name)
        if match is None:
            raise NodePhellError(
                f"invalid FreeCAD artifact name: {artifact.name!r}"
            )
        python_release = release_tuple(host.runtime.version)
        python_tag = "".join(str(part) for part in python_release[:2])
        if match.group("python") != python_tag:
            raise NodePhellError(
                f"embedded host artifact Python mismatch: expected "
                f"py{match.group('python')}, got Python {host.runtime.version}"
            )

    def extract(self, archive: Path, destination: Path) -> Path:
        try:
            archive.chmod(archive.stat().st_mode | stat.S_IXUSR)
            result = subprocess.run(
                [str(archive), "--appimage-extract"],
                cwd=destination,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NodePhellError(
                f"cannot extract FreeCAD AppImage {archive}: {error}"
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise NodePhellError(
                f"cannot extract FreeCAD AppImage {archive}: {detail}"
            )
        root = destination / "squashfs-root"
        if not (root / "AppRun").is_file():
            raise NodePhellError(
                f"FreeCAD AppImage produced no application root: {archive}"
            )
        return root

    def installed_executable(self, root: Path) -> Path:
        return root / "usr" / "bin" / "freecadcmd"

    def gui_executable(self, host: EmbeddedHost) -> Path:
        names = {
            "freecadcmd": "freecad",
            "FreeCADCmd": "FreeCAD",
        }
        name = names.get(host.executable.name)
        if name is None:
            raise NodePhellError(
                f"cannot derive FreeCAD GUI executable from {host.executable}"
            )
        executable = host.executable.with_name(name)
        if not executable.is_file():
            raise NodePhellError(
                f"FreeCAD GUI executable is missing: {executable}"
            )
        return executable

    def launch_arguments(self, packages: PackageSelection) -> tuple[str, ...]:
        # FreeCAD appends --python-path, then promotes --module-path before
        # loading workbenches. The same view keeps locked packages available
        # early and gives them precedence during normal module loading.
        return tuple(
            option
            for path in packages.paths
            for option in (
                "--python-path",
                str(path),
                "--module-path",
                str(path),
            )
        )

    def augment_environment(
        self,
        host: EmbeddedHost,
        environment: dict[str, str],
    ) -> dict[str, str]:
        home = Path(environment["HOME"]) if "HOME" in environment else Path.home()
        environment["PYTHONUSERBASE"] = str(data_root(home) / "disabled-user-base")
        return environment

    @staticmethod
    def _probe_details(stdout: str, executable: Path) -> dict:
        for line in stdout.splitlines():
            if not line.startswith(_PROBE_MARKER):
                continue
            try:
                details = json.loads(line.removeprefix(_PROBE_MARKER))
            except json.JSONDecodeError as error:
                raise NodePhellError(
                    f"embedded host returned invalid probe data: {executable}"
                ) from error
            if isinstance(details, dict):
                return details
        raise NodePhellError(f"embedded host returned no probe data: {executable}")

    @staticmethod
    def _candidate_environment(
        executable: Path,
    ) -> tuple[dict[str, str], tuple[Path, ...]]:
        app_dir = executable.parent.parent.parent
        if (
            executable.parent.name == "bin"
            and executable.parent.parent.name == "usr"
            and (app_dir / "AppRun").is_file()
        ):
            library = app_dir / "usr" / "lib"
            libraries = (library.resolve(),) if library.is_dir() else ()
            return {"APPDIR": str(app_dir)}, libraries
        return {}, ()

    @staticmethod
    def _asset_parameters(runtime: Runtime) -> tuple[str, str]:
        if sys.platform != "linux":
            raise NodePhellError(
                "automatic FreeCAD downloads are Linux-only for now"
            )
        platforms = {
            "linux-x86_64": "x86_64",
            "linux-aarch64": "aarch64",
        }
        arch = platforms.get(runtime.platform)
        if arch is None:
            raise NodePhellError(
                f"unsupported FreeCAD download platform: {runtime.platform}"
            )
        release = release_tuple(runtime.version)
        if len(release) < 2:
            raise NodePhellError(
                f"runtime version has no minor component: {runtime.version}"
            )
        return arch, f"{release[0]}{release[1]}"

    @staticmethod
    def _json_url(url: str) -> object:
        request = Request(url, headers={"User-Agent": "NodePhell"})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except (OSError, json.JSONDecodeError) as error:
            raise NodePhellError(f"cannot read {url}: {error}") from error


ADAPTER = FreeCADAdapter()
