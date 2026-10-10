# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nodephell.errors import NodePhellError
from nodephell.metadata import (
    load_project_definition,
    project_definition_fingerprint,
)
from nodephell.project_options import inspect_project_options, update_project_options
from nodephell.references import ProjectReference


def reference(
    manifest: Path,
    root: Path,
    releases: tuple[Path, ...],
) -> ProjectReference:
    return ProjectReference(
        manifest,
        root.resolve(),
        root / "pylock.toml",
        "a" * 64,
        ("cpython", "3.13.16", "cpython-313-x86_64-linux-gnu", "linux"),
        releases,
        (),
    )


class ProjectOptionTests(unittest.TestCase):
    @patch("nodephell.project_options.lock_project")
    @patch("nodephell.project_options.install_project")
    @patch("nodephell.project_options.inspect_project_references")
    def test_empty_extra_updates_selection_without_resolving(
        self,
        inspect_references,
        install_project,
        lock_project,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "demo"
            root.mkdir()
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"

[project.optional-dependencies]
data = []
''',
                encoding="utf-8",
            )
            fingerprint = project_definition_fingerprint(
                load_project_definition(root)
            )
            (root / "pylock.toml").write_text(
                f'''lock-version = "1.0"
created-by = "nodephell"
packages = []

[tool.nodephell.source]
fingerprint = "{fingerprint}"
''',
                encoding="utf-8",
            )
            inspect_references.return_value = ((), ())
            runtime = Mock()
            install_project.return_value = Mock(runtime=runtime)
            progress: list[str] = []

            result = update_project_options(
                root,
                ("data",),
                (),
                home,
                progress.append,
            )

        lock_project.assert_not_called()
        self.assertEqual(result.project.selected_extras, ("data",))
        self.assertEqual(result.lock.runtime, runtime)
        self.assertIn("does not affect dependencies", progress[0])

    def test_stale_locked_option_remains_visible_for_deselection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )
            (root / "pylock.toml").write_text(
                '''lock-version = "1.0"
created-by = "nodephell"
packages = []

[tool.nodephell.selection]
extras = ["removed-feature"]
groups = []
''',
                encoding="utf-8",
            )

            project = inspect_project_options(root)

        self.assertEqual(project.selected_extras, ("removed-feature",))
        self.assertEqual(project.optional_dependencies[0].name, "removed-feature")
        self.assertFalse(project.optional_dependencies[0].available)

    @patch("nodephell.project_options.inspect_project_options")
    @patch("nodephell.project_options.install_project")
    @patch("nodephell.project_options.lock_project")
    @patch("nodephell.project_options.inspect_project_references")
    def test_classifies_deselected_releases_by_other_project_use(
        self,
        inspect_references,
        lock_project,
        install_project,
        inspect_options,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "demo"
            root.mkdir()
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"

[project.optional-dependencies]
full = ["shared", "unused"]
''',
                encoding="utf-8",
            )
            lock_path = root / "pylock.toml"
            lock_path.write_text(
                'lock-version = "1.0"\ncreated-by = "nodephell"\n'
                'packages = []\n',
                encoding="utf-8",
            )
            manifest = root / "project-reference.json"
            manifest.write_text("{}\n", encoding="utf-8")
            shared = Path("/store/packages/shared/1.0/artifact/hash")
            unused = Path("/store/packages/unused/1.0/artifact/hash")
            old = reference(manifest, root, (shared, unused))
            current = reference(manifest, root, ())
            other_root = root.parent / "other"
            other = reference(
                root / "other-reference.json",
                other_root,
                (shared,),
            )
            inspect_references.side_effect = (
                ((old,), ()),
                ((current, other), ()),
            )
            lock_project.return_value = Mock(path=lock_path, runtime=Mock())
            install_project.return_value = Mock()
            inspect_options.return_value = Mock()

            result = update_project_options(root, (), ())

        self.assertEqual(result.used_elsewhere[0].path, shared)
        self.assertEqual(result.used_elsewhere[0].project_count, 1)
        self.assertEqual(result.unused_releases, (unused,))
        self.assertEqual(result.uncertain_releases, ())
        lock_project.assert_called_once_with(
            root,
            None,
            None,
            update=True,
            selected_extras=(),
            selected_groups=(),
        )

    @patch("nodephell.project_options.install_project")
    @patch("nodephell.project_options.lock_project")
    @patch("nodephell.project_options.inspect_project_references")
    def test_failed_install_restores_previous_lock(
        self,
        inspect_references,
        lock_project,
        install_project,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"

[project.optional-dependencies]
full = ["helper"]
''',
                encoding="utf-8",
            )
            lock = root / "pylock.toml"
            original = (
                b'lock-version = "1.0"\ncreated-by = "nodephell"\n'
                b'packages = []\n'
            )
            lock.write_bytes(original)
            inspect_references.return_value = ((), ())

            def replace_lock(*args, **kwargs):
                lock.write_text("replacement\n", encoding="utf-8")
                return Mock(path=lock, runtime=Mock())

            lock_project.side_effect = replace_lock
            install_project.side_effect = NodePhellError("installation failed")

            with self.assertRaisesRegex(NodePhellError, "installation failed"):
                update_project_options(root, ("full",), ())

            self.assertEqual(lock.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
