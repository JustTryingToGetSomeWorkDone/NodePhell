# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodephell.metadata import PackagePin, Project
from nodephell.runtime import Runtime
from nodephell.store import package_environment, resolve_packages


def write_distribution_metadata(
    release: Path,
    name: str,
    version: str,
) -> None:
    metadata = release / f"{name}-{version}.dist-info" / "METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime(
            "cpython",
            "3.13.15",
            Path("/runtimes/python3.13"),
            "cpython-313-x86_64-linux-gnu",
            "linux-x86_64",
            (Path("/runtimes/lib"),),
        )

    @patch("nodephell.store._ordinary_versions")
    def test_resolves_normalized_distribution_directory(
        self, ordinary_versions
    ) -> None:
        ordinary_versions.return_value = {"pyside6-essentials": None}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            release = (
                home
                / ".python/python313/packages/PySide6_Essentials/6.11.2"
            )
            write_distribution_metadata(
                release,
                "PySide6_Essentials",
                "6.11.2",
            )
            project = Project(
                home,
                home / "pylock.toml",
                ">=3.13,<3.14",
                (PackagePin("pyside6-essentials", "6.11.2"),),
            )
            selected = resolve_packages(project, self.runtime, home)
            self.assertEqual(selected.paths, (release.resolve(),))

    @patch("nodephell.store._ordinary_versions")
    def test_accepts_exact_ordinary_package(self, ordinary_versions) -> None:
        ordinary_versions.return_value = {"demo": "1.2.3"}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            package = PackagePin("demo", "1.2.3")
            project = Project(home, home / "pylock.toml", None, (package,))
            selected = resolve_packages(project, self.runtime, home)
            self.assertEqual(selected.ordinary_packages, (package,))

    @patch("nodephell.store._ordinary_versions")
    def test_project_environment_replaces_inherited_pythonpath(
        self, ordinary_versions
    ) -> None:
        ordinary_versions.return_value = {"demo": None}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            release = home / ".python/python313/packages/demo/1.0"
            write_distribution_metadata(release, "demo", "1.0")
            project = Project(
                home,
                home / "pylock.toml",
                None,
                (PackagePin("demo", "1.0"),),
            )
            selected = resolve_packages(project, self.runtime, home)
            environment = package_environment(
                self.runtime,
                selected,
                {"PYTHONPATH": "/unrelated", "LD_LIBRARY_PATH": "/system"},
            )
            self.assertEqual(environment["PYTHONPATH"], str(release.resolve()))
            self.assertEqual(
                environment["LD_LIBRARY_PATH"],
                os.pathsep.join(("/runtimes/lib", "/system")),
            )


if __name__ == "__main__":
    unittest.main()
