# SPDX-License-Identifier: GPL-3.0-only

from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

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
    @patch("nodephell.cli.lock_project")
    def test_routes_lock_and_update_commands(self, lock_project) -> None:
        lock_project.return_value = Mock(
            path=Path("/projects/example/pylock.toml"),
            runtime=Mock(identifier="cpython-runtime"),
        )
        output = io.StringIO()

        with redirect_stdout(output):
            statuses = (
                main(["lock", "/projects/example"]),
                main(["update", "/projects/example"]),
            )

        self.assertEqual(statuses, (0, 0))
        self.assertEqual(lock_project.call_args_list[0].kwargs["update"], False)
        self.assertEqual(lock_project.call_args_list[1].kwargs["update"], True)
        self.assertIn("Created", output.getvalue())
        self.assertIn("Updated", output.getvalue())

    @patch("nodephell.cli.move_project_reference")
    @patch("nodephell.cli.unregister_host")
    @patch("nodephell.cli.unregister_runtime")
    @patch("nodephell.cli.remove_project_reference")
    def test_routes_removal_commands(
        self,
        remove_project,
        remove_runtime,
        remove_host,
        move_project,
    ) -> None:
        project = Path("/projects/example")
        moved = Path("/projects/moved")
        python = Path("/runtimes/python3")
        host = Path("/applications/freecadcmd")
        remove_project.return_value = project
        move_project.return_value = Mock(project_root=moved)
        remove_runtime.return_value = Mock(
            identifier="cpython-runtime",
            executable=python,
        )
        remove_host.return_value = Mock(
            identifier="freecad-host",
            executable=host,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            statuses = (
                main(["project", "remove", str(project)]),
                main(["project", "move", str(project), str(moved)]),
                main(["runtime", "remove", str(python)]),
                main(["host", "remove", str(host)]),
            )

        self.assertEqual(statuses, (0, 0, 0, 0))
        remove_project.assert_called_once_with(project)
        move_project.assert_called_once_with(project, moved)
        remove_runtime.assert_called_once_with(python)
        remove_host.assert_called_once_with(host)
        self.assertIn("Files were not deleted", output.getvalue())

    @patch("nodephell.cli.inspect_project_references", return_value=((), ()))
    def test_project_list_reports_empty_registry(self, inspect) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["project", "list"])

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue(), "No projects are registered.\n")

    @patch("nodephell.cli.reference_problem")
    @patch("nodephell.cli.inspect_project_references")
    def test_project_list_explains_project_states(
        self,
        inspect,
        problem,
    ) -> None:
        current = project_reference("current", 1)
        changed = project_reference("changed", 2)
        unavailable = project_reference("unavailable", 3)
        inspect.return_value = ((current, changed, unavailable), ())
        problem.side_effect = (
            None,
            ("project lock changed; run 'nodephell install' in that project", False),
            ("registered project location is unavailable", False),
        )
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["project", "list"])

        self.assertEqual(status, 0)
        text = output.getvalue()
        self.assertIn("current\t/projects/current\t1 shared release", text)
        self.assertIn("changed\t/projects/changed\t2 shared releases", text)
        self.assertIn(
            "unavailable\t/projects/unavailable\t3 shared releases", text
        )
        self.assertIn("registered project location is unavailable", text)


if __name__ == "__main__":
    unittest.main()
