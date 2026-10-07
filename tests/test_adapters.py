# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import unittest

from nodephell.adapters import (
    adapter_for_executable,
    discover_adapters,
    load_adapter,
)
from nodephell.errors import NodePhellError
from nodephell.metadata import HostRequirement


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


if __name__ == "__main__":
    unittest.main()
