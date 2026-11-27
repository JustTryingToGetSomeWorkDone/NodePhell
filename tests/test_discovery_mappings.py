# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.discovery_mappings import load_discovery_mappings
from nodephell.errors import NodePhellError
from nodephell.metadata import normalize_name


class DiscoveryMappingTests(unittest.TestCase):
    def test_bundled_aliases_have_no_redundant_same_name_entries(self):
        mappings = load_discovery_mappings()
        self.assertEqual(mappings.imports["PIL"], ("Pillow",))
        self.assertEqual(mappings.imports["yaml"], ("PyYAML",))
        for module, candidates in mappings.imports.items():
            self.assertFalse(all(normalize_name(module) == normalize_name(candidate)
                                 for candidate in candidates), module)
        self.assertNotIn("numpy", mappings.imports)

    def test_external_file_overrides_entries_and_is_reread_without_code_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mappings.toml"
            path.write_text('[imports]\ncv2=["opencv-python-headless"]\nextra=["extra-dist"]\n[applications]\ncustomcad=["Part"]\n')
            first = load_discovery_mappings(path)
            self.assertEqual(first.imports["PIL"], ("Pillow",))
            self.assertEqual(first.imports["cv2"], ("opencv-python-headless",))
            self.assertEqual(first.applications["customcad"], ("Part",))
            path.write_text('[imports]\ncv2=["different-choice"]\n')
            second = load_discovery_mappings(path)
            self.assertEqual(second.imports["cv2"], ("different-choice",))
            self.assertNotIn("extra", second.imports)

    def test_invalid_data_and_missing_files_produce_clear_errors(self):
        cases = (
            '[imports',
            'imports = ["not a table"]',
            '[imports]\nPIL="Pillow"',
            '[imports]\nPIL=[]',
            '[imports]\nPIL=[42]',
            '[imports]\n"PIL.Image"=["Pillow"]',
            '[imports]\nPIL=["Pillow>=10"]',
            '[imports]\nPIL=["Pillow[extra]"]',
            '[applications]\nfreecad=["Part.Module"]',
            '[typo]\nPIL=["Pillow"]',
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mappings.toml"
            with self.assertRaisesRegex(NodePhellError, "cannot read discovery mappings"):
                load_discovery_mappings(path)
            for contents in cases:
                with self.subTest(contents=contents):
                    path.write_text(contents)
                    with self.assertRaises(NodePhellError) as raised:
                        load_discovery_mappings(path)
                    self.assertIn(str(path), str(raised.exception))


if __name__ == "__main__":
    unittest.main()
