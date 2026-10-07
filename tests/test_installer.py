# SPDX-License-Identifier: GPL-3.0-only

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.host import EmbeddedHost
from nodephell.installer import install_project, install_release
from nodephell.metadata import (
    HostRequirement,
    PackageArtifact,
    PackagePin,
    Project,
    RuntimeArtifact,
)
from nodephell.runtime import Runtime
from nodephell.store import PackageInspection, PackageSelection, stored_release_path


class InstallerTests(unittest.TestCase):
    PACKAGE_SHA256 = "c" * 64

    def setUp(self) -> None:
        self.runtime = Runtime(
            "cpython",
            "3.16.0a0",
            Path("/runtimes/python3.16"),
            "cpython-316-x86_64-linux-gnu",
            "linux-x86_64",
            (Path("/runtimes/lib"),),
        )

    @patch("nodephell.installer.ensure_project_reference")
    @patch("nodephell.installer.resolve_packages")
    @patch("nodephell.installer.inspect_packages")
    @patch("nodephell.installer.ensure_runtime")
    def test_install_project_acquires_its_locked_runtime(
        self,
        ensure_runtime,
        inspect_packages,
        resolve_packages,
        ensure_project_reference,
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
        ensure_project_reference.assert_called_once_with(
            unittest.mock.ANY,
            self.runtime,
            selection,
            root,
        )

    @patch("nodephell.installer.ensure_project_reference")
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
        ensure_project_reference,
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
        resolve_and_write_lock.assert_called_once_with(source, managed, None)
        ensure_project_reference.assert_called_once_with(
            generated,
            managed,
            selection,
            root,
        )
        self.assertEqual(result.project, generated)

    def test_fresh_project_reuses_registered_compatible_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )
            requirement = HostRequirement("freecad", "==1.1.3")
            source = Project(
                root,
                root / "pyproject.toml",
                None,
                (),
                host=requirement,
            )
            generated = Project(
                root,
                root / "pylock.toml",
                None,
                (),
                host=requirement,
            )
            registered_host = EmbeddedHost(
                "freecad",
                "1.1.3",
                Path("/hosts/freecadcmd"),
                self.runtime,
            )
            selection = PackageSelection((), ())

            with (
                patch("nodephell.installer.load_project") as load_project,
                patch("nodephell.installer.ensure_runtime") as ensure_runtime,
                patch(
                    "nodephell.installer.resolve_and_write_lock"
                ) as resolve_and_write_lock,
                patch("nodephell.installer.load_hosts") as load_hosts,
                patch("nodephell.installer.select_host") as select_host,
                patch(
                    "nodephell.installer.resolve_host_artifact"
                ) as resolve_host_artifact,
                patch("nodephell.installer.ensure_host") as ensure_host,
                patch("nodephell.installer.inspect_packages") as inspect_packages,
                patch("nodephell.installer.resolve_packages") as resolve_packages,
                patch(
                    "nodephell.installer.ensure_project_reference"
                ) as ensure_project_reference,
            ):
                load_project.side_effect = (source, generated)
                ensure_runtime.return_value = self.runtime
                resolve_and_write_lock.return_value = root / "pylock.toml"
                load_hosts.return_value = (registered_host,)
                select_host.return_value = registered_host
                ensure_host.return_value = registered_host
                inspect_packages.return_value = PackageInspection(selection, ())
                resolve_packages.return_value = selection

                result = install_project(root, root)

            select_host.assert_called_once_with(
                requirement,
                (registered_host,),
                self.runtime,
            )
            resolve_host_artifact.assert_not_called()
            resolve_and_write_lock.assert_called_once_with(
                source,
                self.runtime,
                None,
            )
            ensure_host.assert_called_once_with(
                requirement,
                self.runtime,
                root,
                unittest.mock.ANY,
                None,
            )
            inspect_packages.assert_called_once_with(
                generated,
                self.runtime,
                root,
                (),
                include_ordinary=False,
            )
            resolve_packages.assert_called_once_with(
                generated,
                self.runtime,
                root,
                (),
                include_ordinary=False,
            )
            ensure_project_reference.assert_called_once_with(
                generated,
                self.runtime,
                selection,
                root,
            )
            self.assertIs(result.host, registered_host)

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
                (self.package_pin(),),
            )
            target = install_release(
                project.packages[0],
                project,
                self.runtime,
                home,
            )

            self.assertEqual(
                target,
                home
                / ".python/packages/demo/1.2.3"
                / "demo-1.2.3-py3-none-any.whl"
                / self.PACKAGE_SHA256
                / "root",
            )
            command = run.call_args.args[0]
            self.assertIn("-I", command)
            self.assertIn("--no-deps", command)
            self.assertIn("--no-compile", command)
            self.assertIn("--require-hashes", command)
            self.assertEqual(
                requirement_text,
                (
                    "demo @ https://example.invalid/"
                    "demo-1.2.3-py3-none-any.whl "
                    f"--hash=sha256:{self.PACKAGE_SHA256}\n"
                ),
            )
            self.assertFalse((target / "requirements.txt").exists())
            self.assertTrue((target / "demo-1.2.3.dist-info/METADATA").is_file())
            self.assertTrue((target.parent / "nodephell.json").is_file())

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
                (self.package_pin(),),
            )
            target = (
                home
                / ".python/packages/demo/1.2.3"
                / "demo-1.2.3-py3-none-any.whl"
                / self.PACKAGE_SHA256
            )

            with self.assertRaises(NodePhellError):
                install_release(
                    project.packages[0],
                    project,
                    self.runtime,
                    home,
                )

            self.assertFalse(target.exists())
            self.assertEqual(tuple(target.parent.glob(".1.2.3-*")), ())

    @patch("nodephell.installer.subprocess.run")
    def test_concurrent_installers_download_one_release_once(self, run) -> None:
        entered_pip = threading.Event()
        finish_pip = threading.Event()

        def fake_pip(command, **kwargs):
            staging = Path(command[command.index("--target") + 1])
            entered_pip.set()
            self.assertTrue(finish_pip.wait(5))
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
                home / "pylock.toml",
                None,
                (self.package_pin(),),
            )
            arguments = (project.packages[0], project, self.runtime, home)

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(install_release, *arguments)
                self.assertTrue(entered_pip.wait(5))
                second = executor.submit(install_release, *arguments)
                finish_pip.set()
                self.assertEqual(first.result(timeout=5), second.result(timeout=5))

            self.assertEqual(run.call_count, 1)

    def test_refuses_to_replace_invalid_existing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = Project(
                home,
                home / "pyproject.toml",
                None,
                (self.package_pin(),),
            )
            target = stored_release_path(
                project.packages[0],
                self.runtime,
                home,
            )
            target.parent.mkdir(parents=True)

            with self.assertRaises(NodePhellError):
                install_release(
                    project.packages[0],
                    project,
                    self.runtime,
                    home,
                )

    @classmethod
    def package_pin(cls) -> PackagePin:
        name = "demo-1.2.3-py3-none-any.whl"
        hashes = (("sha256", cls.PACKAGE_SHA256),)
        return PackagePin(
            "demo",
            "1.2.3",
            (
                PackageArtifact(
                    "wheel",
                    name,
                    f"https://example.invalid/{name}",
                    hashes,
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
