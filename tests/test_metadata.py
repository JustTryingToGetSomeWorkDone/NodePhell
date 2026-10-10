# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import tempfile
import unittest

from nodephell.errors import NodePhellError
from nodephell.metadata import (
    ApplicationDeclaration,
    DependencyOption,
    HostArtifact,
    HostRequirement,
    PackageArtifact,
    PackagePin,
    PackageRequirement,
    RuntimeArtifact,
    discover_project,
    invocation_start,
    load_project,
    load_project_definition,
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
_PACKAGE_SHA256 = "c" * 64


class MetadataTests(unittest.TestCase):
    def test_loads_optional_features_groups_and_locked_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"

[project.optional-dependencies]
gui = ["qtpy", "PySide6"]

[dependency-groups]
test = ["pytest"]
dev = ["ruff", { include-group = "test" }]
''',
                encoding="utf-8",
            )
            (root / "pylock.toml").write_text(
                '''lock-version = "1.0"

[tool.nodephell.selection]
extras = ["gui"]
groups = ["dev"]
''',
                encoding="utf-8",
            )

            project = load_project(root)

            self.assertEqual(project.name, "demo")
            self.assertEqual(
                project.optional_dependencies,
                (DependencyOption("gui", ("qtpy", "PySide6")),),
            )
            self.assertEqual(
                project.dependency_groups,
                (
                    DependencyOption("dev", ("ruff",), ("test",)),
                    DependencyOption("test", ("pytest",)),
                ),
            )
            self.assertEqual(project.selected_extras, ("gui",))
            self.assertEqual(project.selected_groups, ("dev",))

    def test_build_system_marks_a_source_project_for_editable_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo"
''',
                encoding="utf-8",
            )

            project = load_project_definition(root)

            self.assertTrue(project.has_build_system)

    def test_project_definition_ignores_existing_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\ndependencies = ["source==1.0"]\n',
                encoding="utf-8",
            )
            (root / "pylock.toml").write_text(
                "this is deliberately not valid TOML",
                encoding="utf-8",
            )

            project = load_project_definition(root)

            self.assertEqual(project.metadata_file, root / "pyproject.toml")
            self.assertEqual(
                project.requirements,
                (PackageRequirement("source", specifiers=(("==", "1.0"),)),),
            )

    def test_loads_pep508_dependency_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"
dependencies = [
    "tomli>=1.1; python_version < '3.11'",
    "tomli>=2; python_version >= '3.11'",
]
''',
                encoding="utf-8",
            )

            project = load_project_definition(root)

        self.assertEqual(
            project.requirements,
            (
                PackageRequirement(
                    "tomli",
                    specifiers=((">=", "1.1"),),
                    marker="python_version < '3.11'",
                ),
                PackageRequirement(
                    "tomli",
                    specifiers=((">=", "2"),),
                    marker="python_version >= '3.11'",
                ),
            ),
        )
        self.assertEqual(
            project.requirements[0].text,
            "tomli>=1.1; python_version < '3.11'",
        )

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
sha256 = "{_PACKAGE_SHA256}"
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
            self.assertEqual(
                project.packages[0],
                PackagePin(
                    "example-package",
                    "2.0.post1",
                    (
                        PackageArtifact(
                            "wheel",
                            "example_package-2.0.post1-py3-none-any.whl",
                            (
                                "https://example.invalid/"
                                "example_package-2.0.post1-py3-none-any.whl"
                            ),
                            (("sha256", _PACKAGE_SHA256),),
                        ),
                    ),
                ),
            )

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

    def test_pyproject_accepts_unpinned_and_ranged_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                (
                    '[project]\nname = "demo"\n'
                    'dependencies = ["demo", "requests>=2.31,<3"]\n'
                ),
                encoding="utf-8",
            )

            project = load_project(root)

            self.assertEqual(
                tuple(requirement.text for requirement in project.requirements),
                ("demo", "requests>=2.31,<3"),
            )

    def test_loads_legacy_poetry_runtime_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[tool.poetry]
name = "frogmouth"
version = "0.9.2"

[tool.poetry.dependencies]
python = "^3.8"
textual = "==0.53.1"
typing-extensions = "^4.5.0"
httpx = "^0.24.1"
xdg = "^6.0.0"
optional-demo = { version = "^2.1", optional = true }

[tool.poetry.group.dev.dependencies]
pylint = "^2.17.1"
''',
                encoding="utf-8",
            )

            project = load_project_definition(root)

            self.assertEqual(project.requires_python, ">=3.8,<4.0")
            self.assertEqual(
                tuple(requirement.text for requirement in project.requirements),
                (
                    "textual==0.53.1",
                    "typing-extensions>=4.5.0,<5.0.0",
                    "httpx>=0.24.1,<0.25.0",
                    "xdg>=6.0.0,<7.0.0",
                ),
            )
            self.assertEqual(
                project.dependency_groups,
                (
                    DependencyOption(
                        "dev",
                        ("pylint>=2.17.1,<3.0.0",),
                    ),
                ),
            )

    def test_loads_and_combines_poetry_dependency_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "example"

