# SPDX-License-Identifier: GPL-3.0-only

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nodephell.cli import main
from nodephell.discovery import discover_dependencies, scan_imports
from nodephell.errors import NodePhellError
from nodephell.metadata import load_project_definition


class DiscoveryTests(unittest.TestCase):
    def write(self, root: Path, name: str, text: str = "") -> Path:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_filters_stdlib_src_namespace_and_sibling_modules_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "main.py", "import os, requests, internal\nfrom package import thing\nraise RuntimeError('must not execute')\n")
            self.write(root, "src/package/thing.py", "from . import other\nimport helper\nimport numpy.linalg as la\n")
            self.write(root, "src/package/helper.py")
            self.write(root, "internal.py")

            scan = scan_imports(root)

        self.assertEqual({x.module for x in scan.imports}, {"requests", "numpy"})
        self.assertIn("os", scan.standard_library)
        self.assertEqual(set(scan.local_modules), {"internal", "package", "helper"})

    def test_nested_tests_do_not_hide_runtime_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "main.py", "import requests\n")
            self.write(root, "tests/requests.py")
            scan = scan_imports(root)
        self.assertEqual([x.module for x in scan.imports], ["requests"])

    def test_context_preserves_optional_conditional_function_and_test_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", """try:
    import fast_backend
except (ImportError, ModuleNotFoundError):
    import slow_backend
if TYPE_CHECKING:
    import typing_helper
def process():
    import requests
