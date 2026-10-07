# SPDX-License-Identifier: GPL-3.0-only

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from nodephell.errors import NodePhellError
from nodephell.host import (
    EmbeddedHost,
    _verify_host_artifact,
    execute_host_gui,
    host_environment,
    host_store,
    install_host,
    load_hosts,
    probe_host,
    register_host,
    resolve_host_artifact,
    select_host,
)
from nodephell.metadata import HostArtifact, HostRequirement
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


def artifact(
    version: str = "1.1.3",
    digest: str = "a" * 64,
) -> HostArtifact:
    name = f"FreeCAD_{version}-Linux-x86_64-py311.AppImage"
    return HostArtifact(
        "freecad",
        version,
        "linux-x86_64",
        name,
        f"https://example.invalid/{name}",
        (("sha256", digest),),
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
                "HOME": "/users/example",
                "PYTHONPATH": "/unrelated",
                "PYTHONHOME": "/wrong",
                "LD_LIBRARY_PATH": "/system",
            },
        )

        self.assertEqual(environment["PYTHONPATH"], "/packages/composed")
        self.assertEqual(
            environment["PYTHONUSERBASE"],
            "/users/example/.python/disabled-user-base",
        )
        self.assertNotIn("PYTHONHOME", environment)
        self.assertEqual(environment["APPDIR"], "/hosts")
        self.assertEqual(
            environment["LD_LIBRARY_PATH"],
            os.pathsep.join(("/hosts/lib", "/system")),
        )

    @patch("nodephell.host.os.execvpe")
    @patch("nodephell.host.register_resolution")
    def test_gui_uses_sibling_executable_and_project_packages(
        self,
        register_resolution,
        execvpe,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "squashfs-root"
            command = root / "usr/bin/freecadcmd"
            gui = root / "usr/bin/freecad"
            gui.parent.mkdir(parents=True)
            command.touch()
            gui.touch()
            library = root / "usr/lib"
            library.mkdir()
            runtime = Runtime(
                "cpython",
                "3.11.14",
                command,
                "cpython-311-x86_64-linux-gnu",
                "linux-x86_64",
                (library,),
            )
            host = EmbeddedHost(
                "freecad",
                "1.1.3",
                command,
                runtime,
                (("APPDIR", str(root)),),
            )
            resolution = Mock()
            resolution.host = host
            resolution.project.packages = PackageSelection(
                (Path("/packages/composed"),)
            )

            execute_host_gui(["model.FCStd"], resolution)

        register_resolution.assert_called_once_with(resolution.project)
        executable, arguments, environment = execvpe.call_args.args
        self.assertEqual(executable, str(gui))
        self.assertEqual(
            arguments,
            [
                str(gui),
                "--python-path",
                "/packages/composed",
                "model.FCStd",
            ],
        )
        self.assertEqual(environment["PYTHONPATH"], "/packages/composed")
        self.assertEqual(environment["APPDIR"], str(root))

    @patch("nodephell.host._json_url")
    def test_selects_latest_matching_freecad_artifact(self, json_url) -> None:
        older = artifact("1.1.2", "1" * 64)
        selected = artifact("1.1.3", "2" * 64)
        wrong_python = HostArtifact(
            "freecad",
            "1.1.4",
            "linux-x86_64",
            "FreeCAD_1.1.4-Linux-x86_64-py312.AppImage",
            "https://example.invalid/FreeCAD_1.1.4-Linux-x86_64-py312.AppImage",
            (("sha256", "3" * 64),),
        )
        json_url.return_value = [
            {
                "draft": False,
                "assets": [
                    {
                        "name": item.name,
                        "browser_download_url": item.url,
                        "digest": f"sha256:{item.sha256}",
                    }
                    for item in (older, selected, wrong_python)
                ],
            }
        ]
        runtime = Runtime(
            "cpython",
            "3.11.17",
            Path("/python"),
            "cpython-311-x86_64-linux-gnu",
            "linux-x86_64",
        )

        resolved = resolve_host_artifact(
            HostRequirement("freecad", ">=1.1,<1.2"),
            runtime,
        )

        self.assertEqual(resolved, selected)

    def test_verifies_host_artifact_sha256(self) -> None:
        content = b"verified FreeCAD AppImage"
        locked = artifact(digest=hashlib.sha256(content).hexdigest())
        with tempfile.TemporaryDirectory() as temporary:
            appimage = Path(temporary) / locked.name
            appimage.write_bytes(content)

            _verify_host_artifact(appimage, locked)
            appimage.write_bytes(b"tampered")
            with self.assertRaisesRegex(NodePhellError, "SHA-256 mismatch"):
                _verify_host_artifact(appimage, locked)

    @patch("nodephell.host._extract_appimage")
    @patch("nodephell.host._download")
    def test_tampered_host_is_not_extracted(self, download, extract) -> None:
        locked = artifact(digest="0" * 64)
        download.side_effect = lambda url, target: target.write_bytes(b"tampered")
        runtime = Runtime(
            "cpython",
            "3.11.17",
            Path("/python"),
            "cpython-311-x86_64-linux-gnu",
            "linux-x86_64",
        )

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(NodePhellError, "SHA-256 mismatch"):
                install_host(
                    HostRequirement("freecad", "==1.1.3"),
                    runtime,
                    Path(temporary),
                    artifact=locked,
                )

        extract.assert_not_called()

    @patch("nodephell.host.probe_host")
    @patch("nodephell.host._extract_appimage")
    @patch("nodephell.host._download")
    def test_installs_verified_host_atomically(
        self,
        download,
        extract,
        probe,
    ) -> None:
        content = b"verified FreeCAD AppImage"
        locked = artifact(digest=hashlib.sha256(content).hexdigest())
        download.side_effect = lambda url, target: target.write_bytes(content)

        def fake_extract(appimage, destination):
            root = destination / "squashfs-root"
            executable = root / "usr/bin/freecadcmd"
            executable.parent.mkdir(parents=True)
            executable.touch()
            (root / "usr/lib").mkdir()
            (root / "AppRun").touch()

        def fake_probe(executable):
            executable = executable.resolve()
            root = executable.parent.parent.parent
            embedded = Runtime(
                "cpython",
                "3.11.14",
                executable,
                "cpython-311-x86_64-linux-gnu",
                "linux-x86_64",
                (root / "usr/lib",),
            )
            return EmbeddedHost(
                "freecad",
                "1.1.3",
                executable,
                embedded,
                (("APPDIR", str(root)),),
            )

        extract.side_effect = fake_extract
        probe.side_effect = fake_probe
        runtime = Runtime(
            "cpython",
            "3.11.17",
            Path("/python"),
            "cpython-311-x86_64-linux-gnu",
            "linux-x86_64",
        )

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installed = install_host(
                HostRequirement("freecad", "==1.1.3"),
                runtime,
                home,
                artifact=locked,
            )

            self.assertEqual(installed.artifact, locked)
            self.assertEqual(
                installed.executable,
                host_store(locked, home) / "usr/bin/freecadcmd",
            )
            self.assertEqual(load_hosts(home), (installed,))


if __name__ == "__main__":
    unittest.main()
