# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..metadata import HostArtifact, HostRequirement
from ..runtime import Runtime
from ..store import PackageSelection


@dataclass(frozen=True)
class EmbeddedHost:
    kind: str
    version: str
    executable: Path
    runtime: Runtime
    environment: tuple[tuple[str, str], ...] = ()
    artifact: HostArtifact | None = None
    package_roots: tuple[Path, ...] = ()

    @property
    def identifier(self) -> str:
        return "-".join((self.kind, self.version, self.runtime.abi))


class HostAdapter(Protocol):
    kind: str
    display_name: str

    def accepts_executable(self, executable: Path) -> bool: ...

    def probe(self, executable: Path) -> EmbeddedHost: ...

    def resolve_artifact(
        self,
        requirement: HostRequirement,
        runtime: Runtime,
    ) -> HostArtifact: ...

    def validate_artifact(
        self,
        artifact: HostArtifact,
        runtime: Runtime,
    ) -> None: ...

    def validate_probed_artifact(
        self,
        host: EmbeddedHost,
        artifact: HostArtifact,
    ) -> None: ...

    def extract(self, archive: Path, destination: Path) -> Path: ...

    def installed_executable(self, root: Path) -> Path: ...

    def gui_executable(self, host: EmbeddedHost) -> Path: ...

    def launch_arguments(self, packages: PackageSelection) -> tuple[str, ...]: ...

    def augment_environment(
        self,
        host: EmbeddedHost,
        environment: dict[str, str],
    ) -> dict[str, str]: ...