[dependency-groups]
lint = ["ruff>=0.14"]
dev = [{ include-group = "lint" }]

[tool.poetry.dev-dependencies]
coverage = "^7.0"

[tool.poetry.group.test.dependencies]
pytest = "^8.0"

[tool.poetry.group.dev]
optional = true
include-groups = ["test"]

[tool.poetry.group.dev.dependencies]
tox = "*"
''',
                encoding="utf-8",
            )

            project = load_project_definition(root)

            self.assertEqual(
                project.dependency_groups,
                (
                    DependencyOption(
                        "dev",
                        ("coverage>=7.0,<8.0", "tox"),
                        ("lint", "test"),
                    ),
                    DependencyOption("lint", ("ruff>=0.14",)),
                    DependencyOption("test", ("pytest>=8.0,<9.0",)),
                ),
            )

    def test_rejects_unsupported_poetry_group_dependency_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[tool.poetry]
name = "example"

[tool.poetry.group.dev.dependencies]
demo = { path = "../demo" }
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                NodePhellError,
                "unsupported Poetry dependency field 'path'",
            ):
                load_project_definition(root)

    def test_rejects_unsupported_legacy_poetry_dependency_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[tool.poetry]
name = "example"

[tool.poetry.dependencies]
python = "^3.11"
demo = { git = "https://example.invalid/demo.git" }
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                NodePhellError,
                "unsupported Poetry dependency field 'git'",
            ):
                load_project_definition(root)

    def test_pyproject_rejects_unsupported_direct_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                (
                    '[project]\nname = "demo"\n'
                    'dependencies = ["demo @ https://example.invalid/demo.whl"]\n'
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(NodePhellError, "unsupported"):
                load_project(root)

    def test_loads_backend_supplied_dynamic_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "1.0"
dynamic = ["dependencies"]

[tool.setuptools.dynamic]
dependencies = { file = ["requirements.txt"] }
''',
                encoding="utf-8",
            )

            project = load_project_definition(root)

            self.assertTrue(project.dynamic_dependencies)
            self.assertEqual(project.requirements, ())

    def test_rejects_static_and_dynamic_dependencies_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"
dynamic = ["dependencies"]
dependencies = ["requests"]
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                NodePhellError, "both static and dynamic"
            ):
                load_project_definition(root)

    def test_rejects_dynamic_fields_needed_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "demo"
dynamic = ["optional-dependencies"]
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                NodePhellError,
                "declare it statically.*NodePhell can inspect it",
            ):
                load_project_definition(root)

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

    def test_loads_project_bundled_application_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "cad-demo"

[tool.nodephell.application]
adapter = "nodephell-plugins/freecad"
executable = "build/bin/FreeCADCmd"
name = "FreeCAD"
''',
                encoding="utf-8",
            )

            project = load_project_definition(root)

            self.assertEqual(
                project.application,
                ApplicationDeclaration(
                    Path("nodephell-plugins/freecad"),
                    Path("build/bin/FreeCADCmd"),
                    "FreeCAD",
                ),
            )

    def test_rejects_application_path_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '''[project]
name = "unsafe"

[tool.nodephell.application]
adapter = "../adapter"
''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(NodePhellError, "project-relative"):
                load_project_definition(root)

    def test_package_pin_rejects_path_components(self) -> None:
        with self.assertRaises(NodePhellError):
            PackagePin("demo", "../../outside")


if __name__ == "__main__":
    unittest.main()
