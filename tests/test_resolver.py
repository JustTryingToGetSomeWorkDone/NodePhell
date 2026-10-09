# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.metadata import (
    HostArtifact,
    HostRequirement,
    PackageArtifact,
    PackagePin,
    PackageRequirement,
    Project,
    RuntimeArtifact,
    lock_matches_project_definition,
    load_project,
    load_project_definition,
    project_definition_fingerprint,
)
from nodephell.resolver import (
    _external_requirement_guidance,
    resolve_and_write_lock,
    rewrite_lock_selection,
)
from nodephell.runtime import Runtime


class ResolverTests(unittest.TestCase):
    PACKAGE_SHA256 = "c" * 64

    def test_explains_external_program_required_by_python_build(self) -> None:
        guidance = _external_requirement_guidance(
            "Error: nativebridge cannot be built without toolx in the PATH"
        )

        self.assertIsNotNone(guidance)
        assert guidance is not None
        self.assertIn("Python package nativebridge", guidance)
        self.assertIn("external program named 'toolx'", guidance)
        self.assertIn("separate system software", guidance)
        self.assertIn('run "nodephell options" again', guidance)
        self.assertIn("attempt adding one package at a time", guidance)

    def test_rewrites_dependency_neutral_option_without_replacing_packages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"

[project.optional-dependencies]
data = []
''',
                encoding="utf-8",
            )
            definition = load_project_definition(root)
            fingerprint = project_definition_fingerprint(definition)
            lock = root / "pylock.toml"
            lock.write_text(
                f'''lock-version = "1.0"

[tool.nodephell.source]
fingerprint = "{fingerprint}"

