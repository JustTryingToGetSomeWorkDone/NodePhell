# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable

from .activity import working
from .errors import NodePhellError
from .locking import exclusive_store_lock
from .metadata import PackagePin, Project
from .runtime import (
    Runtime,
    data_root,
    native_build_failure_guidance,
    runtime_build_environment,
)


_MANIFEST = "nodephell-editable.json"
_STORE_COMPONENT = re.compile(r"[^A-Za-z0-9._+-]+")


@dataclass(frozen=True)
class EditableInstall:
    root: Path
    bootstrap: Path
    site_packages: Path
    package: PackagePin

    @property
    def paths(self) -> tuple[Path, ...]:
        return (self.bootstrap, self.site_packages)


def editable_store(user_home: Path | None = None) -> Path:
    return data_root(user_home) / "source-projects"


def ensure_editable_project(
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> EditableInstall | None:
    if not project.has_build_system:
        return None
    target = _editable_target(project, runtime, user_home)
    fingerprint = _source_fingerprint(project.root)
    installed = _load_install(target, project, runtime, fingerprint)
    if installed is not None:
        return installed

    with exclusive_store_lock(target, user_home) as acquired:
        assert acquired
        installed = _load_install(target, project, runtime, fingerprint)
        if installed is not None:
            return installed
        with working(
            progress,
            "Preparing the source project in editable form with stock pip",
        ):
            staging = _build_editable(project, runtime, target, fingerprint)
        _replace_install(staging, target)
        installed = _load_install(target, project, runtime, fingerprint)
        if installed is None:
            raise NodePhellError(
                f"editable project installation is invalid after commit: {target}"
            )
        return installed


def resolve_editable_project(
    project: Project,
    runtime: Runtime,
    user_home: Path | None = None,
) -> EditableInstall | None:
    if not project.has_build_system:
        return None
    target = _editable_target(project, runtime, user_home)
    installed = _load_install(
        target,
        project,
        runtime,
        _source_fingerprint(project.root),
    )
    if installed is None:
        raise NodePhellError(
            "the project's editable installation is missing or out of date; "
            "run 'nodephell sync'"
        )
    return installed


def _editable_target(
    project: Project,
    runtime: Runtime,
    user_home: Path | None,
) -> Path:
    root = project.root.expanduser().resolve(strict=False)
    label = _STORE_COMPONENT.sub("-", root.name).strip("-.") or "project"
    project_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    runtime_text = "\0".join((runtime.abi, runtime.platform))
    runtime_key = hashlib.sha256(runtime_text.encode("utf-8")).hexdigest()[:16]
    abi = _STORE_COMPONENT.sub("-", runtime.abi).strip("-.") or "unknown-abi"
    return (
        editable_store(user_home)
        / f"{label}-{project_key}"
        / runtime.python_store_name
        / f"{abi}-{runtime_key}"
    )


def _source_fingerprint(root: Path) -> str:
    hasher = hashlib.sha256()
    found = False
    for name in ("pyproject.toml", "setup.cfg", "setup.py"):
        path = root / name
        if not path.is_file():
            continue
        found = True
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        try:
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError as error:
            raise NodePhellError(
                f"cannot inspect project build file {path}: {error}"
            ) from error
        hasher.update(b"\0")
    if not found:
        raise NodePhellError(f"project has no build metadata: {root}")
    return hasher.hexdigest()


def _load_install(
    target: Path,
    project: Project,
    runtime: Runtime,
    fingerprint: str,
) -> EditableInstall | None:
    if not target.is_dir() or target.is_symlink():
        return None
    manifest = target / _MANIFEST
    site_packages = target / "site-packages"
    bootstrap = target / "bootstrap"
    if (
        not manifest.is_file()
        or manifest.is_symlink()
        or not site_packages.is_dir()
        or site_packages.is_symlink()
        or not bootstrap.is_dir()
        or bootstrap.is_symlink()
    ):
        return None
    try:
        with manifest.open(encoding="utf-8") as file:
            data = json.load(file)
        package = _project_package(site_packages)
        expected = {
            "version": 1,
            "project": str(project.root.resolve(strict=True)),
            "source_fingerprint": fingerprint,
            "runtime": {
                "implementation": runtime.implementation,
                "python": runtime.python_store_name,
                "abi": runtime.abi,
                "platform": runtime.platform,
            },
            "package": {
                "name": package.name,
                "version": package.version,
            },
        }
        if data != expected:
            return None
        customizer = bootstrap / "sitecustomize.py"
        if (
            not customizer.is_file()
            or customizer.is_symlink()
            or customizer.read_text(encoding="utf-8")
            != _sitecustomize_text(site_packages)
        ):
            return None
    except (OSError, UnicodeError, json.JSONDecodeError, NodePhellError):
        return None
    return EditableInstall(
        target.resolve(),
        bootstrap.resolve(),
        site_packages.resolve(),
        package,
    )


def _build_editable(
    project: Project,
    runtime: Runtime,
    target: Path,
    fingerprint: str,
) -> Path:
    parent = target.parent
    staging: Path | None = None
    try:
        parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".editable-", dir=parent))
        install = staging / "install"
        prefix = staging / "prefix"
        install.mkdir()
    except OSError as error:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise NodePhellError(
            f"cannot create editable project staging area: {error}"
        ) from error
    assert staging is not None

    environment = runtime_build_environment(runtime)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    command = [
        str(runtime.executable),
        "-I",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-deps",
        "--no-compile",
        "--ignore-installed",
        "--prefix",
        str(prefix),
        "--editable",
        str(project.root.resolve()),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=project.root,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            message = (
                "stock pip failed while preparing the editable project "
                f"(exit status {result.returncode})"
            )
            details = (result.stdout or "").strip()
            if details:
                message += f":\n{details}"
            raise NodePhellError(
                message,
                guidance=native_build_failure_guidance(details),
            )
        candidates = tuple(
            path
            for path in prefix.rglob("site-packages")
            if path.is_dir() and not path.is_symlink()
        )
        if len(candidates) != 1:
            raise NodePhellError(
                "editable project installation produced "
                f"{len(candidates)} site-packages directories"
            )
        site_packages = install / "site-packages"
        candidates[0].rename(site_packages)
        package = _project_package(site_packages)
        bootstrap = install / "bootstrap"
        bootstrap.mkdir()
        (bootstrap / "sitecustomize.py").write_text(
            _sitecustomize_text(target / "site-packages"),
            encoding="utf-8",
        )
        manifest = {
            "version": 1,
            "project": str(project.root.resolve(strict=True)),
            "source_fingerprint": fingerprint,
            "runtime": {
                "implementation": runtime.implementation,
                "python": runtime.python_store_name,
                "abi": runtime.abi,
                "platform": runtime.platform,
            },
            "package": {
                "name": package.name,
                "version": package.version,
            },
        }
        (install / _MANIFEST).write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(prefix, ignore_errors=True)
        return install
    except (OSError, NodePhellError):
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _replace_install(staging: Path, target: Path) -> None:
    container = staging.parent
    backup: Path | None = None
    try:
        if target.exists() or target.is_symlink():
            if not target.is_dir() or target.is_symlink():
                raise NodePhellError(
                    f"editable project path is not a managed directory: {target}"
                )
            backup = Path(
                tempfile.mkdtemp(prefix=".previous-", dir=target.parent)
            )
            backup.rmdir()
            target.rename(backup)
        staging.rename(target)
    except (OSError, NodePhellError) as error:
        if backup is not None and backup.exists() and not target.exists():
            try:
                backup.rename(target)
            except OSError:
                pass
        if isinstance(error, NodePhellError):
            raise
        raise NodePhellError(
            f"cannot commit editable project installation {target}: {error}"
        ) from error
    finally:
        if backup is not None and backup.exists() and target.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if container.exists():
            shutil.rmtree(container, ignore_errors=True)


def _project_package(site_packages: Path) -> PackagePin:
    metadata_files = tuple(site_packages.glob("*.dist-info/METADATA"))
    if len(metadata_files) != 1:
        raise NodePhellError(
            "editable project installation must contain exactly one "
            "distribution metadata record"
        )
    try:
        with metadata_files[0].open("rb") as file:
            metadata = BytesParser(policy=compat32).parse(file, headersonly=True)
    except OSError as error:
        raise NodePhellError(
            f"cannot read editable project metadata: {error}"
        ) from error
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise NodePhellError("editable project metadata has no name or version")
    return PackagePin(name, version)


def _sitecustomize_text(site_packages: Path) -> str:
    return (
        "# Managed by NodePhell editable project installer v1\n"
        "import site as _nodephell_site\n"
        f"_nodephell_site.addsitedir({str(site_packages)!r})\n"
        "del _nodephell_site\n"
    )
