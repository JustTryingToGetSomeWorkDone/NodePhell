# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.errors import NodePhellError
from nodephell.launchers import (
    install_launchers,
    install_package_launchers,
    uninstall_launchers,
)


class LauncherTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
