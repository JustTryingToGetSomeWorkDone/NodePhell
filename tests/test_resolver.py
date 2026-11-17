# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
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

    @patch("nodephell.resolver.subprocess.run")
    def test_failed_replacement_profile_explains_complete_input(self, run) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["python", "-m", "pip"],
            1,
            stdout="ERROR: No matching distribution found for missing-demo",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )
            profile = root / "requirements-rocm-linux.txt"
            profile.write_text("missing-demo\n", encoding="utf-8")
            project = replace(
                load_project_definition(root),
                requirement_files=(Path(profile.name),),
                replace_requirements=True,
            )
            runtime = Runtime(
                "cpython",
                "3.12.3",
                root / "python3.12",
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
            )

            with self.assertRaises(NodePhellError) as raised:
                resolve_and_write_lock(project, runtime)

        self.assertIsNotNone(raised.exception.guidance)
        assert raised.exception.guidance is not None
        self.assertIn(
            "complete dependency declaration",
            raised.exception.guidance,
        )
        self.assertIn(
            "does not execute separate pip commands",
            raised.exception.guidance,
        )

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
created-by = "nodephell"

[tool.nodephell.source]
fingerprint = "{fingerprint}"

[[packages]]
name = "demo-dependency"
version = "1.2.3"

[[packages.wheels]]
name = "demo_dependency-1.2.3-py3-none-any.whl"
url = "https://example.invalid/demo_dependency-1.2.3-py3-none-any.whl"
hashes = {{ sha256 = "{'a' * 64}" }}
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

            self.assertEqual(lock, root / "nodephell.lock.toml")
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
    def test_recovers_sha256_when_package_index_omits_it(self, run) -> None:
        artifact = "demo-1.2.3-py3-none-any.whl"
        contents = b"resolved artifact without an index hash"

        def fake_pip(command, **kwargs):
            if "--report" in command:
                report = Path(command[command.index("--report") + 1])
                entry = self._entry("demo", "1.2.3")
                entry["download_info"]["archive_info"] = {}
                report.write_text(
                    json.dumps({"version": "1", "install": [entry]}),
                    encoding="utf-8",
                )
            else:
                destination = Path(command[command.index("--dest") + 1])
                (destination / artifact).write_bytes(contents)
            return subprocess.CompletedProcess(command, 0, stdout="")

        run.side_effect = fake_pip
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo-project"\ndependencies = ["demo"]\n',
                encoding="utf-8",
            )
            project = load_project_definition(root)
            runtime = Runtime(
                "cpython",
                "3.12.3",
                root / "python3.12",
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            loaded = load_project(root)
            lock_text = lock.read_text(encoding="utf-8")

        expected = hashlib.sha256(contents).hexdigest()
        self.assertEqual(run.call_count, 2)
        download_command = run.call_args_list[1].args[0]
        self.assertIn("download", download_command)
        self.assertIn("--no-deps", download_command)
        self.assertEqual(
            download_command[-1],
            self._entry("demo", "1.2.3")["download_info"]["url"],
        )
        self.assertEqual(loaded.packages[0].artifacts[0].sha256, expected)
        self.assertIn(expected, lock_text)

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
        self.assertEqual(tomllib.loads(lock_text)["packages"], [])

    @patch("nodephell.resolver.subprocess.run")
    def test_resolves_dependencies_from_build_backend_metadata(self, run) -> None:
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
                                    "name": "dynamic-demo",
                                    "version": "1.0",
                                },
                            },
                            self._entry("requests", "2.32.5"),
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
name = "dynamic-demo"
version = "1.0"
dynamic = ["dependencies"]
''',
                encoding="utf-8",
            )
            project = load_project_definition(root)
            runtime = Runtime(
                "cpython",
                "3.15.0",
                root / "python3.15",
                "cpython-315-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            loaded = load_project(root)

            command = run.call_args.args[0]
            self.assertIn(".", command)
            self.assertEqual(
                tuple(package.name for package in loaded.packages),
                ("requests",),
            )
            self.assertNotIn("dynamic-demo", lock.read_text(encoding="utf-8"))
            self.assertTrue(lock_matches_project_definition(root))
            self.assertEqual(lock, root / "pylock.toml")
            self.assertIn(
                'created-by = "nodephell"', lock.read_text(encoding="utf-8")
            )
            self.assertIn(
                'requires-python = "==3.15.0"',
                lock.read_text(encoding="utf-8"),
            )

    @patch("nodephell.resolver.subprocess.run")
    def test_dependency_group_includes_preserve_repeated_requirements(
        self, run
    ) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {"version": "1", "install": [self._entry("requests", "2.32.5")]}
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"

[dependency-groups]
base = ["requests"]
first = [{ include-group = "base" }]
second = [{ include-group = "base" }]
''',
                encoding="utf-8",
            )
            project = replace(
                load_project_definition(root),
                selected_groups=("first", "second"),
            )
            runtime = Runtime(
                "cpython",
                "3.15.0",
                root / "python3.15",
                "cpython-315-x86_64-linux-gnu",
                "linux-x86_64",
            )

            resolve_and_write_lock(project, runtime)

        command = run.call_args.args[0]
        self.assertEqual(command.count("requests"), 2)

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

    @patch("nodephell.resolver.subprocess.run")
    def test_resolves_uv_index_and_editable_path_sources(self, run) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "install": [
                            {
                                "download_info": {"url": local.as_uri()},
                                "is_direct": True,
                                "requested": True,
                                "metadata": {
                                    "name": "nano-vllm",
                                    "version": "0.1",
                                },
                            },
                            self._entry("torch", "2.8.0+rocm6.4"),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / "acestep" / "third_parts" / "nano-vllm"
            local.mkdir(parents=True)
            (local / "pyproject.toml").write_text(
                '''[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "nano-vllm"
version = "0.1"
''',
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                '''[project]
name = "ace-step"
dependencies = [
  "nano-vllm",
  "torch==2.8.0+rocm6.4; sys_platform == 'linux'",
]

[[tool.uv.index]]
name = "pytorch-rocm"
url = "https://download.pytorch.org/whl/rocm6.4"
explicit = true

[tool.uv.sources]
nano-vllm = { path = "acestep/third_parts/nano-vllm" }
torch = { index = "pytorch-rocm", marker = "sys_platform == 'linux'" }
''',
                encoding="utf-8",
            )
            project = load_project_definition(root)
            runtime = Runtime(
                "cpython",
                "3.12.3",
                root / "python3.12",
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            loaded = load_project(root)
            lock_text = lock.read_text(encoding="utf-8")
            current_match = lock_matches_project_definition(root)

        command = run.call_args.args[0]
        self.assertIn("--extra-index-url", command)
        self.assertIn(
            "https://download.pytorch.org/whl/rocm6.4",
            command,
        )
        self.assertIn(f"nano-vllm @ {local.as_uri()}", command)
        self.assertIn(
            "torch==2.8.0+rocm6.4; sys_platform == 'linux'",
            command,
        )
        self.assertEqual(
            loaded.local_projects,
            (Path("acestep/third_parts/nano-vllm"),),
        )
        self.assertEqual(
            tuple(package.name for package in loaded.packages),
            ("torch",),
        )
        self.assertIn("local-projects", lock_text)
        self.assertTrue(current_match)

    @patch("nodephell.resolver.subprocess.run")
    def test_requirements_profile_replaces_project_dependencies(self, run) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "install": [
                            {
                                "download_info": {"url": local.as_uri()},
                                "is_direct": True,
                                "requested": True,
                                "metadata": {
                                    "name": "nano-vllm",
                                    "version": "0.1",
                                },
                            },
                            self._entry("rocm-package", "6.4"),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / "acestep" / "third_parts" / "nano-vllm"
            local.mkdir(parents=True)
            (local / "pyproject.toml").write_text(
                '''[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "nano-vllm"
version = "0.1"
''',
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                '''[project]
name = "ace-step"
dependencies = ["cuda-package==12.8"]

[tool.uv.sources]
nano-vllm = { path = "acestep/third_parts/nano-vllm" }
''',
                encoding="utf-8",
            )
            profile = root / "requirements-rocm-linux.txt"
            profile.write_text(
                "--extra-index-url https://download.pytorch.org/whl/rocm6.4\n"
                "-e acestep/third_parts/nano-vllm\n"
                "-r requirements-common.txt\n",
                encoding="utf-8",
            )
            common = root / "requirements-common.txt"
            common.write_text("rocm-package==6.4\n", encoding="utf-8")
            project = replace(
                load_project_definition(root),
                requirement_files=(Path(profile.name),),
                replace_requirements=True,
            )
            runtime = Runtime(
                "cpython",
                "3.12.3",
                root / "python3.12",
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            loaded = load_project(root)
            lock_text = lock.read_text(encoding="utf-8")
            initial_match = lock_matches_project_definition(root)
            common.write_text("rocm-package==6.5\n", encoding="utf-8")
            changed_match = lock_matches_project_definition(root)

        command = run.call_args.args[0]
        self.assertIn("-r", command)
        self.assertIn(str(profile), command)
        self.assertNotIn("cuda-package==12.8", command)
        self.assertEqual(
            loaded.requirement_files,
            (Path("requirements-rocm-linux.txt"),),
        )
        self.assertTrue(loaded.replace_requirements)
        self.assertEqual(
            loaded.local_projects,
            (Path("acestep/third_parts/nano-vllm"),),
        )
        self.assertEqual(
            tuple(package.name for package in loaded.packages),
            ("rocm-package",),
        )
        self.assertIn(
            'requirements = ["requirements-rocm-linux.txt"]',
            lock_text,
        )
        self.assertTrue(initial_match)
        self.assertFalse(changed_match)

    @patch("nodephell.resolver.subprocess.run")
    def test_requirements_profile_rejects_insecure_resolved_artifact(
        self,
        run,
    ) -> None:
        def fake_resolver(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            entry = self._entry("demo", "1.0")
            entry["download_info"]["url"] = (
                "http://example.invalid/files/demo-1.0-py3-none-any.whl"
            )
            report.write_text(
                json.dumps({"version": "1", "install": [entry]}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        run.side_effect = fake_resolver
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )
            profile = root / "requirements.txt"
            profile.write_text("demo\n", encoding="utf-8")
            project = replace(
                load_project_definition(root),
                requirement_files=(Path(profile.name),),
                replace_requirements=True,
            )
            runtime = Runtime(
                "cpython",
                "3.12.3",
                root / "python3.12",
                "cpython-312-x86_64-linux-gnu",
                "linux-x86_64",
            )

            with self.assertRaisesRegex(NodePhellError, "non-HTTPS"):
                resolve_and_write_lock(project, runtime)

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
