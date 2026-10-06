# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.metadata import PackagePin, Project, load_project
from nodephell.resolver import resolve_and_write_lock
from nodephell.runtime import Runtime


class ResolverTests(unittest.TestCase):
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
dependencies = ["demo==1.2.3"]
""",
                encoding="utf-8",
            )
            project = Project(
                root,
                root / "pyproject.toml",
                ">=3.16.0a0,<3.17",
                (PackagePin("demo", "1.2.3"),),
            )
            runtime = Runtime(
                "cpython",
                "3.16.0a0",
                root / "python3.16",
                "cpython-316-x86_64-linux-gnu",
                "linux-x86_64",
            )

            lock = resolve_and_write_lock(project, runtime)
            loaded = load_project(root)

            self.assertEqual(lock, root / "pylock.toml")
            self.assertEqual(
                loaded.packages,
                (
                    PackagePin("demo", "1.2.3", (("sha256", "abc123"),)),
                    PackagePin(
                        "dependency",
                        "4.5.6",
                        (("sha256", "abc123"),),
                    ),
                ),
            )
            command = run.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertIn("--ignore-installed", command)
            self.assertIn("--target", command)
            self.assertNotIn("--no-deps", command)
            self.assertIn('"sha256" = "abc123"', lock.read_text())

    @staticmethod
    def _entry(name: str, version: str) -> dict:
        filename = f"{name}-{version}-py3-none-any.whl"
        return {
            "download_info": {
                "url": f"https://example.invalid/files/{filename}",
                "archive_info": {"hashes": {"sha256": "abc123"}},
            },
            "metadata": {"name": name, "version": version},
        }


if __name__ == "__main__":
    unittest.main()