[[packages]]
name = "demo-dependency"
version = "1.2.3"
''',
                encoding="utf-8",
            )

            rewrite_lock_selection(
                replace(definition, selected_extras=("data",))
            )
            loaded = load_project(root)

            self.assertEqual(loaded.selected_extras, ("data",))
            self.assertEqual(loaded.packages[0].name, "demo-dependency")
            self.assertTrue(lock_matches_project_definition(root))

    @patch("nodephell.resolver.subprocess.run")
    def test_writes_complete_pip_report_to_lock(self, run) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "install": [
                            self._entry("demo", "1.2.3"),
                            self._entry("dependency", "4.5.6"),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                """[project]
name = "demo-project"
version = "0.0.0"
requires-python = ">=3.16.0a0,<3.17"
dependencies = ["demo>=1,<2"]

[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
""",
                encoding="utf-8",
            )
            project = Project(
                root,
                root / "pyproject.toml",
                ">=3.16.0a0,<3.17",
                (),
                host=HostRequirement("freecad", "==1.1.3"),
                requirements=(
                    PackageRequirement(
                        "demo",
                        specifiers=((">=", "1"), ("<", "2")),
                    ),
                ),
            )
            runtime_name = (
                "cpython-3.16.0a0+20261003-x86_64-unknown-linux-gnu-"
                "install_only.tar.gz"
            )
            runtime_artifact = RuntimeArtifact(
                "cpython",
                "3.16.0a0",
                "x86_64-unknown-linux-gnu",
                runtime_name,
                f"https://example.invalid/{runtime_name.replace('+', '%2B')}",
                (("sha256", "f" * 64),),
            )
            runtime = Runtime(
                "cpython",
                "3.16.0a0",
                root / "python3.16",
                "cpython-316-x86_64-linux-gnu",
                "linux-x86_64",
                artifact=runtime_artifact,
            )
            host_name = "FreeCAD_1.1.3-Linux-x86_64-py316.AppImage"
            host_artifact = HostArtifact(
                "freecad",
                "1.1.3",
                "linux-x86_64",
                host_name,
                f"https://example.invalid/{host_name}",
                (("sha256", "e" * 64),),
            )

            lock = resolve_and_write_lock(project, runtime, host_artifact)
            loaded = load_project(root)

            self.assertEqual(lock, root / "pylock.toml")
            self.assertEqual(loaded.runtime_artifact, runtime_artifact)
            self.assertEqual(loaded.host, project.host)
            self.assertEqual(loaded.host_artifact, host_artifact)
            self.assertEqual(
                loaded.packages,
                (
                    PackagePin(
                        "demo",
                        "1.2.3",
                        (self._artifact("demo", "1.2.3"),),
                    ),
                    PackagePin(
                        "dependency", "4.5.6",
                        (self._artifact("dependency", "4.5.6"),),
                    ),
                ),
            )
            command = run.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertIn("--ignore-installed", command)
            self.assertIn("--target", command)
            self.assertNotIn("--no-deps", command)
            self.assertIn("demo>=1,<2", command)
            self.assertIn(
                f'"sha256" = "{self.PACKAGE_SHA256}"',
                lock.read_text(),
            )
            self.assertIn("[tool.nodephell.runtime]", lock.read_text())
            self.assertIn("[tool.nodephell.host]", lock.read_text())
            self.assertIn(
                f'"sha256" = "{host_artifact.sha256}"',
                lock.read_text(),
            )
            self.assertIn(
                f'"sha256" = "{runtime_artifact.sha256}"',
                lock.read_text(),
            )
            self.assertTrue(lock_matches_project_definition(root))

            (root / "pyproject.toml").write_text(
                (
                    '[project]\nname = "demo-project"\nversion = "0.0.0"\n'
                    'requires-python = ">=3.16.0a0,<3.17"\n'
                    'dependencies = ["demo>=1.2,<2"]\n'
                    '\n[tool.nodephell.host]\nkind = "freecad"\n'
                    'requires = "==1.1.3"\n'
                ),
                encoding="utf-8",
            )
            self.assertFalse(lock_matches_project_definition(root))

    @patch("nodephell.resolver.subprocess.run")
    def test_selected_runtime_evaluates_direct_requirement_markers(
        self,
        run,
    ) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps({"version": "1", "install": []}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = Project(
                root,
                root / "pyproject.toml",
                ">=3.15,<3.16",
                (),
                requirements=(
                    PackageRequirement(
                        "tomli",
                        specifiers=((">=", "1.1"),),
                        marker="python_version < '3.11'",
                    ),
                ),
            )
            runtime = Runtime(
                "cpython",
                "3.15.0",
                root / "python3.15",
                "cpython-315-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            lock_text = lock.read_text(encoding="utf-8")

        command = run.call_args.args[0]
        self.assertIn("tomli>=1.1; python_version < '3.11'", command)
        self.assertNotIn("[[packages]]", lock_text)

    @patch("nodephell.resolver.subprocess.run")
    def test_resolves_source_extra_and_included_dependency_group(self, run) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "install": [
                            {
                                "download_info": {"url": root.as_uri()},
                                "is_direct": True,
                                "requested": True,
                                "metadata": {
                                    "name": "demo-project",
                                    "version": "1.0.dev1",
                                },
                            },
                            self._entry("qtpy", "2.4.3"),
                            self._entry("pytest", "9.2.0"),
                            self._entry("ruff", "0.15.0"),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "demo-project"
version = "1.0"

[project.optional-dependencies]
gui = ["qtpy"]

[dependency-groups]
test = ["pytest"]
dev = ["ruff", { include-group = "test" }]
''',
                encoding="utf-8",
            )
            project = replace(
                load_project(root),
                selected_extras=("gui",),
                selected_groups=("dev",),
            )
            runtime = Runtime(
                "cpython",
                "3.13.16",
                root / "python3.13",
                "cpython-313-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            loaded = load_project(root)

            command = run.call_args.args[0]
            self.assertIn(".[gui]", command)
            self.assertIn("pytest", command)
            self.assertIn("ruff", command)
            self.assertEqual(loaded.selected_extras, ("gui",))
            self.assertEqual(loaded.selected_groups, ("dev",))
            self.assertEqual(
                {package.name for package in loaded.packages},
                {"pytest", "qtpy", "ruff"},
            )
            self.assertNotIn("demo-project", {p.name for p in loaded.packages})
            self.assertIn("[tool.nodephell.selection]", lock.read_text())
            self.assertTrue(lock_matches_project_definition(root))

    @staticmethod
    def _entry(name: str, version: str) -> dict:
        filename = f"{name}-{version}-py3-none-any.whl"
        return {
            "download_info": {
                "url": f"https://example.invalid/files/{filename}",
                "archive_info": {
                    "hashes": {"sha256": ResolverTests.PACKAGE_SHA256}
                },
            },
            "metadata": {"name": name, "version": version},
        }

    @staticmethod
    def _artifact(name: str, version: str) -> PackageArtifact:
        filename = f"{name}-{version}-py3-none-any.whl"
        return PackageArtifact(
            "wheel",
            filename,
            f"https://example.invalid/files/{filename}",
            (("sha256", ResolverTests.PACKAGE_SHA256),),
        )


if __name__ == "__main__":
    unittest.main()
