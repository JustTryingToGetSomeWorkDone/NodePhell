# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import sys
import tempfile
import unittest

from nodephell.errors import NodePhellError
from nodephell.initializer import initialize_project
from nodephell.metadata import load_project_definition


class InitializerTests(unittest.TestCase):
    def test_blank_answers_use_defaults_and_blank_dependency_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "drawing-tool"
            root.mkdir()
            answers = iter(("", "", "", "requests", "", "", ""))

            path = initialize_project(root, lambda _: next(answers), lambda _: None)
            project = load_project_definition(root)

            self.assertEqual(path, root / "pyproject.toml")
            text = path.read_text(encoding="utf-8")
            self.assertIn('name = "drawing-tool"', text)
            self.assertIn('version = "0.1.0"', text)
            self.assertIn(
                (
                    f'requires-python = ">={sys.version_info.major}.'
                    f'{sys.version_info.minor},<{sys.version_info.major}.'
                    f'{sys.version_info.minor + 1}"'
                ),
                text,
            )
            self.assertEqual(
                tuple(requirement.text for requirement in project.requirements),
                ("requests",),
            )

    def test_dependency_version_accepts_number_or_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            answers = iter(
                (
                    "demo",
                    "1.2.0",
                    ">=3.12,<3.14",
                    "requests",
                    "2.32.5",
                    "pillow",
                    ">=10,<12",
                    "",
                    "yes",
                )
            )

            initialize_project(root, lambda _: next(answers), lambda _: None)
            project = load_project_definition(root)

        self.assertEqual(project.requires_python, ">=3.12,<3.14")
        self.assertEqual(
            tuple(requirement.text for requirement in project.requirements),
            ("requests==2.32.5", "pillow>=10,<12"),
        )

    def test_refuses_to_replace_existing_project_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "pyproject.toml"
            path.write_text('[project]\nname = "existing"\n', encoding="utf-8")

            with self.assertRaisesRegex(NodePhellError, "already exists"):
                initialize_project(root, lambda _: self.fail("prompted"))

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '[project]\nname = "existing"\n',
            )


if __name__ == "__main__":
    unittest.main()
