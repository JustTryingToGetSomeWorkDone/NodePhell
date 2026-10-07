# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

_PLUGIN_SOURCE = Path(__file__).resolve().parents[1] / "plugins/freecad/src"
os.environ["NODEPHELL_ADAPTER_PATH"] = str(_PLUGIN_SOURCE)
sys.path.insert(0, str(_PLUGIN_SOURCE))

from nodephell.adapters import (  # noqa: E402
    adapter_for_executable,
    discover_adapters,
    load_adapter,
)
from nodephell.errors import NodePhellError  # noqa: E402
from nodephell.metadata import HostRequirement  # noqa: E402
from freecad import FreeCADAdapter  # noqa: E402


class ExampleAdapter(FreeCADAdapter):
    kind = "example"
    display_name = "Example Host"


class AdapterTests(unittest.TestCase):
    def test_discovers_freecad_reference_adapter(self) -> None:
        adapters = discover_adapters()

        self.assertIn("freecad", {adapter.kind for adapter in adapters})
        self.assertEqual(load_adapter("freecad").display_name, "FreeCAD")

    def test_infers_adapter_from_executable_name(self) -> None:
        adapter = adapter_for_executable(Path("/opt/freecad/bin/FreeCADCmd"))

        self.assertEqual(adapter.kind, "freecad")

    def test_reports_unknown_adapter(self) -> None:
        with self.assertRaisesRegex(
            NodePhellError,
            "no embedded-host adapter is installed",
        ):
            load_adapter("example")

    def test_metadata_accepts_generic_host_kind(self) -> None:
        requirement = HostRequirement("example", ">=1")

        self.assertEqual(requirement.kind, "example")

    def test_loads_dropin_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "freecad.py").write_text(
                "from freecad import FreeCADAdapter\n"
                "class VendorAdapter(FreeCADAdapter):\n"
                "    display_name = 'Vendor FreeCAD'\n"
                "ADAPTER = VendorAdapter()\n",
                encoding="utf-8",
            )
            environment = {
                "NODEPHELL_ADAPTER_PATH": str(directory),
                "XDG_DATA_HOME": str(directory / "empty-data"),
            }

            with patch.dict(os.environ, environment):
                adapter = load_adapter("freecad")

            self.assertEqual(adapter.display_name, "Vendor FreeCAD")

    @patch("nodephell.adapters._adapter_entry_points")
    def test_loads_packaged_entry_point_adapter(self, entry_points) -> None:
        entry_point = Mock()
        entry_point.load.return_value = ExampleAdapter()
        entry_points.return_value = (entry_point,)

        adapter = load_adapter("example")

        self.assertEqual(adapter.display_name, "Example Host")


if __name__ == "__main__":
    unittest.main()
