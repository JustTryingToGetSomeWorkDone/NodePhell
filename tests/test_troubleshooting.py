# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nodephell.errors import NodePhellError
from nodephell.troubleshooting import (
    suggested_project_commands,
    troubleshoot_project,
)


class TroubleshootingTests(unittest.TestCase):
    def test_suggests_standard_and_poetry_project_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"
requires-python = ">=3.11"

[project.scripts]
demo = "demo.cli:main"

[tool.poetry.scripts]
legacy-demo = "demo.legacy:main"
''',
                encoding="utf-8",
            )

            commands = suggested_project_commands(root)

        self.assertEqual(commands, ("demo", "legacy-demo"))

    @patch("nodephell.troubleshooting.install_project")
    @patch("nodephell.troubleshooting.lock_project")
    @patch("nodephell.troubleshooting.load_project")
    @patch("nodephell.troubleshooting.load_project_definition")
    @patch(
        "nodephell.troubleshooting.lock_matches_project_definition",
        return_value=True,
    )
    def test_restores_original_lock_when_working_trial_is_not_kept(
        self,
        lock_matches,
        load_definition,
        load_project,
        lock_project_mock,
        install_project_mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path = root / "pylock.toml"
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            lock_path.write_text("original\n", encoding="utf-8")
            load_definition.return_value = Mock(requires_python=">=3.8,<4")
            load_project.return_value = Mock(
                runtime_artifact=Mock(version="3.15.0")
            )
            trial_runtime = Mock(version="3.8.20")

            def write_trial(*args, **kwargs):
                lock_path.write_text("trial\n", encoding="utf-8")
                return Mock(runtime=trial_runtime)

            lock_project_mock.side_effect = write_trial
            runner = Mock(side_effect=(1, 0))

            result = troubleshoot_project(
                ("demo", "--help"),
                root,
                runner=runner,
                keep_trial=lambda runtime: False,
            )

            self.assertEqual(lock_path.read_text(encoding="utf-8"), "original\n")
            self.assertFalse(
                (root / "pylock.toml.nodephell-troubleshoot-backup").exists()
            )

        self.assertEqual(result.trial_status, 0)
        self.assertFalse(result.kept)
        self.assertEqual(install_project_mock.call_count, 2)
        self.assertEqual(
            lock_project_mock.call_args.kwargs["runtime_requirement"],
            ">=3.8,<4,<3.9",
        )

    @patch("nodephell.troubleshooting.install_project")
    @patch("nodephell.troubleshooting.lock_project")
    @patch("nodephell.troubleshooting.load_project")
    @patch("nodephell.troubleshooting.load_project_definition")
    @patch(
        "nodephell.troubleshooting.lock_matches_project_definition",
        return_value=True,
    )
    def test_keeps_working_trial_only_after_confirmation(
        self,
        lock_matches,
        load_definition,
        load_project,
        lock_project_mock,
        install_project_mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path = root / "pylock.toml"
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            lock_path.write_text("original\n", encoding="utf-8")
            load_definition.return_value = Mock(requires_python=">=3.8,<4")
            load_project.return_value = Mock(
                runtime_artifact=Mock(version="3.15.0")
            )
            trial_runtime = Mock(version="3.8.20")

            def write_trial(*args, **kwargs):
                lock_path.write_text("trial\n", encoding="utf-8")
                return Mock(runtime=trial_runtime)

            lock_project_mock.side_effect = write_trial

            result = troubleshoot_project(
                ("demo", "--help"),
                root,
                runner=Mock(side_effect=(1, 0)),
                keep_trial=lambda runtime: runtime is trial_runtime,
            )

            self.assertEqual(lock_path.read_text(encoding="utf-8"), "trial\n")
            self.assertFalse(
                (root / "pylock.toml.nodephell-troubleshoot-backup").exists()
            )

        self.assertTrue(result.kept)
        install_project_mock.assert_called_once()

    @patch("nodephell.troubleshooting.install_project")
    @patch("nodephell.troubleshooting.lock_project")
    @patch("nodephell.troubleshooting.load_project")
    @patch("nodephell.troubleshooting.load_project_definition")
    @patch(
        "nodephell.troubleshooting.lock_matches_project_definition",
        return_value=True,
    )
    def test_missing_floor_runtime_restores_lock_and_names_next_action(
        self,
        lock_matches,
        load_definition,
        load_project,
        lock_project_mock,
        install_project_mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path = root / "pylock.toml"
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            lock_path.write_text("original\n", encoding="utf-8")
            load_definition.return_value = Mock(requires_python=">=3.8,<4")
            load_project.return_value = Mock(
                runtime_artifact=Mock(version="3.15.0")
            )
            lock_project_mock.side_effect = NodePhellError(
                "no downloadable CPython runtime satisfies '>=3.8,<3.9'"
            )

            with self.assertRaises(NodePhellError) as raised:
                troubleshoot_project(
                    ("demo", "--help"),
                    root,
                    runner=Mock(return_value=1),
                )

            self.assertEqual(lock_path.read_text(encoding="utf-8"), "original\n")

        self.assertIn("next supported minor line", raised.exception.guidance)
        install_project_mock.assert_called_once()
