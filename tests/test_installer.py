# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.installer import install_project, install_release
from nodephell.metadata import PackagePin, Project, RuntimeArtifact
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
    def test_install_project_acquires_its_locked_runtime(
        self,
        ensure_runtime,
        inspect_packages,
        resolve_packages,
    ) -> None:
        ensure_runtime.return_value = self.runtime
        selection = PackageSelection((), ())
        inspect_packages.return_value = PackageInspection(selection, ())
        resolve_packages.return_value = selection
        locked = RuntimeArtifact(
            "cpython",
            "3.16.0a0",
            "x86_64-unknown-linux-gnu",
            (
                "cpython-3.16.0a0+20261003-x86_64-unknown-linux-gnu-"
                "install_only.tar.gz"
            ),
            (
                "https://example.invalid/cpython-3.16.0a0%2B20261003-"
                "x86_64-unknown-linux-gnu-install_only.tar.gz"
            ),
            (("sha256", "a" * 64),),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pylock.toml").write_text(
                f'''lock-version = "1.0"
requires-python = ">=3.16.0a0,<3.17"

[tool.nodephell.runtime]
implementation = "{locked.implementation}"
version = "{locked.version}"
platform = "{locked.platform}"
name = "{locked.name}"
url = "{locked.url}"

[tool.nodephell.runtime.hashes]
sha256 = "{locked.sha256}"
''',
                encoding="utf-8",
            )

            result = install_project(root, root)

        self.assertEqual(result.runtime, self.runtime)
        ensure_runtime.assert_called_once_with(
            "==3.16.0a0",
            root,
            unittest.mock.ANY,
            locked,
        )

    @patch("nodephell.installer.resolve_packages")
    @patch("nodephell.installer.inspect_packages")
    @patch("nodephell.installer.resolve_and_write_lock")
    @patch("nodephell.installer.ensure_runtime")
    @patch("nodephell.installer.resolve_runtime_artifact")
    @patch("nodephell.installer.load_project")
    def test_fresh_project_locks_selected_runtime_artifact(
        self,
        load_project,
        resolve_runtime_artifact,
        ensure_runtime,
        resolve_and_write_lock,
        inspect_packages,
        resolve_packages,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\nrequires-python = ">=3.16,<3.17"\n',
                encoding="utf-8",
            )
            name = (
                "cpython-3.16.1+20261003-x86_64-unknown-linux-gnu-"
                "install_only.tar.gz"
            )
            locked = RuntimeArtifact(
                "cpython",
                "3.16.1",
                "x86_64-unknown-linux-gnu",
                name,
                f"https://example.invalid/{name.replace('+', '%2B')}",
                (("sha256", "b" * 64),),
            )
            source = Project(
                root,
                root / "pyproject.toml",
                ">=3.16,<3.17",
                (),
            )
            generated = Project(
                root,
                root / "pylock.toml",
                ">=3.16,<3.17",
                (),
                locked,
            )
            managed = Runtime(
                "cpython",
                locked.version,
                Path("/runtimes/python3.16"),
                "cpython-316-x86_64-linux-gnu",
                "linux-x86_64",
                artifact=locked,
            )
            selection = PackageSelection((), ())
            load_project.side_effect = (source, generated)
            resolve_runtime_artifact.return_value = locked
            ensure_runtime.return_value = managed
            resolve_and_write_lock.return_value = root / "pylock.toml"
            inspect_packages.return_value = PackageInspection(selection, ())
            resolve_packages.return_value = selection

            result = install_project(root, root)

        resolve_runtime_artifact.assert_called_once_with(">=3.16,<3.17")
        ensure_runtime.assert_called_once_with(
            "==3.16.1",
            root,
            unittest.mock.ANY,
            locked,
        )
        resolve_and_write_lock.assert_called_once_with(source, managed)
        self.assertEqual(result.project, generated)

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
