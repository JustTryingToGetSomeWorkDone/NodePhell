# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.launchers import (
    configure_shell_path,
    install_application_launcher,
    install_launchers,
    install_package_launchers,
    path_problem,
    remove_application_launcher,
    remove_shell_path,
    uninstall_launchers,
)


class LauncherTests(unittest.TestCase):
    def test_configures_bash_path_once_and_removes_only_its_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            bashrc = home / ".bashrc"
            original = 'export PATH="$HOME/.pyenv/shims:$PATH"\n'
            bashrc.write_text(original, encoding="utf-8")

            first = configure_shell_path(home, shell="/bin/bash")
            second = configure_shell_path(home, shell="/bin/bash")
            configured = bashrc.read_text(encoding="utf-8")
            removed = remove_shell_path(home)

            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            self.assertGreater(
                configured.index("# >>> NodePhell launchers >>>"),
                configured.index(".pyenv/shims"),
            )
            self.assertTrue(removed.changed)
            self.assertEqual(bashrc.read_text(encoding="utf-8"), original)

    def test_path_problem_checks_each_core_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            launchers = home / ".local" / "bin"
            other = home / ".pyenv" / "shims"
            launchers.mkdir(parents=True)
            other.mkdir(parents=True)
            for name in ("nodephell", "python", "python3"):
                command = launchers / name
                command.touch()
                command.chmod(0o755)
            competing = other / "python"
            competing.touch()
            competing.chmod(0o755)

            with patch.dict(
                os.environ,
                {"PATH": f"{other}:{launchers}"},
            ):
                problem = path_problem(home)
            with patch.dict(
                os.environ,
                {"PATH": f"{launchers}:{other}"},
            ):
                healthy = path_problem(home)

            self.assertIn("so python uses NodePhell", problem)
            self.assertIsNone(healthy)

    def test_installs_updates_and_uninstalls_owned_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "checkout"
            cli = source_root / "src" / "nodephell" / "cli.py"
            cli.parent.mkdir(parents=True)
            cli.touch()

            first = install_launchers(root, source_root=source_root)
            second = install_launchers(root, source_root=source_root)
            removed = uninstall_launchers(root)

            self.assertEqual(len(first.installed), 3)
            self.assertEqual(len(second.unchanged), 3)
            self.assertEqual(set(removed.removed), set(first.installed))
            self.assertTrue(all(not path.exists() for path in first.installed))

    def test_refuses_to_replace_or_remove_unowned_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "checkout"
            cli = source_root / "src" / "nodephell" / "cli.py"
            cli.parent.mkdir(parents=True)
            cli.touch()
            command = root / ".local" / "bin" / "python"
            command.parent.mkdir(parents=True)
            command.write_text("#!/bin/sh\n", encoding="utf-8")

            with self.assertRaisesRegex(NodePhellError, "refusing to replace"):
                install_launchers(root, source_root=source_root)
            with self.assertRaisesRegex(NodePhellError, "refusing to remove"):
                uninstall_launchers(root)

            self.assertEqual(command.read_text(), "#!/bin/sh\n")

    def test_installs_and_uninstalls_package_command_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "checkout"
            cli = source_root / "src" / "nodephell" / "cli.py"
            cli.parent.mkdir(parents=True)
            cli.touch()

            change = install_package_launchers(
                ("demo",), root, source_root=source_root
            )
            removed = uninstall_launchers(root)

            self.assertEqual([path.name for path in change.installed], ["demo"])
            self.assertIn(change.installed[0], removed.removed)
            self.assertFalse(change.installed[0].exists())

    def test_package_commands_preserve_unowned_name_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "checkout"
            cli = source_root / "src" / "nodephell" / "cli.py"
            cli.parent.mkdir(parents=True)
            cli.touch()
            existing = root / ".local" / "bin" / "f2py"
            existing.parent.mkdir(parents=True)
            existing.write_text("#!/old/python\n", encoding="utf-8")

            change = install_package_launchers(
                ("demo", "f2py"), root, source_root=source_root
            )

            self.assertEqual([path.name for path in change.installed], ["demo"])
            self.assertEqual(change.skipped, (existing,))
            self.assertEqual(existing.read_text(), "#!/old/python\n")

    def test_installs_and_removes_bound_application_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "checkout"
            module = source_root / "src" / "nodephell" / "applications.py"
            module.parent.mkdir(parents=True)
            module.touch()

            installed = install_application_launcher(
                "FreeCAD", root, source_root=source_root
            )
            text = installed.installed[0].read_text(encoding="utf-8")
            removed = remove_application_launcher("FreeCAD", root)

            self.assertIn("app_main('FreeCAD')", text)
            self.assertEqual(removed.removed, installed.installed)
            self.assertFalse(installed.installed[0].exists())

    def test_package_launcher_preserves_application_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "checkout"
            module = source_root / "src" / "nodephell" / "applications.py"
            module.parent.mkdir(parents=True)
            module.touch()
            install_application_launcher(
                "FreeCAD", root, source_root=source_root
            )

            change = install_package_launchers(
                ("FreeCAD",), root, source_root=source_root
            )

            self.assertEqual(change.installed, ())
            self.assertEqual(
                change.skipped,
                (root / ".local/bin/FreeCAD",),
            )


if __name__ == "__main__":
    unittest.main()
