# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.metadata import PackageArtifact, PackagePin, Project
from nodephell.runtime import Runtime
from nodephell.store import (
    package_environment,
    release_matches,
    resolve_packages,
    stored_release_path,
    write_release_manifest,
)


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


def locked_package(
    name: str = "demo",
    version: str = "1.2.3",
    kind: str = "wheel",
    digest_character: str = "d",
) -> PackagePin:
    filename_name = name.replace("-", "_").lower()
    filename = (
        f"{filename_name}-{version}-py3-none-any.whl"
        if kind == "wheel"
        else f"{filename_name}-{version}.tar.gz"
    )
    hashes = (("sha256", digest_character * 64),)
    return PackagePin(
        name,
        version,
        (
            PackageArtifact(
                kind,
                filename,
                f"https://example.invalid/{filename}",
                hashes,
            ),
        ),
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

    def test_same_wheel_has_one_store_path_across_python_versions(self) -> None:
        other = Runtime(
            "cpython",
            "3.16.0a0",
            Path("/runtimes/python3.16"),
            "cpython-316-x86_64-linux-gnu",
            "linux-x86_64",
        )
        home = Path("/users/example")
        package = locked_package()

        first = stored_release_path(package, self.runtime, home)
        second = stored_release_path(package, other, home)

        self.assertEqual(first, second)
        self.assertEqual(
            first,
            home
            / ".python/packages/demo/1.2.3"
            / "demo-1.2.3-py3-none-any.whl"
            / ("d" * 64)
            / "root",
        )

    def test_source_builds_remain_runtime_specific(self) -> None:
        other = Runtime(
            "cpython",
            "3.16.0a0",
            Path("/runtimes/python3.16"),
            "cpython-316-x86_64-linux-gnu",
            "linux-x86_64",
        )
        home = Path("/users/example")
        package = locked_package(kind="sdist")

        self.assertNotEqual(
            stored_release_path(package, self.runtime, home),
            stored_release_path(package, other, home),
        )

    def test_exact_release_requires_matching_store_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            package = locked_package()
            release = stored_release_path(package, self.runtime, home)
            write_distribution_metadata(release, package.name, package.version)

            self.assertFalse(release_matches(package, release, self.runtime))
            write_release_manifest(package, self.runtime, release)
            self.assertTrue(release_matches(package, release, self.runtime))

    def test_store_requires_one_exact_locked_download(self) -> None:
        with self.assertRaisesRegex(NodePhellError, "one exact locked download"):
            stored_release_path(
                PackagePin("demo", "1.2.3"),
                self.runtime,
                Path("/users/example"),
            )

    @patch("nodephell.store._ordinary_versions")
    def test_resolves_normalized_distribution_directory(
        self, ordinary_versions
    ) -> None:
        ordinary_versions.return_value = {"pyside6-essentials": None}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            package = locked_package(
                "pyside6-essentials",
                "6.11.2",
            )
            release = stored_release_path(package, self.runtime, home)
            write_distribution_metadata(
                release,
                "PySide6_Essentials",
                "6.11.2",
            )
            write_release_manifest(package, self.runtime, release)
            project = Project(
                home,
                home / "pylock.toml",
                ">=3.13,<3.14",
                (package,),
            )
            selected = resolve_packages(project, self.runtime, home)
            self.assertEqual(len(selected.paths), 1)
            self.assertTrue(selected.paths[0].is_dir())
            self.assertTrue(
                (selected.paths[0] / "PySide6_Essentials-6.11.2.dist-info").is_dir()
            )

    @patch("nodephell.store._ordinary_versions")
    def test_accepts_exact_ordinary_package(self, ordinary_versions) -> None:
        ordinary_versions.return_value = {"demo": "1.2.3"}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            package = locked_package()
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
            package = locked_package("demo", "1.0")
            release = stored_release_path(package, self.runtime, home)
            write_distribution_metadata(release, "demo", "1.0")
            write_release_manifest(package, self.runtime, release)
            project = Project(
                home,
                home / "pylock.toml",
                None,
                (package,),
            )
            selected = resolve_packages(project, self.runtime, home)
            environment = package_environment(
                self.runtime,
                selected,
                {"PYTHONPATH": "/unrelated", "LD_LIBRARY_PATH": "/system"},
            )
            self.assertEqual(environment["PYTHONPATH"], str(selected.paths[0]))
            self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(
                environment["LD_LIBRARY_PATH"],
                os.pathsep.join(("/runtimes/lib", "/system")),
            )

    @patch("nodephell.store._ordinary_versions")
    def test_composes_shared_regular_import_package(
        self, ordinary_versions
    ) -> None:
        ordinary_versions.return_value = {
            "pyside6": None,
            "pyside6-addons": None,
            "pyside6-essentials": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            packages = (
                locked_package("PySide6", "6.11.2", digest_character="d"),
                locked_package(
                    "PySide6_Essentials",
                    "6.11.2",
                    digest_character="e",
                ),
                locked_package(
                    "PySide6_Addons",
                    "6.11.2",
                    digest_character="f",
                ),
            )
            pyside6, essentials, addons = (
                stored_release_path(package, self.runtime, home)
                for package in packages
            )
            write_distribution_metadata(pyside6, "PySide6", "6.11.2")
            write_distribution_metadata(
                essentials,
                "PySide6_Essentials",
                "6.11.2",
            )
            write_distribution_metadata(addons, "PySide6_Addons", "6.11.2")
            for package, release in zip(packages, (pyside6, essentials, addons)):
                write_release_manifest(package, self.runtime, release)
            (pyside6 / "PySide6").mkdir()
            (pyside6 / "PySide6/__init__.py").write_text("", encoding="utf-8")
            (essentials / "PySide6/QtCore.py").parent.mkdir()
            (essentials / "PySide6/QtCore.py").write_text("", encoding="utf-8")
            (addons / "PySide6/QtSvgWidgets.py").parent.mkdir()
            (addons / "PySide6/QtSvgWidgets.py").write_text("", encoding="utf-8")
            (pyside6 / "PySide6/common.pyi").write_text(
                "# shared stub\n",
                encoding="utf-8",
            )
            (addons / "PySide6/common.pyi").write_text(
                "# shared stub\n",
                encoding="utf-8",
            )
            (pyside6 / "PySide6/__pycache__").mkdir()
            (pyside6 / "PySide6/__pycache__/common.pyc").write_bytes(b"first")
            (addons / "PySide6/__pycache__").mkdir()
            (addons / "PySide6/__pycache__/common.pyc").write_bytes(b"second")
            project = Project(
                home,
                home / "pylock.toml",
                ">=3.13,<3.14",
                packages,
            )

            selected = resolve_packages(project, self.runtime, home)
            composed = selected.paths[0]

            self.assertEqual(len(selected.paths), 1)
            self.assertTrue((composed / "PySide6/__init__.py").is_symlink())
            self.assertTrue((composed / "PySide6/QtCore.py").is_symlink())
            self.assertTrue((composed / "PySide6/QtSvgWidgets.py").is_symlink())
            self.assertTrue((composed / "PySide6/common.pyi").is_symlink())
            self.assertFalse((composed / "PySide6/__pycache__").exists())
            self.assertTrue((composed / "PySide6-6.11.2.dist-info").is_dir())
            self.assertTrue(
                (composed / "PySide6_Essentials-6.11.2.dist-info").is_dir()
            )
            self.assertTrue(
                (composed / "PySide6_Addons-6.11.2.dist-info").is_dir()
            )

    @patch("nodephell.store._ordinary_versions")
    def test_rejects_different_files_at_the_same_import_path(
        self,
        ordinary_versions,
    ) -> None:
        ordinary_versions.return_value = {"first": None, "second": None}
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            packages = (
                locked_package("first", "1.0", digest_character="1"),
                locked_package("second", "1.0", digest_character="2"),
            )
            first, second = (
                stored_release_path(package, self.runtime, home)
                for package in packages
            )
            write_distribution_metadata(first, "first", "1.0")
            write_distribution_metadata(second, "second", "1.0")
            for package, release in zip(packages, (first, second)):
                write_release_manifest(package, self.runtime, release)
            (first / "shared").mkdir()
            (second / "shared").mkdir()
            (first / "shared/module.py").write_text("FIRST = 1\n", encoding="utf-8")
            (second / "shared/module.py").write_text("SECOND = 2\n", encoding="utf-8")
            project = Project(
                home,
                home / "pylock.toml",
                None,
                packages,
            )

            with self.assertRaisesRegex(NodePhellError, "composition conflict"):
                resolve_packages(project, self.runtime, home)


if __name__ == "__main__":
    unittest.main()