import importlib
importlib.import_module('dynamic_plugin')
""")
            self.write(root, "examples/demo.py", "import plotting\n")
            scan = scan_imports(root)

        contexts = {item.module: item.context for item in scan.imports}
        self.assertIn("optional: import-error fallback", contexts["fast_backend"])
        self.assertIn("exception fallback", contexts["slow_backend"])
        self.assertIn("conditional: TYPE_CHECKING", contexts["typing_helper"])
        self.assertIn("inside function: process", contexts["requests"])
        self.assertIn("tests/examples/docs", contexts["plotting"])
        self.assertTrue(any("dynamic import" in warning for warning in scan.warnings))

    def test_ignores_generated_environments_symlinks_and_user_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import requests\n")
            for directory in (".venv", "venv_rocm", "node_modules", "build", "vendor"):
                self.write(root, f"{directory}/hidden.py", "import unwanted\n")
            self.write(root, "environment/pyvenv.cfg")
            self.write(root, "environment/library.py", "import unwanted\n")
            self.write(root, "target.txt", "import unwanted\n")
            (root / "linked.py").symlink_to(root / "target.txt")
            (root / "linked-directory").symlink_to(root / "vendor", target_is_directory=True)
            scan = scan_imports(root, ("vendor/**",))
        self.assertEqual(scan.files, 1)
        self.assertEqual([x.module for x in scan.imports], ["requests"])

    def test_reports_parse_errors_and_honors_source_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "broken.py", "def broken(\n")
            (root / "latin.py").write_bytes(b"# coding: latin-1\n# caf\xe9\nimport requests\n")
            scan = scan_imports(root)
        self.assertEqual([x.module for x in scan.imports], ["requests"])
        self.assertIn("broken.py", scan.warnings[0])

    def test_reports_dynamic_import_alias_in_function_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "from importlib import import_module as load\ndef app(backend=load('plugin')):\n    pass\n")
            scan = scan_imports(root)
        self.assertTrue(any("dynamic import" in warning for warning in scan.warnings))

    def test_creates_reviewed_declaration_with_aliases_versions_and_skips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "from PIL import Image\nimport requests\nimport yaml\n")
            answers = iter(("demo", "", "3.12", "", "10.4", "-", "", "", "", "y"))
            messages = []
            discover_dependencies(root, prompt=lambda _: next(answers), announce=messages.append)
            definition = load_project_definition(root)
            self.assertFalse((root / "nodephell.lock.toml").exists())
        self.assertEqual(definition.requires_python, ">=3.12,<3.13")
        self.assertEqual([x.text for x in definition.requirements], ["Pillow==10.4", "PyYAML"])
        self.assertTrue(any("Proposed pyproject.toml:" in line for line in messages))

    def test_optional_test_and_application_imports_are_skipped_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "try:\n    import fast_backend\nexcept ImportError:\n    pass\nimport pcbnew\n")
            self.write(root, "tests/test_app.py", "import pytest\n")
            answers = iter(("demo", "", "", "", "", "", "", "y"))
            discover_dependencies(root, prompt=lambda _: next(answers), announce=lambda _: None,
                                  application="kicad")
            self.assertEqual(load_project_definition(root).requirements, ())

    def test_unknown_name_can_be_corrected_and_ambiguous_import_requires_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import custom_name\nimport cv2\n")
            answers = iter(("demo", "", "", "actual-package", ">=2,<3", "opencv-python-headless", "", "", "y"))
            discover_dependencies(root, prompt=lambda _: next(answers), announce=lambda _: None)
            deps = load_project_definition(root).requirements
        self.assertEqual([x.text for x in deps], ["actual-package>=2,<3", "opencv-python-headless"])

    def test_two_import_names_do_not_duplicate_same_distribution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import fitz, pymupdf\n")
            answers = iter(("demo", "", "", "", "", "", "", "y"))
            discover_dependencies(root, prompt=lambda _: next(answers), announce=lambda _: None)
            self.assertEqual([x.name for x in load_project_definition(root).requirements], ["PyMuPDF"])

    def test_existing_metadata_is_report_only_and_never_prompts_or_changes_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import yaml, requests\n")
            original = '[project]\nname = "demo"\ndependencies = ["requests"]\n'
            path = self.write(root, "pyproject.toml", original)
            output = []
            result = discover_dependencies(root, prompt=lambda _: self.fail("prompted"), announce=output.append)
            self.assertIsNone(result)
            self.assertEqual(path.read_text(), original)
        report = "\n".join(output).split("Possible missing dependencies:")[1]
        self.assertIn("PyYAML", report)
        self.assertNotIn("review requests", report)

    def test_requirements_route_uses_existing_file_without_parsing_source_or_downloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "requirements.txt", "--extra-index-url https://example.invalid\nrequests>=2\n")
            self.write(root, "app.py", "invalid syntax (\n")
            answers = iter(("1", "demo", "", "", "y"))
            output = []
            discover_dependencies(root, prompt=lambda _: next(answers), announce=output.append)
            self.assertTrue((root / "pyproject.toml").is_file())
        self.assertIn("nodephell sync --requirements requirements.txt", "\n".join(output))
        self.assertNotIn("could not scan", "\n".join(output))

    def test_cancel_and_eof_do_not_create_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            answers = iter(("demo", "", "", "", "n"))
            with self.assertRaisesRegex(NodePhellError, "cancelled"):
                discover_dependencies(root, prompt=lambda _: next(answers), announce=lambda _: None)
            self.assertFalse((root / "pyproject.toml").exists())
            def eof(_):
                raise EOFError
            with self.assertRaisesRegex(NodePhellError, "cancelled"):
                discover_dependencies(root, prompt=eof, announce=lambda _: None)

    def test_does_not_replace_file_created_during_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            answers = iter(("demo", "", "", ""))
            def prompt(message):
                if message.startswith("Write"):
                    self.write(root, "pyproject.toml", "another writer\n")
                    return "y"
                return next(answers)
            with self.assertRaisesRegex(NodePhellError, "cannot create"):
                discover_dependencies(root, prompt=prompt, announce=lambda _: None)
            self.assertEqual((root / "pyproject.toml").read_text(), "another writer\n")

    @patch("nodephell.cli.discover_dependencies")
    @patch("nodephell.cli.sync_project")
    def test_cli_routes_exclusions_without_synchronizing(self, sync, discover):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["discover", "/project", "--exclude", "vendor/**"]), 0)
        discover.assert_called_once_with(
            Path("/project"), ("vendor/**",), mappings_file=None, application=None,
        )
        sync.assert_not_called()

    def test_custom_mapping_is_used_in_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import special_import\n")
            mappings = self.write(root, "hints.toml", '[imports]\nspecial_import = ["actual-distribution"]\n')
            answers = iter(("demo", "", "", "", "", "", "y"))
            discover_dependencies(root, prompt=lambda _: next(answers), announce=lambda _: None,
                                  mappings_file=mappings)
            self.assertEqual([x.name for x in load_project_definition(root).requirements],
                             ["actual-distribution"])

    def test_application_name_is_not_globally_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import Part\n")
            answers = iter(("demo", "", "", "", "", "", "y"))
            discover_dependencies(root, prompt=lambda _: next(answers), announce=lambda _: None)
            self.assertEqual([x.name for x in load_project_definition(root).requirements], ["Part"])

    def test_existing_host_metadata_selects_application_hints_without_loading_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "app.py", "import Part\n")
            self.write(root, "pyproject.toml", '[project]\nname="demo"\n[tool.nodephell.host]\nkind="freecad"\nrequires="==1.1.3"\n')
            output = []
            discover_dependencies(root, prompt=lambda _: self.fail("prompted"), announce=output.append)
            self.assertIn("Application-module hints selected for freecad.", output)
            self.assertFalse(any("review Part" in line for line in output))

    @patch("nodephell.cli.discover_dependencies")
    def test_cli_passes_external_mappings_and_application_context(self, discover):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["discover", "/project", "--mappings", "/hints.toml",
                                   "--application", "customcad"]), 0)
        discover.assert_called_once_with(
            Path("/project"), (), mappings_file=Path("/hints.toml"), application="customcad",
        )


if __name__ == "__main__":
    unittest.main()
