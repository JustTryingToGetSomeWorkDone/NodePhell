# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.errors import NodePhellError
from nodephell.metadata import Project
from nodephell.references import (
    _project_key,
    move_project_reference,
    project_registry,
    record_project_reference,
    remove_project_reference,
)
from nodephell.runtime import Runtime
from nodephell.store import PackageSelection


class ReferenceTests(unittest.TestCase):
    def test_moves_registration_when_lock_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            old = home / "old"
            new = home / "new"
            old.mkdir()
            lock = old / "pylock.toml"
            lock.write_text('lock-version = "1.0"\n', encoding="utf-8")
            runtime = Runtime(
                "cpython", "3.13.1", Path("/python"), "abi", "linux"
            )
            original = record_project_reference(
                Project(old, lock, None, ()), runtime, PackageSelection(()), home
            )
            old.rename(new)

            moved = move_project_reference(old, new, home)

            self.assertEqual(moved.project_root, new.resolve())
            self.assertFalse(original.manifest.exists())
            self.assertTrue(moved.manifest.is_file())

    def test_refuses_move_when_lock_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            old = home / "old"
            new = home / "new"
            old.mkdir()
            lock = old / "pylock.toml"
            lock.write_text('lock-version = "1.0"\n', encoding="utf-8")
            runtime = Runtime(
                "cpython", "3.13.1", Path("/python"), "abi", "linux"
            )
            original = record_project_reference(
                Project(old, lock, None, ()), runtime, PackageSelection(()), home
            )
            old.rename(new)
            (new / "pylock.toml").write_text(
                'lock-version = "1.0"\n# changed\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(NodePhellError, "lock does not match"):
                move_project_reference(old, new, home)

            self.assertTrue(original.manifest.is_file())

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
