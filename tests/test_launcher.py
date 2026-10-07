# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nodephell.errors import NodePhellError
from nodephell.launcher import (
    Resolution,
    execute,
    execute_package_command,
    register_resolution,
    resolve_project,
)
from nodephell.metadata import Project
from nodephell.runtime import Runtime
from nodephell.store import PackageCommand, PackageSelection


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime(
            "cpython",
            "3.16.0a0",
            Path("/runtimes/python3.16"),
            "cpython-316-x86_64-linux-gnu",
            "linux-x86_64",
        )

    @patch("nodephell.launcher.ensure_project_reference")
    def test_registers_resolved_project_before_execution(self, ensure) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = Project(
                Path("/projects/demo"),
                Path("/projects/demo/pylock.toml"),
                None,
                (),
            )
            selection = PackageSelection(())
            resolution = Resolution(self.runtime, project, selection, home)

            register_resolution(resolution)

            ensure.assert_called_once_with(project, self.runtime, selection, home)

    @patch("nodephell.launcher.bootstrap_runtime")
    def test_changed_project_definition_requires_sync(self, bootstrap) -> None:
        bootstrap.return_value = self.runtime
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\ndependencies = ["requests"]\n',
                encoding="utf-8",
            )
            (root / "pylock.toml").write_text(
                (
                    'lock-version = "1.0"\npackages = []\n\n'
                    '[tool.nodephell.source]\n'
                    f'fingerprint = "{"a" * 64}"\n'
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(NodePhellError, "nodephell sync"):
                resolve_project([], root, root)

    @patch("nodephell.launcher.bootstrap_runtime")
    def test_project_without_lock_requires_sync(self, bootstrap) -> None:
        bootstrap.return_value = self.runtime
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(NodePhellError, "nodephell sync"):
                resolve_project([], root, root)

    @patch("nodephell.launcher.os.execvpe")
    @patch("nodephell.launcher.ensure_project_reference")
    def test_execute_leaves_system_fallback_unregistered(
        self,
        ensure,
        execvpe,
    ) -> None:
        resolution = Resolution(self.runtime, None, PackageSelection(()))

        execute(["-c", "pass"], resolution)

        ensure.assert_not_called()
        execvpe.assert_called_once()

    @patch("nodephell.launcher.locked_package_commands")
    @patch("nodephell.launcher.os.execvpe")
    @patch("nodephell.launcher.ensure_project_reference")
    def test_executes_locked_package_command(
        self,
        ensure,
        execvpe,
        commands,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "packages" / "bin" / "demo"
            command.parent.mkdir(parents=True)
            command.touch()
            project = Project(root, root / "pylock.toml", None, ())
            commands.return_value = (
                PackageCommand("demo", Mock(), "demo.cli", "main"),
            )
            resolution = Resolution(
                self.runtime,
                project,
                PackageSelection((root / "packages",)),
                root,
            )

            execute_package_command("demo", ["--version"], resolution)

        execvpe.assert_called_once()
        self.assertEqual(
            execvpe.call_args.args[1][-4:],
            ["demo.cli", "main", "demo", "--version"],
        )
        ensure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
