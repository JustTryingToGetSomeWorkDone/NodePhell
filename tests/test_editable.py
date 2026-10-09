# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.editable import (
    ensure_editable_project,
    resolve_editable_project,
)
from nodephell.errors import NodePhellError
from nodephell.metadata import Project
from nodephell.runtime import Runtime


class EditableProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime(
            "cpython",
            "3.13.16",
            Path("/runtimes/python3.13"),
            "cpython-313-x86_64-linux-gnu",
            "linux-x86_64",
        )

    @patch("nodephell.editable.subprocess.run")
    def test_installs_and_reuses_standard_editable_project(self, run) -> None:
        def fake_pip(command, **kwargs):
            prefix = Path(command[command.index("--prefix") + 1])
            site_packages = prefix / "lib/python3.13/site-packages"
            metadata = site_packages / "demo-1.2.3.dist-info"
            metadata.mkdir(parents=True)
            (metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: demo\nVersion: 1.2.3\n",
                encoding="utf-8",
            )
            (metadata / "entry_points.txt").write_text(
                "[console_scripts]\ndemo = demo.cli:main\n",
                encoding="utf-8",
            )
            (site_packages / "demo.pth").write_text(
                f"{kwargs['cwd']}\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_pip
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "source" / "demo"
            root.mkdir(parents=True)
            (root / "pyproject.toml").write_text(
                '''[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "1.2.3"
''',
                encoding="utf-8",
            )
            project = Project(
                root,
                root / "pylock.toml",
                ">=3.13,<3.14",
                (),
                has_build_system=True,
            )

            first = ensure_editable_project(project, self.runtime, home)
            second = ensure_editable_project(project, self.runtime, home)
            resolved = resolve_editable_project(project, self.runtime, home)

            self.assertEqual(first, second)
            self.assertEqual(resolved, first)
            self.assertEqual(first.package.name, "demo")
            self.assertEqual(first.package.version, "1.2.3")
            relative = first.root.relative_to(
                home / ".python" / "source-projects"
            )
            self.assertTrue(relative.parts[0].startswith("demo-"))
            self.assertEqual(relative.parts[1], "python313")
            self.assertTrue(relative.parts[2].startswith("cpython-313-"))
            customizer = first.bootstrap / "sitecustomize.py"
            self.assertIn(str(first.site_packages), customizer.read_text())
            self.assertNotIn(".editable-", customizer.read_text())
            self.assertIn("--editable", run.call_args.args[0])
            self.assertIn("--no-deps", run.call_args.args[0])
            run.assert_called_once()

            (root / "pyproject.toml").write_text(
                '''[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "1.2.3"
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(NodePhellError, "nodephell sync"):
                resolve_editable_project(project, self.runtime, home)

    def test_missing_editable_install_requires_synchronization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "demo"
            root.mkdir()
            project_file = root / "pyproject.toml"
            project_file.write_text(
                "[build-system]\nrequires = []\n",
                encoding="utf-8",
            )
            project = Project(
                root,
                root / "pylock.toml",
                None,
                (),
                has_build_system=True,
            )

            with self.assertRaisesRegex(NodePhellError, "nodephell sync"):
                resolve_editable_project(project, self.runtime, home)
