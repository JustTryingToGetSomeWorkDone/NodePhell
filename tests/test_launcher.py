# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodephell.launcher import Resolution, execute, register_resolution
from nodephell.metadata import Project
from nodephell.runtime import Runtime
from nodephell.store import PackageSelection


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


if __name__ == "__main__":
    unittest.main()
