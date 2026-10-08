# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodephell.plugins import (
    add_plugin,
    remove_plugin,
    scan_plugins,
    user_plugin_directory,
)


_FREECAD_PLUGIN = Path(__file__).resolve().parents[1] / "plugins/freecad"


class PluginTests(unittest.TestCase):
    def test_adds_reuses_and_removes_local_plugin_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            environment = {
                "XDG_DATA_HOME": str(home / ".local/share"),
                "NODEPHELL_ADAPTER_PATH": "",
            }
            with patch.dict(os.environ, environment, clear=False):
                first = add_plugin(_FREECAD_PLUGIN, home)
                second = add_plugin(_FREECAD_PLUGIN, home)
                removed = remove_plugin("freecad", home)

            self.assertTrue(first.installed)
            self.assertFalse(second.installed)
            self.assertEqual(first.adapter.kind, "freecad")
            self.assertEqual(first.path, second.path)
            self.assertEqual(removed, first.path)
            self.assertFalse(first.path.exists())
            self.assertTrue(_FREECAD_PLUGIN.is_dir())

    def test_scan_adds_new_plugins_and_reuses_installed_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            dropins = user_plugin_directory(home)
            dropins.mkdir(parents=True)
            (dropins / "freecad-adapter").symlink_to(
                _FREECAD_PLUGIN,
                target_is_directory=True,
            )
            (dropins / "broken-adapter").mkdir()
            environment = {
                "XDG_DATA_HOME": str(home / ".local/share"),
                "NODEPHELL_ADAPTER_PATH": "",
            }
            with patch.dict(os.environ, environment, clear=False):
                first = scan_plugins(user_home=home)
                second = scan_plugins(user_home=home)

            self.assertEqual(first.directory, dropins)
            self.assertEqual(len(first.changes), 1)
            self.assertTrue(first.changes[0].installed)
            self.assertEqual(first.changes[0].adapter.kind, "freecad")
            self.assertEqual(len(first.issues), 1)
            self.assertEqual(first.issues[0].source, dropins / "broken-adapter")
            self.assertEqual(len(second.changes), 1)
            self.assertFalse(second.changes[0].installed)
            self.assertEqual(len(second.issues), 1)


if __name__ == "__main__":
    unittest.main()
