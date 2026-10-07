# SPDX-License-Identifier: GPL-3.0-only

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
)
from nodephell.resolver import resolve_and_write_lock
from nodephell.runtime import Runtime


class ResolverTests(unittest.TestCase):
    PACKAGE_SHA256 = "c" * 64

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
