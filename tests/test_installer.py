# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.installer import install_release
from nodephell.metadata import PackagePin, Project
from nodephell.runtime import Runtime


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

    @patch("nodephell.installer.subprocess.run")
    def test_installs_with_stock_pip_and_commits_atomically(self, run) -> None:
        def fake_pip(command, **kwargs):
            staging = Path(command[command.index("--target") + 1])
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
                (PackagePin("demo", "1.2.3"),),
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
            self.assertTrue((target / "demo-1.2.3.dist-info/METADATA").is_file())

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
