# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.references import (
    _project_key,
    project_registry,
    remove_project_reference,
)


class ReferenceTests(unittest.TestCase):
    def test_removes_only_project_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = home / "work" / "example"
            project.mkdir(parents=True)
            lock = project / "pylock.toml"
            lock.write_text('lock-version = "1.0"\n', encoding="utf-8")
            registry = project_registry(home)
            registry.mkdir(parents=True)
            manifest = registry / (_project_key(project.resolve()) + ".json")
            manifest.write_text("{}\n", encoding="utf-8")

            removed = remove_project_reference(project, home)

            self.assertEqual(removed, project.resolve())
            self.assertFalse(manifest.exists())
            self.assertTrue(project.is_dir())
            self.assertTrue(lock.is_file())


if __name__ == "__main__":
    unittest.main()
