# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.errors import NodePhellError
from nodephell.metadata import (
    PackagePin,
    discover_project,
    invocation_start,
    load_project,
)


class MetadataTests(unittest.TestCase):
    def test_discovers_project_from_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pylock.toml").write_text(
                'lock-version = "1.0"\npackages = []\n',
                encoding="utf-8",
            )
            script = root / "src" / "tool.py"
            script.parent.mkdir()
            start = invocation_start([str(script)], Path("/"))
            self.assertEqual(discover_project(start), root)

    def test_loads_exact_pylock_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pylock.toml").write_text(
                """lock-version = "1.0"
requires-python = ">=3.13,<3.14"

[[packages]]
name = "example-package"
version = "2.0.post1"
""",
                encoding="utf-8",
            )
            project = load_project(root)
            self.assertEqual(project.requires_python, ">=3.13,<3.14")
            self.assertEqual(project.packages[0].version, "2.0.post1")

    def test_pyproject_requires_exact_package_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\ndependencies = ["demo>=1"]\n',
                encoding="utf-8",
            )
            with self.assertRaises(NodePhellError):
                load_project(root)

    def test_package_pin_rejects_path_components(self) -> None:
        with self.assertRaises(NodePhellError):
            PackagePin("demo", "../../outside")


if __name__ == "__main__":
    unittest.main()
