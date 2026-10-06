# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.errors import NodePhellError
from nodephell.metadata import (
    HostArtifact,
    HostRequirement,
    PackagePin,
    RuntimeArtifact,
    discover_project,
    invocation_start,
    load_project,
)


_RUNTIME_NAME = (
    "cpython-3.13.11+20261003-x86_64-unknown-linux-gnu-"
    "install_only.tar.gz"
)
_RUNTIME_URL = f"https://example.invalid/{_RUNTIME_NAME.replace('+', '%2B')}"
_RUNTIME_SHA256 = "a" * 64
_HOST_NAME = "FreeCAD_1.1.3-Linux-x86_64-py311.AppImage"
_HOST_URL = f"https://example.invalid/{_HOST_NAME}"
_HOST_SHA256 = "b" * 64


class MetadataTests(unittest.TestCase):
    def test_discovers_project_from_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pylock.toml").write_text(
                'lock-version = "1.0"\npackages = []\n',
                encoding="utf-8",
            )
            script = root / "src" / "tool.py"
            script.parent.mkdir()
            start = invocation_start([str(script)], Path("/"))
            self.assertEqual(discover_project(start), root)

    def test_loads_exact_pylock_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pylock.toml").write_text(
                f"""lock-version = "1.0"
requires-python = ">=3.13,<3.14"

[tool.nodephell.runtime]
implementation = "cpython"
version = "3.13.11"
platform = "x86_64-unknown-linux-gnu"
name = "{_RUNTIME_NAME}"
url = "{_RUNTIME_URL}"

[tool.nodephell.runtime.hashes]
sha256 = "{_RUNTIME_SHA256}"

[tool.nodephell.host]
kind = "freecad"
requires = ">=1.1,<1.2"
version = "1.1.3"
platform = "linux-x86_64"
name = "{_HOST_NAME}"
url = "{_HOST_URL}"

[tool.nodephell.host.hashes]
sha256 = "{_HOST_SHA256}"

[[packages]]
name = "example-package"
version = "2.0.post1"

[[packages.wheels]]
name = "example_package-2.0.post1-py3-none-any.whl"
url = "https://example.invalid/example_package-2.0.post1-py3-none-any.whl"

[packages.wheels.hashes]
sha256 = "abc123"
""",
                encoding="utf-8",
            )
            project = load_project(root)
            self.assertEqual(project.requires_python, ">=3.13,<3.14")
            self.assertEqual(
                project.runtime_artifact,
                RuntimeArtifact(
                    "cpython",
                    "3.13.11",
                    "x86_64-unknown-linux-gnu",
                    _RUNTIME_NAME,
                    _RUNTIME_URL,
                    (("sha256", _RUNTIME_SHA256),),
                ),
            )
            self.assertEqual(project.runtime_requirement, "==3.13.11")
            self.assertEqual(
                project.host,
                HostRequirement("freecad", ">=1.1,<1.2"),
            )
            self.assertEqual(
                project.host_artifact,
                HostArtifact(
                    "freecad",
                    "1.1.3",
                    "linux-x86_64",
                    _HOST_NAME,
                    _HOST_URL,
                    (("sha256", _HOST_SHA256),),
                ),
            )
            self.assertEqual(project.packages[0].version, "2.0.post1")
            self.assertEqual(project.packages[0].hashes, (("sha256", "abc123"),))

    def test_rejects_locked_runtime_outside_project_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = _RUNTIME_NAME.replace("3.13.11", "3.12.12")
            url = f"https://example.invalid/{name.replace('+', '%2B')}"
            (root / "pylock.toml").write_text(
                f'''lock-version = "1.0"
requires-python = ">=3.13,<3.14"

[tool.nodephell.runtime]
implementation = "cpython"
version = "3.12.12"
platform = "x86_64-unknown-linux-gnu"
name = "{name}"
url = "{url}"

[tool.nodephell.runtime.hashes]
sha256 = "{_RUNTIME_SHA256}"
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(NodePhellError, "does not satisfy"):
                load_project(root)

    def test_pyproject_requires_exact_package_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\ndependencies = ["demo>=1"]\n',
                encoding="utf-8",
            )
            with self.assertRaises(NodePhellError):
                load_project(root)

    def test_loads_freecad_host_from_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "cad-demo"
requires-python = ">=3.11,<3.12"

[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
''',
                encoding="utf-8",
            )

            project = load_project(root)

            self.assertEqual(
                project.host,
                HostRequirement("freecad", "==1.1.3"),
            )

    def test_package_pin_rejects_path_components(self) -> None:
        with self.assertRaises(NodePhellError):
            PackagePin("demo", "../../outside")


if __name__ == "__main__":
    unittest.main()
