# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodephell.plugins import add_plugin, remove_plugin


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


if __name__ == "__main__":
    unittest.main()
