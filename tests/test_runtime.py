# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.metadata import RuntimeArtifact
from nodephell.runtime import (
    Runtime,
    _select_standalone_asset,
    _verify_runtime_archive,
    data_root,
    delete_runtime,
    install_runtime,
    interpreter_store,
    load_registry,
    native_build_failure_guidance,
    register_runtime,
    runtime_build_environment,
    select_reusable_runtime,
    select_runtime,
    unregister_runtime,
)
from nodephell.versions import lowest_runtime_line, matches_runtime


def artifact(
    version: str = "3.13.11",
    digest: str = "a" * 64,
    triple: str = "x86_64-unknown-linux-gnu",
) -> RuntimeArtifact:
    name = (
        f"cpython-{version}+20261003-{triple}-install_only.tar.gz"
    )
    return RuntimeArtifact(
        "cpython",
        version,
        triple,
        name,
        f"https://example.invalid/{name}",
        (("sha256", digest),),
    )


def runtime(
    version: str,
    name: str,
    runtime_artifact: RuntimeArtifact | None = None,
) -> Runtime:
    return Runtime(
        "cpython",
        version,
        Path("/runtimes") / name,
        f"cpython-{version.replace('.', '')}",
        "linux-x86_64",
        (),
        runtime_artifact,
    )


class RuntimeTests(unittest.TestCase):
    def test_data_root_uses_explicit_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(
                data_root(Path(temporary)),
                Path(temporary) / ".python",
            )

    @patch("nodephell.runtime.shutil.which")
    @patch("nodephell.runtime.subprocess.run")
    def test_build_environment_replaces_unavailable_recorded_tools(
        self,
        run,
        which,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            (),
            0,
            stdout=json.dumps(
                {
                    "CC": "clang -pthread",
                    "CXX": "clang++ -pthread",
                    "AR": "/tools/llvm/bin/llvm-ar",
                }
            ),
        )
        available = {
            "cc": "/usr/bin/cc",
            "c++": "/usr/bin/c++",
            "ar": "/usr/bin/ar",
        }
        which.side_effect = lambda command, path=None: available.get(command)

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "python"
            executable.touch()
            selected = Runtime(
                "cpython",
                "3.13.11",
                executable,
                "cpython-313-x86_64-linux-gnu",
                "linux-x86_64",
            )
            environment = runtime_build_environment(
                selected,
                {"PATH": "/usr/bin"},
            )

        self.assertEqual(environment["CC"], "/usr/bin/cc")
        self.assertEqual(environment["CXX"], "/usr/bin/c++")
        self.assertEqual(environment["AR"], "/usr/bin/ar")

    @patch("nodephell.runtime.shutil.which")
    @patch("nodephell.runtime.subprocess.run")
    def test_build_environment_preserves_explicit_tools(self, run, which) -> None:
        run.return_value = subprocess.CompletedProcess(
            (),
            0,
            stdout=json.dumps({"CC": "clang", "CXX": "clang++", "AR": "ar"}),
        )
        which.return_value = None

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "python"
            executable.touch()
            selected = Runtime(
                "cpython",
                "3.13.11",
                executable,
                "cpython-313-x86_64-linux-gnu",
                "linux-x86_64",
            )
            environment = runtime_build_environment(
                selected,
                {
                    "PATH": "/usr/bin",
                    "CC": "/opt/compiler/cc",
                    "CXX": "/opt/compiler/c++",
                    "AR": "/opt/compiler/ar",
                },
            )

        self.assertEqual(environment["CC"], "/opt/compiler/cc")
        self.assertEqual(environment["CXX"], "/opt/compiler/c++")
        self.assertEqual(environment["AR"], "/opt/compiler/ar")

    def test_missing_build_tool_guidance_names_override(self) -> None:
        guidance = native_build_failure_guidance(
            "error: [Errno 2] No such file or directory: 'clang'"
        )

        self.assertIsNotNone(guidance)
        assert guidance is not None
        self.assertIn("clang", guidance)
        self.assertIn("CC=/path/to/an/available-tool", guidance)

    def test_missing_native_dependency_guidance_names_remedy(self) -> None:
        guidance = native_build_failure_guidance(
            "The headers or library files could not be found for jpeg, "
            "a required dependency."
        )

        self.assertIsNotNone(guidance)
        assert guidance is not None
        self.assertIn("development headers and libraries", guidance)
        self.assertIn("sudo apt install libjpeg-dev", guidance)

    def test_missing_development_packages_guidance_names_remedy(self) -> None:
        guidance = native_build_failure_guidance(
            "Error: Please make sure the libxml2 and libxslt development "
            "packages are installed."
        )

        self.assertIsNotNone(guidance)
        assert guidance is not None
        self.assertIn("libxml2 and libxslt", guidance)
        self.assertIn(
            "sudo apt install libxml2-dev libxslt1-dev",
            guidance,
        )

    def test_matches_bounded_requirement(self) -> None:
        self.assertTrue(matches_runtime("3.13.15", ">=3.13,<3.14"))
        self.assertFalse(matches_runtime("3.14.0", ">=3.13,<3.14"))

    def test_matches_development_runtime_when_explicitly_allowed(self) -> None:
        self.assertTrue(
            matches_runtime("3.16.0a0", ">=3.16.0a0,<3.17")
        )

    def test_alpha_runtime_precedes_final_release(self) -> None:
        self.assertFalse(matches_runtime("3.16.0a0", ">=3.16,<3.17"))

    def test_broad_requirement_does_not_select_prerelease(self) -> None:
        self.assertFalse(matches_runtime("3.15.0rc3", ">=3.8,<4.0"))

    def test_finds_earliest_declared_python_minor_line(self) -> None:
        self.assertEqual(
            lowest_runtime_line(">=3.8,<4.0"),
            ("3.8", ">=3.8,<4.0,<3.9"),
        )
        self.assertEqual(
            lowest_runtime_line(">=3.8,>=3.11,<4.0"),
            ("3.11", ">=3.8,>=3.11,<4.0,<3.12"),
        )

    def test_exact_or_major_only_requirement_has_no_minor_fallback(self) -> None:
        self.assertIsNone(lowest_runtime_line("==3.13.2"))
        self.assertIsNone(lowest_runtime_line(">=3,<4"))

    def test_reuses_newest_compatible_artifact_runtime(self) -> None:
        old_artifact = artifact("3.12.12")
        new_artifact = artifact("3.13.11")

        selected = select_reusable_runtime(
            ">=3.8,<4.0",
            (
                runtime("3.12.12", "old", old_artifact),
                runtime("3.13.11", "new", new_artifact),
                runtime("3.14.0", "external"),
                runtime("3.15.0rc3", "prerelease", artifact("3.15.0rc3")),
            ),
        )

        self.assertEqual(selected, runtime("3.13.11", "new", new_artifact))

    def test_selects_newest_compatible_registered_runtime(self) -> None:
        current = runtime("3.11.9", "current")
        selected = select_runtime(
            ">=3.13,<3.14",
            (runtime("3.13.4", "old"), runtime("3.13.15", "new")),
            current,
        )
        self.assertEqual(selected.version, "3.13.15")

    def test_without_requirement_keeps_bootstrap_runtime(self) -> None:
        current = runtime("3.11.9", "current")
        selected = select_runtime(None, (runtime("3.16.0", "new"),), current)
        self.assertEqual(selected, current)

    def test_reports_unsatisfied_requirement(self) -> None:
        with self.assertRaises(NodePhellError):
            select_runtime(">=3.16", (), runtime("3.13.15", "current"))

    def test_locked_artifact_requires_matching_runtime_provenance(self) -> None:
        locked = artifact()
        matching = runtime(locked.version, "matching", locked)
        same_version = runtime(locked.version, "unproven")

        selected = select_runtime(
            f"=={locked.version}",
            (same_version, matching),
            runtime("3.12.0", "current"),
            locked,
        )

        self.assertEqual(selected, matching)
        with self.assertRaises(NodePhellError):
            select_runtime(
                f"=={locked.version}",
                (same_version,),
                runtime("3.12.0", "current"),
                locked,
            )

    @patch("nodephell.runtime.probe_runtime")
    def test_registration_replaces_same_runtime_identity(self, probe) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            first_path = home / "first-python"
            second_path = home / "second-python"
            first_path.touch()
            second_path.touch()
            first = runtime("3.13.15", "first-python")
            second = runtime("3.13.15", "second-python")
            first = Runtime(
                first.implementation,
                first.version,
                first_path,
                first.abi,
                first.platform,
            )
            second = Runtime(
                second.implementation,
                second.version,
                second_path,
                second.abi,
                second.platform,
            )
            probe.side_effect = (first, second)

            register_runtime(first_path, user_home=home)
            register_runtime(second_path, user_home=home)

            self.assertEqual(load_registry(home), (second,))

    @patch("nodephell.runtime.probe_runtime")
    def test_registry_preserves_runtime_artifact(self, probe) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            executable = home / "python3"
            executable.touch()
            locked = artifact()
            probed = Runtime(
                "cpython",
                locked.version,
                executable,
                "cpython-313-x86_64-linux-gnu",
                "linux-x86_64",
            )
            probe.return_value = probed

            registered = register_runtime(
                executable,
                user_home=home,
                artifact=locked,
            )

            self.assertEqual(registered.artifact, locked)
            self.assertEqual(load_registry(home), (registered,))

    @patch("nodephell.runtime.probe_runtime")
    def test_unregisters_missing_runtime_without_deleting_files(self, probe) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            executable = home / "external" / "python3"
            executable.parent.mkdir()
            executable.touch()
            probe.return_value = Runtime(
                "cpython",
                "3.13.11",
                executable.resolve(),
                "cpython-313-x86_64-linux-gnu",
                "linux-x86_64",
            )
            registered = register_runtime(executable, user_home=home)

            with self.assertRaisesRegex(NodePhellError, "externally managed"):
                delete_runtime(executable, home)
            self.assertTrue(executable.is_file())
            executable.unlink()

            removed = unregister_runtime(executable, home)

            self.assertEqual(removed, registered)
            self.assertEqual(load_registry(home), ())
            self.assertTrue(executable.parent.is_dir())

    @patch("nodephell.runtime.probe_runtime")
    def test_deletes_only_managed_runtime(self, probe) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            locked = artifact()
            managed = interpreter_store(
                locked.version,
                "cpython-313-x86_64-linux-gnu",
                home,
                locked,
            )
            executable = managed / "bin" / "python3"
            executable.parent.mkdir(parents=True)
            executable.touch()
            probe.return_value = Runtime(
                "cpython",
                locked.version,
                executable.resolve(),
                "cpython-313-x86_64-linux-gnu",
                "linux-x86_64",
            )
            register_runtime(executable, user_home=home, artifact=locked)

            _, removed, existed = delete_runtime(executable, home)

            self.assertEqual(removed, managed)
            self.assertTrue(existed)
            self.assertFalse(managed.exists())
            self.assertEqual(load_registry(home), ())

    def test_verifies_runtime_archive_sha256(self) -> None:
        content = b"verified runtime archive"
        digest = hashlib.sha256(content).hexdigest()
        locked = artifact(digest=digest)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / locked.name
            archive.write_bytes(content)

            _verify_runtime_archive(archive, locked)
            archive.write_bytes(b"tampered")
            with self.assertRaisesRegex(NodePhellError, "SHA-256 mismatch"):
                _verify_runtime_archive(archive, locked)

    @patch("nodephell.runtime._extract_tar")
    @patch("nodephell.runtime._download")
    @patch("nodephell.runtime._platform_triple")
    def test_tampered_download_is_not_extracted(
        self,
        platform_triple,
        download,
        extract_tar,
    ) -> None:
        platform_triple.return_value = "x86_64-unknown-linux-gnu"
        locked = artifact(digest="0" * 64)
        download.side_effect = lambda url, target: target.write_bytes(b"tampered")

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(NodePhellError, "SHA-256 mismatch"):
                install_runtime(
                    f"=={locked.version}",
                    Path(temporary),
                    artifact=locked,
                )

        extract_tar.assert_not_called()

    def test_interpreter_store_separates_runtime_builds(self) -> None:
        first = artifact(digest="1" * 64)
        second = artifact(digest="2" * 64)
        home = Path("/users/example")

        first_path = interpreter_store("3.13.11", "abi", home, first)
        second_path = interpreter_store("3.13.11", "abi", home, second)

        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.name, first.sha256)

    @patch("nodephell.runtime._platform_triple")
    @patch("nodephell.runtime._json_url")
    def test_selects_latest_matching_downloadable_runtime(
        self, json_url, platform_triple
    ) -> None:
        platform_triple.return_value = "x86_64-unknown-linux-gnu"
        json_url.side_effect = (
            {"version": 1, "tag": "20261003"},
            {
                "assets": [
                    {
                        "name": artifact("3.12.12").name,
                        "browser_download_url": artifact("3.12.12").url,
                        "digest": f"sha256:{'1' * 64}",
                    },
                    {
                        "name": artifact("3.13.11").name,
                        "browser_download_url": artifact("3.13.11").url,
                        "digest": f"sha256:{'2' * 64}",
                    },
                    {
                        "name": artifact(
                            "3.13.11",
                            triple="aarch64-unknown-linux-gnu",
                        ).name,
                        "browser_download_url": artifact(
                            "3.13.11",
                            triple="aarch64-unknown-linux-gnu",
                        ).url,
                        "digest": f"sha256:{'3' * 64}",
                    },
                ]
            },
        )

        asset = _select_standalone_asset(">=3.13,<3.14")

        self.assertEqual(asset.version, "3.13.11")
        self.assertEqual(asset.sha256, "2" * 64)


if __name__ == "__main__":
    unittest.main()
