# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.installer import install_project, install_release
from nodephell.metadata import PackagePin, Project
from nodephell.runtime import Runtime
from nodephell.store import PackageInspection, PackageSelection


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime(
            "cpython",
            "3.16.0a0",
            Path("/runtimes/python3.16"),
            "cpython-316-x86_64-linux-gnu",
            "linux-x86_64",
            (Path("/runtimes/lib"),),
        )

    @patch("nodephell.installer.resolve_packages")
    @patch("nodephell.installer.inspect_packages")
    @patch("nodephell.installer.ensure_runtime")
    @patch("nodephell.installer.select_runtime")
    def test_install_project_acquires_a_missing_runtime(
        self,
        select_runtime,
        ensure_runtime,
        inspect_packages,
        resolve_packages,
    ) -> None:
        select_runtime.side_effect = NodePhellError("no compatible runtime")
        ensure_runtime.return_value = self.runtime
        selection = PackageSelection((), ())
        inspect_packages.return_value = PackageInspection(selection, ())
        resolve_packages.return_value = selection

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pylock.toml").write_text(
                'lock-version = "1.0"\nrequires-python = ">=3.16,<3.17"\n',
                encoding="utf-8",
            )

            result = install_project(root, root)

        self.assertEqual(result.runtime, self.runtime)
        ensure_runtime.assert_called_once_with(
            ">=3.16,<3.17",
            root,
            unittest.mock.ANY,
        )

    @patch("nodephell.installer.subprocess.run")
    def test_installs_with_stock_pip_and_commits_atomically(self, run) -> None:
        requirement_text = None

        def fake_pip(command, **kwargs):
            nonlocal requirement_text
            staging = Path(command[command.index("--target") + 1])
            requirements = Path(command[command.index("-r") + 1])
            requirement_text = requirements.read_text(encoding="utf-8")
            metadata = staging / "demo-1.2.3.dist-info" / "METADATA"
            metadata.parent.mkdir()
            metadata.write_text(
                "Metadata-Version: 2.1\nName: demo\nVersion: 1.2.3\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_pip
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = Project(
                home,
                home / "pyproject.toml",
                ">=3.16.0a0,<3.17",
                (PackagePin("demo", "1.2.3", (("sha256", "abc123"),)),),
            )
            target = install_release(
                project.packages[0],
                project,
                self.runtime,
                home,
            )

            self.assertEqual(
                target,
                home / ".python/python316/packages/demo/1.2.3",
            )
            command = run.call_args.args[0]
            self.assertIn("-I", command)
            self.assertIn("--no-deps", command)
            self.assertIn("--no-compile", command)
            self.assertIn("--require-hashes", command)
            self.assertEqual(
                requirement_text,
                "demo==1.2.3 --hash=sha256:abc123\n",
            )
            self.assertFalse((target / "requirements.txt").exists())
            self.assertTrue((target / "demo-1.2.3.dist-info/METADATA").is_file())

    @patch("nodephell.installer.subprocess.run")
    def test_failed_hash_check_leaves_no_store_entry(self, run) -> None:
        def fake_pip(command, **kwargs):
            staging = Path(command[command.index("--target") + 1])
            metadata = staging / "demo-1.2.3.dist-info" / "METADATA"
            metadata.parent.mkdir()
            metadata.write_text(
                "Metadata-Version: 2.1\nName: demo\nVersion: 1.2.3\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 1)

        run.side_effect = fake_pip
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = Project(
                home,
                home / "pylock.toml",
                None,
                (PackagePin("demo", "1.2.3", (("sha256", "wrong"),)),),
            )
            target = home / ".python/python316/packages/demo/1.2.3"

            with self.assertRaises(NodePhellError):
                install_release(
                    project.packages[0],
                    project,
                    self.runtime,
                    home,
                )

            self.assertFalse(target.exists())
            self.assertEqual(tuple(target.parent.glob(".1.2.3-*")), ())

    def test_refuses_to_replace_invalid_existing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = Project(
                home,
                home / "pyproject.toml",
                None,
                (PackagePin("demo", "1.2.3"),),
            )
            target = home / ".python/python316/packages/demo/1.2.3"
            target.mkdir(parents=True)

            with self.assertRaises(NodePhellError):
                install_release(
                    project.packages[0],
                    project,
                    self.runtime,
                    home,
                )


if __name__ == "__main__":
    unittest.main()
