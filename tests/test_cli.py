# SPDX-License-Identifier: GPL-3.0-only

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from nodephell.cli import main
from nodephell.errors import NodePhellError
from nodephell.launcher import Resolution
from nodephell.metadata import PackagePin, Project
from nodephell.references import ProjectReference
from nodephell.runtime import Runtime
from nodephell.store import PackageSelection


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
    @patch("nodephell.cli.resolve_host")
    def test_host_resolve_explains_external_package_selection(
        self,
        resolve_host,
    ) -> None:
        package = PackagePin("demo", "1.2.3")
        project = Project(
            Path("/projects/demo"),
            Path("/projects/demo/pylock.toml"),
            None,
            (package,),
        )
        runtime = Runtime(
            "cpython",
            "3.13.1",
            Path("/runtimes/python3"),
            "cpython-313-x86_64-linux-gnu",
            "linux-x86_64",
        )
        selection = PackageSelection(
            (Path("/packages/composed"),), external_packages=(package,)
        )
        host = Mock(
            kind="freecad",
            version="1.1.3",
            executable=Path("/applications/FreeCADCmd"),
            runtime=runtime,
            package_roots=(Path("/applications/packages"),),
        )
        resolve_host.return_value = Mock(
            project=Resolution(runtime, project, selection),
            host=host,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["host", "resolve"])

        self.assertEqual(status, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["selected_host"]["kind"], "freecad")
        self.assertEqual(
            data["package_selections"],
            [
                {
                    "name": "demo",
                    "version": "1.2.3",
                    "provider": "external-host",
                    "path": None,
                }
            ],
        )

    @patch("nodephell.cli.validate_store")
    @patch("nodephell.cli.inspect_project_references", return_value=((), ()))
    @patch("nodephell.cli.load_hosts", return_value=())
    @patch("nodephell.cli.load_registry", return_value=())
    @patch("nodephell.cli.discover_adapters", return_value=())
    @patch("nodephell.cli.path_problem", return_value=None)
    def test_doctor_reports_healthy_system(
        self,
        path_problem,
        discover_adapters,
        load_registry,
        load_hosts,
        inspect_references,
        validate_store,
    ) -> None:
        validate_store.return_value = Mock(checked_releases=0, issues=())
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["doctor"])

        self.assertEqual(status, 0)
        self.assertIn("Doctor found no problems.", output.getvalue())

    @patch("nodephell.cli.validate_store")
    @patch("nodephell.cli.inspect_project_references", return_value=((), ()))
    @patch("nodephell.cli.load_hosts", return_value=())
    @patch("nodephell.cli.load_registry", side_effect=NodePhellError("invalid data"))
    @patch("nodephell.cli.discover_adapters", return_value=())
    @patch("nodephell.cli.path_problem", return_value="add /commands to PATH")
    def test_doctor_reports_problems(
        self,
        path_problem,
        discover_adapters,
        load_registry,
        load_hosts,
        inspect_references,
        validate_store,
    ) -> None:
        validate_store.return_value = Mock(checked_releases=0, issues=())
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(["doctor"])

        self.assertEqual(status, 1)
        text = output.getvalue()
        self.assertIn("Problem: launchers: add /commands to PATH", text)
        self.assertIn("Problem: runtimes registry: invalid data", text)
        self.assertIn("Doctor found 2 problems.", text)

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
