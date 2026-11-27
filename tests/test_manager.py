# SPDX-License-Identifier: GPL-3.0-only

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from nodephell.cli import main
from nodephell.errors import NodePhellError
from nodephell.host import EmbeddedHost, load_hosts, register_probed_host
from nodephell.maintenance import clean_store, remove_unused_releases, validate_store
from nodephell.manager import _select, manage, parse_selection
from nodephell.metadata import Project
from nodephell.references import inspect_project_references, record_project_reference
from nodephell.runtime import Runtime, interpreter_store, load_registry, register_runtime
from nodephell.store import PackageSelection, stored_release_path, write_release_manifest
from tests.test_runtime import artifact
from tests.test_store import locked_package, write_distribution_metadata


class ManagerTests(unittest.TestCase):
    def run_menu(self, home, answers):
        replies = iter(answers)
        output = []
        manage(home, prompt=lambda _: next(replies), announce=output.append)
        return "\n".join(output)

    def add_runtime(self, home, *, managed=False, version="3.13.11"):
        abi = "cpython-" + "".join(version.split(".")[:2]) + "-x86_64-linux-gnu"
        locked = artifact(version=version) if managed else None
        root = interpreter_store(version, abi, home, locked) if managed else home / "external" / version
        executable = root / "bin/python3"
        executable.parent.mkdir(parents=True)
        executable.touch()
        runtime = Runtime("cpython", version, executable.resolve(), abi, "linux-x86_64")
        with patch("nodephell.runtime.probe_runtime", return_value=runtime):
            return register_runtime(executable, user_home=home, artifact=locked)

    def add_package(self, home, runtime, name="demo", digest="a"):
        package = locked_package(name, digest_character=digest)
        release = stored_release_path(package, runtime, home)
        write_distribution_metadata(release, package.name, package.version)
        (release / "value.py").write_text("value = 1\n")
        write_release_manifest(package, runtime, release)
        return package, release

    def reference(self, home, runtime, packages=()):
        root = home / "project"
        root.mkdir()
        lock = root / "pylock.toml"
        lock.write_text('lock-version = "1.0"\n')
        project = Project(root, lock, None, tuple(packages))
        return record_project_reference(project, runtime, PackageSelection(()), home)

    def test_selection_ranges_duplicates_and_bounds(self):
        self.assertEqual(parse_selection("1, 3-5 3", 5), (0, 2, 3, 4))
        self.assertEqual(parse_selection("all", 2), (0, 1))
        for text in ("0", "6", "3-2", "1-9999999999", "bad", "1-2-3"):
            with self.subTest(text=text), self.assertRaises(NodePhellError):
                parse_selection(text, 5)

    def test_missing_runtime_can_be_listed_and_unregistered_without_deleting_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            runtime.executable.unlink()
            with self.assertRaisesRegex(NodePhellError, "missing"):
                load_registry(home)
            self.assertEqual(load_registry(home, require_executables=False), (runtime,))
            output = self.run_menu(home, ("1", "all", "u", "yes", "q"))
            self.assertIn("missing executable", output)
            self.assertEqual(load_registry(home), ())
            self.assertTrue(runtime.executable.parent.is_dir())

    def test_blank_confirmation_keeps_registration_and_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home, managed=True)
            self.run_menu(home, ("1", "1", "d", "", "q"))
            self.assertEqual(load_registry(home), (runtime,))
            self.assertTrue(runtime.executable.exists())

    def test_multiple_missing_runtime_registrations_can_be_removed_together(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            first = self.add_runtime(home, version="3.12.16")
            second = self.add_runtime(home, version="3.13.11")
            first.executable.unlink()
            second.executable.unlink()
            output = self.run_menu(home, ("1", "1-2", "u", "yes", "q"))
            self.assertEqual(output.count("Unregistered (files kept):"), 2)
            self.assertEqual(load_registry(home), ())

    def test_external_runtime_deletion_is_refused_but_managed_unused_one_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            external = self.add_runtime(home)
            output = self.run_menu(home, ("1", "1", "d", "q"))
            self.assertIn("Cannot delete external", output)
            self.assertTrue(external.executable.exists())
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home, managed=True)
            self.run_menu(home, ("1", "1", "d", "yes", "q"))
            self.assertFalse(runtime.executable.exists())
            self.assertEqual(load_registry(home), ())

    def test_referenced_runtime_deletion_keeps_registration_and_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home, managed=True)
            self.reference(home, runtime)
            output = self.run_menu(home, ("1", "1", "d", "yes", "q"))
            self.assertIn("still used", output)
            self.assertEqual(load_registry(home), (runtime,))
            self.assertTrue(runtime.executable.exists())

    def test_missing_host_can_be_unregistered_without_loading_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            host = EmbeddedHost("example", "1.0", runtime.executable, runtime)
            register_probed_host(host, home)
            runtime.executable.unlink()
            with self.assertRaisesRegex(NodePhellError, "missing"):
                load_hosts(home)
            output = self.run_menu(home, ("4", "1", "u", "yes", "q"))
            self.assertIn("Unregistered", output)
            self.assertEqual(load_hosts(home), ())

    def test_package_inventory_is_metadata_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            _, release = self.add_package(home, runtime)
            with patch("nodephell.maintenance.release_contents", side_effect=AssertionError("hashed")):
                output = self.run_menu(home, ("2", "", "q"))
            self.assertIn("integrity not checked", output)
            self.assertTrue(release.exists())

    def test_metadata_inventory_does_not_claim_content_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            _, release = self.add_package(home, runtime)
            (release / "value.py").write_text("value = 2\n")
            self.assertFalse(validate_store(home, verify_contents=False).issues)
            self.assertTrue(validate_store(home).issues)

    def test_inventory_handles_a_relocated_data_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            destination = home / "data-on-another-disk"
            destination.mkdir()
            (home / ".python").symlink_to(destination, target_is_directory=True)
            runtime = self.add_runtime(home)
            _, release = self.add_package(home, runtime)
            output = self.run_menu(home, ("2", "", "q"))
            self.assertIn("demo/1.2.3", output)
            self.assertTrue(release.exists())

    def test_selected_unused_package_is_removed_without_touching_other_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            _, first = self.add_package(home, runtime, "first", "a")
            _, second = self.add_package(home, runtime, "second", "b")
            output = self.run_menu(home, ("2", "1", "yes", "q"))
            self.assertIn("Removed:", output)
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())

    def test_even_damaged_package_is_not_removed_as_unused_when_referenced(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            package, release = self.add_package(home, runtime)
            self.reference(home, runtime, (package,))
            (release / "value.py").write_text("changed = True\n")
            result = remove_unused_releases((release.parent,), home)
            self.assertEqual(result.removed, ())
            self.assertEqual(result.skipped, (release.parent,))
            self.assertTrue(release.exists())

    def test_cleanup_only_removes_selected_current_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            _, first = self.add_package(home, runtime, "first", "a")
            _, second = self.add_package(home, runtime, "second", "b")
            output = self.run_menu(home, ("6", "1", "yes", "q"))
            self.assertIn("Removed:", output)
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())

    def test_cleanup_rechecks_when_selected_release_becomes_referenced(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            package, release = self.add_package(home, runtime)
            answers = iter(("6", "1", "q"))
            def prompt(message):
                if message.startswith("Proceed"):
                    self.reference(home, runtime, (package,))
                    return "yes"
                return next(answers)
            manage(home, prompt=prompt, announce=lambda _: None)
            self.assertTrue(release.exists())

    def test_outside_path_cannot_be_selected_for_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            outside = home / "precious.txt"
            outside.write_text("keep")
            result = clean_store(home, apply=True, selected=(outside,))
            self.assertEqual(result.skipped, (outside,))
            self.assertEqual(outside.read_text(), "keep")

    def test_unregister_project_keeps_project_files_and_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            package, release = self.add_package(home, runtime)
            reference = self.reference(home, runtime, (package,))
            self.run_menu(home, ("3", "all", "yes", "q"))
            self.assertEqual(inspect_project_references(home), ((), ()))
            self.assertTrue(reference.metadata_file.exists())
            self.assertTrue(release.exists())

    def test_corrupt_registry_is_reported_and_menu_remains_usable(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            registry = home / ".python/runtimes/registry.json"
            registry.write_text("broken json")
            output = self.run_menu(home, ("1", "q"))
            self.assertIn("cannot read runtime registry", output)
            self.assertEqual(registry.read_text(), "broken json")
            self.assertTrue(runtime.executable.exists())

    def test_eof_and_invalid_menu_choices_do_not_change_registrations(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            runtime = self.add_runtime(home)
            output = self.run_menu(home, ("bad", "q"))
            self.assertIn("Choose a listed number", output)
            def eof(_):
                raise EOFError
            manage(home, prompt=eof, announce=lambda _: None)
            self.assertEqual(load_registry(home), (runtime,))

    @patch("nodephell.cli.manage")
    def test_cli_dispatches_manager(self, manage_mock):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["manage"]), 0)
        manage_mock.assert_called_once_with()

    def test_terminal_colors_distinguish_numbers_and_wrap_long_paths(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        output = Terminal()
        path = Path("/store/" + "long-directory/" * 8 + "python3")
        rows = [(path, "a-long-runtime-identifier-" * 3 + ": missing executable; external")]
        with (
            redirect_stdout(output),
            patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True),
            patch("nodephell.manager.shutil.get_terminal_size", return_value=os.terminal_size((40, 24))),
        ):
            self.assertEqual(_select(rows, lambda _: "", print), ())
        text = output.getvalue()
        self.assertIn("\033[1;96m1.\033[0m", text)
        self.assertIn("\033[1;93m", text)
        plain = re.sub(r"\033\[[0-9;]*m", "", text)
        self.assertTrue(all(len(line) <= 40 for line in plain.splitlines()))
        self.assertIn(str(path), "".join(plain.split()))
        self.assertIn("     Path: ", plain)

    def test_menu_colors_respect_no_color_dumb_terminals_and_redirection(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        cases = (
            (Terminal, {"TERM": "xterm-256color", "NO_COLOR": "1"}),
            (Terminal, {"TERM": "dumb"}),
            (io.StringIO, {"TERM": "xterm-256color"}),
        )
        for stream_type, environment in cases:
            with self.subTest(environment=environment, stream=stream_type):
                output = stream_type()
                with redirect_stdout(output), patch.dict(os.environ, environment, clear=True):
                    manage(prompt=lambda _: "q")
                self.assertNotIn("\033[", output.getvalue())
                self.assertIn("1. Runtimes", output.getvalue())


if __name__ == "__main__":
    unittest.main()
