# SPDX-License-Identifier: GPL-3.0-only

from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from nodephell.cli import main
from nodephell.references import ProjectReference


def project_reference(name: str, release_count: int) -> ProjectReference:
    root = Path("/projects") / name
    return ProjectReference(
        Path(f"/store/projects/{name}.json"),
        root,
        root / "pylock.toml",
        "a" * 64,
        ("cpython", "3.16.0a0", "cpython-316-x86_64-linux-gnu", "linux"),
        tuple(
            Path(f"/store/packages/release-{index}")
            for index in range(release_count)
        ),
        (),
    )


class CliTests(unittest.TestCase):
    @patch("nodephell.cli.inspect_project_references", return_value=((), ()))
    def test_project_list_reports_empty_registry(self, inspect) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["project", "list"])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "No projects are registered.\n")

    @patch("nodephell.cli.reference_problem")
    @patch("nodephell.cli.inspect_project_references")
    def test_project_list_explains_current_and_missing_projects(
        self,
        inspect,
        problem,
    ) -> None:
        current = project_reference("current", 1)
        missing = project_reference("missing", 2)
        inspect.return_value = ((current, missing), ())
        problem.side_effect = (
            None,
            ("registered project directory no longer exists", True),
        )
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["project", "list"])

        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn("current\t/projects/current\t1 shared release", text)
        self.assertIn("missing\t/projects/missing\t2 shared releases", text)
        self.assertIn("registered project directory no longer exists", text)


if __name__ == "__main__":
    unittest.main()
