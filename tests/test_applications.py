# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nodephell.applications import (
    Application,
    ApplicationCandidate,
    ApplicationPlan,
    DeclaredApplicationPlan,
    app_main,
    apply_application,
    discover_application_candidates,
    get_application,
    install_declared_application,
    load_applications,
    move_application_projects,
    plan_application,
    plan_declared_application,
    remove_application,
)
from nodephell.errors import NodePhellError
from nodephell.host import EmbeddedHost
from nodephell.launchers import LauncherChange
from nodephell.plugins import PluginChange
from nodephell.runtime import Runtime


def host(executable: Path) -> EmbeddedHost:
    runtime = Runtime(
        "cpython",
        "3.13.15",
        executable,
        "cpython-313-x86_64-linux-gnu",
        "linux-x86_64",
    )
    return EmbeddedHost("freecad", "27.1.0", executable, runtime)


def project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0"\n',
        encoding="utf-8",
    )


class ApplicationTests(unittest.TestCase):
    @patch("nodephell.applications.discover_adapters")
    def test_discovers_only_adapter_declared_project_paths(self, adapters) -> None:
        adapter = Mock(
            project_search_patterns=("build/*/bin/ExampleCmd",),
            display_name="Example",
        )
        adapter.accepts_executable.side_effect = (
            lambda path: path.name == "ExampleCmd"
        )
        adapters.return_value = (adapter,)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = root / "build/release/bin/ExampleCmd"
            expected.parent.mkdir(parents=True)
            expected.touch()
            unrelated = root / "unrelated/ExampleCmd"
            unrelated.parent.mkdir()
            unrelated.touch()

            candidates = discover_application_candidates(root)

        self.assertEqual([item.executable for item in candidates], [expected])

    @patch("nodephell.applications.check_application_launcher")
    @patch("nodephell.applications.probe_host")
    @patch("nodephell.applications.adapter_for_executable")
    def test_plans_adapter_default_launcher(
        self,
        adapter_for_executable,
        probe_host,
        check_launcher,
    ) -> None:
        adapter_for_executable.return_value = Mock(
            kind="freecad",
            launcher_name="FreeCAD",
            launch_mode="gui",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project(root)
            executable = root / "build/bin/FreeCADCmd"
            executable.parent.mkdir(parents=True)
            executable.touch()
            probe_host.return_value = host(executable.resolve())
            check_launcher.return_value = root / ".local/bin/FreeCAD"

            plan = plan_application(executable, root, user_home=root)

        self.assertEqual(plan.application.name, "FreeCAD")
        self.assertEqual(plan.application.project_root, root)
        self.assertTrue(plan.project_update)

    @patch("nodephell.applications.plan_application")
    @patch("nodephell.applications.discover_application_candidates")
    @patch("nodephell.applications.add_plugin")
    def test_plans_project_declared_plugin_and_discovered_executable(
        self,
        add_plugin,
        discover,
        plan_application,
    ) -> None:
        adapter = Mock(kind="freecad", display_name="FreeCAD")
        planned = Mock(application=Mock(kind="freecad"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "freecad"

[tool.nodephell.application]
adapter = "nodephell-plugins/freecad"
''',
                encoding="utf-8",
            )
            executable = root / "build/bin/FreeCADCmd"
            add_plugin.return_value = PluginChange(
                adapter,
                root / ".local/share/nodephell/adapters/freecad",
                True,
            )
            discover.return_value = (
                ApplicationCandidate(adapter, executable),
            )
            plan_application.return_value = planned

            result = plan_declared_application(root, root)

        self.assertEqual(
            result,
            DeclaredApplicationPlan(add_plugin.return_value, planned),
        )
        add_plugin.assert_called_once_with(
            root / "nodephell-plugins/freecad",
            root,
        )
        plan_application.assert_called_once_with(
            executable,
            root,
            None,
            root,
            replace=True,
        )

    @patch("nodephell.applications._record_application")
    @patch("nodephell.applications.install_project")
    @patch("nodephell.applications.register_probed_host")
    def test_install_uses_declared_host_without_updating_lock(
        self,
        register_host,
        install_project,
        record_application,
    ) -> None:
        application = Application(
            "FreeCAD",
            "freecad",
            Path("/projects/freecad"),
            Path("/projects/freecad/FreeCADCmd"),
            "gui",
        )
        selected_host = host(application.executable)
        plan = ApplicationPlan(
            application,
            selected_host,
            Path("/commands/FreeCAD"),
            False,
        )
        declared = DeclaredApplicationPlan(Mock(), plan)
        installation = Mock()
        launcher = LauncherChange(installed=(Path("/commands/FreeCAD"),))
        install_project.return_value = installation
        record_application.return_value = launcher

        result = install_declared_application(declared)

        register_host.assert_called_once_with(selected_host, None)
        install_project.assert_called_once_with(
            application.project_root,
            None,
            None,
        )
        self.assertEqual(result.installation, installation)
        self.assertEqual(result.launcher, launcher)

    @patch("nodephell.applications.install_application_launcher")
    @patch("nodephell.applications.sync_project")
    @patch("nodephell.applications.register_probed_host")
    def test_applies_host_configuration_and_records_application(
        self,
        register_host,
        sync_project,
        install_launcher,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project(root)
            executable = root / "FreeCADCmd"
            executable.touch()
            selected_host = host(executable.resolve())
            application = Application(
                "FreeCAD", "freecad", root, executable.resolve(), "gui"
            )
            plan = ApplicationPlan(
                application,
                selected_host,
                root / ".local/bin/FreeCAD",
                True,
            )
            sync_result = Mock()
            sync_project.return_value = sync_result
            launcher = LauncherChange(installed=(root / ".local/bin/FreeCAD",))
            install_launcher.return_value = launcher

            result = apply_application(plan, root)

            text = (root / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn("[tool.nodephell.host]", text)
            self.assertIn('kind = "freecad"', text)
            self.assertIn('requires = "==27.1.0"', text)
            self.assertEqual(get_application("FreeCAD", root), application)
            self.assertEqual(result.sync, sync_result)
            register_host.assert_called_once_with(selected_host, root)

    @patch("nodephell.applications.sync_project")
    @patch("nodephell.applications.register_probed_host")
    def test_failed_sync_restores_project_definition(
        self,
        register_host,
        sync_project,
    ) -> None:
        sync_project.side_effect = NodePhellError("resolution failed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project(root)
            original = (root / "pyproject.toml").read_bytes()
            executable = root / "FreeCADCmd"
            executable.touch()
            selected_host = host(executable.resolve())
            plan = ApplicationPlan(
                Application(
                    "FreeCAD", "freecad", root, executable.resolve(), "gui"
                ),
                selected_host,
                root / ".local/bin/FreeCAD",
                True,
            )

            with self.assertRaisesRegex(NodePhellError, "resolution failed"):
                apply_application(plan, root)

            self.assertEqual((root / "pyproject.toml").read_bytes(), original)
            self.assertFalse((root / "pylock.toml").exists())
            self.assertEqual(load_applications(root), ())

    @patch("nodephell.applications.remove_application_launcher")
    def test_removes_only_application_binding_and_launcher(self, remove) -> None:
        remove.return_value = LauncherChange(removed=(Path("/commands/FreeCAD"),))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project(root)
            executable = root / "FreeCADCmd"
            executable.touch()
            application = Application(
                "FreeCAD", "freecad", root, executable.resolve(), "gui"
            )
            from nodephell.applications import _save_applications

            _save_applications((application,), root)

            removed, launcher = remove_application("FreeCAD", root)

            self.assertEqual(removed, application)
            self.assertEqual(launcher.removed, (Path("/commands/FreeCAD"),))
            self.assertEqual(load_applications(root), ())

    def test_project_move_updates_bound_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            old = home / "old"
            new = home / "new"
            executable = old / "build/bin/FreeCADCmd"
            application = Application(
                "FreeCAD", "freecad", old, executable, "gui"
            )
            from nodephell.applications import _save_applications

            _save_applications((application,), home)

            changed = move_application_projects(old, new, home)
            moved = get_application("FreeCAD", home)

            self.assertEqual(changed, 1)
            self.assertEqual(moved.project_root, new)
            self.assertEqual(
                moved.executable,
                new / "build/bin/FreeCADCmd",
            )

    @patch("nodephell.applications.execute_host_gui")
    @patch("nodephell.applications.resolve_host")
    @patch("nodephell.applications._application_named")
    def test_application_launcher_uses_bound_project_and_host(
        self,
        application_named,
        resolve_host,
        execute_gui,
    ) -> None:
        application = Application(
            "FreeCAD",
            "freecad",
            Path("/projects/freecad"),
            Path("/hosts/FreeCADCmd"),
            "gui",
        )
        application_named.return_value = application
        resolution = Mock()
        resolution.host.kind = "freecad"
        resolve_host.return_value = resolution
        execute_gui.side_effect = SystemExit(0)

        with self.assertRaises(SystemExit):
            app_main("FreeCAD", ["model.FCStd"])

        resolve_host.assert_called_once_with(
            [],
            cwd=application.project_root,
            host_executable=application.executable,
        )
        execute_gui.assert_called_once_with(["model.FCStd"], resolution)


if __name__ == "__main__":
    unittest.main()
