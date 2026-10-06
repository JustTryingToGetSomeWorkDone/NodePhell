# SPDX-License-Identifier: GPL-3.0-only

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.host import (
    EmbeddedHost,
    host_environment,
    load_hosts,
    probe_host,
    register_host,
    select_host,
)
from nodephell.metadata import HostRequirement
from nodephell.runtime import Runtime
from nodephell.store import PackageSelection


def embedded_host(
    version: str = "1.1.3",
    python_version: str = "3.11.14",
    abi: str = "cpython-311-x86_64-linux-gnu",
) -> EmbeddedHost:
    executable = Path(f"/hosts/freecad-{version}")
    runtime = Runtime(
        "cpython",
        python_version,
        executable,
        abi,
        "linux-x86_64",
        (Path("/hosts/lib"),),
    )
    return EmbeddedHost(
        "freecad",
        version,
        executable,
        runtime,
        (("APPDIR", "/hosts"),),
    )


class HostTests(unittest.TestCase):
    @patch("nodephell.host.subprocess.run")
    def test_probes_extracted_freecad_appimage(self, run) -> None:
        details = {
            "host_version": ["1", "1", "3"],
            "implementation": "cpython",
            "python_version": "3.11.14",
            "abi": "cpython-311-x86_64-linux-gnu",
            "platform": "linux-x86_64",
        }
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout="banner\n__NODEPHELL_FREECAD_HOST__" + json.dumps(details),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temporary:
            app_dir = Path(temporary) / "squashfs-root"
            executable = app_dir / "usr/bin/freecadcmd"
            executable.parent.mkdir(parents=True)
            executable.touch()
            (app_dir / "usr/lib").mkdir()
            (app_dir / "AppRun").touch()

            host = probe_host(executable)

        self.assertEqual(host.kind, "freecad")
        self.assertEqual(host.version, "1.1.3")
        self.assertEqual(host.runtime.version, "3.11.14")
        self.assertEqual(host.runtime.abi, "cpython-311-x86_64-linux-gnu")
        self.assertEqual(dict(host.environment)["APPDIR"], str(app_dir))
        self.assertEqual(host.runtime.library_paths, ((app_dir / "usr/lib").resolve(),))
        self.assertEqual(run.call_args.args[0][0], str(executable.resolve()))

    @patch("nodephell.host.probe_host")
    def test_registry_preserves_host_identity(self, probe) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            executable = home / "freecadcmd"
            executable.touch()
            expected = embedded_host()
            expected = EmbeddedHost(
                expected.kind,
                expected.version,
                executable.resolve(),
                Runtime(
                    expected.runtime.implementation,
                    expected.runtime.version,
                    executable.resolve(),
                    expected.runtime.abi,
                    expected.runtime.platform,
                    expected.runtime.library_paths,
                ),
                expected.environment,
            )
            probe.return_value = expected

            registered = register_host(executable, home)

            self.assertEqual(registered, expected)
            self.assertEqual(load_hosts(home), (expected,))

    def test_selects_abi_compatible_host(self) -> None:
        requirement = HostRequirement("freecad", ">=1.1,<1.2")
        project_runtime = Runtime(
            "cpython",
            "3.11.14",
            Path("/python"),
            "cpython-311-x86_64-linux-gnu",
            "linux-x86_64",
        )
        older = embedded_host("1.1.2")
        newer = embedded_host("1.1.3")
        incompatible = embedded_host("1.1.4", abi="cpython-312-x86_64-linux-gnu")

        selected = select_host(
            requirement,
            (older, newer, incompatible),
            project_runtime,
        )

        self.assertEqual(selected, newer)

    def test_rejects_host_with_incompatible_python_abi(self) -> None:
        project_runtime = Runtime(
            "cpython",
            "3.12.3",
            Path("/python"),
            "cpython-312-x86_64-linux-gnu",
            "linux-x86_64",
        )
        with self.assertRaisesRegex(NodePhellError, "Python ABI"):
            select_host(
                HostRequirement("freecad"),
                (embedded_host(),),
                project_runtime,
            )

    def test_host_environment_injects_only_selected_packages(self) -> None:
        host = embedded_host()
        packages = PackageSelection((Path("/packages/composed"),))

        environment = host_environment(
            host,
            packages,
            {
                "PYTHONPATH": "/unrelated",
                "PYTHONHOME": "/wrong",
                "LD_LIBRARY_PATH": "/system",
            },
        )

        self.assertEqual(environment["PYTHONPATH"], "/packages/composed")
        self.assertNotIn("PYTHONHOME", environment)
        self.assertEqual(environment["APPDIR"], "/hosts")
        self.assertEqual(
            environment["LD_LIBRARY_PATH"],
            os.pathsep.join(("/hosts/lib", "/system")),
        )


if __name__ == "__main__":
    unittest.main()
