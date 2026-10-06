# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from nodephell.errors import NodePhellError
from nodephell.runtime import (
    Runtime,
    _select_standalone_asset,
    data_root,
    load_registry,
    register_runtime,
    select_runtime,
)
from nodephell.versions import matches_runtime


def runtime(version: str, name: str) -> Runtime:
    return Runtime(
        "cpython",
        version,
        Path("/runtimes") / name,
        f"cpython-{version.replace('.', '')}",
        "linux-x86_64",
    )


class RuntimeTests(unittest.TestCase):
    def test_data_root_honors_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("NODEPHELL_HOME")
            os.environ["NODEPHELL_HOME"] = temporary
            try:
                self.assertEqual(data_root(), Path(temporary) / ".python")
            finally:
                if previous is None:
                    os.environ.pop("NODEPHELL_HOME", None)
                else:
                    os.environ["NODEPHELL_HOME"] = previous

    def test_matches_bounded_requirement(self) -> None:
        self.assertTrue(matches_runtime("3.13.15", ">=3.13,<3.14"))
        self.assertFalse(matches_runtime("3.14.0", ">=3.13,<3.14"))

    def test_matches_development_runtime_when_explicitly_allowed(self) -> None:
        self.assertTrue(
            matches_runtime("3.16.0a0", ">=3.16.0a0,<3.17")
        )

    def test_alpha_runtime_precedes_final_release(self) -> None:
        self.assertFalse(matches_runtime("3.16.0a0", ">=3.16,<3.17"))

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
                        "name": (
                            "cpython-3.12.12+20261003-"
                            "x86_64-unknown-linux-gnu-install_only.tar.gz"
                        ),
                        "browser_download_url": "https://example.invalid/3.12",
                    },
                    {
                        "name": (
                            "cpython-3.13.11+20261003-"
                            "x86_64-unknown-linux-gnu-install_only.tar.gz"
                        ),
                        "browser_download_url": "https://example.invalid/3.13",
                    },
                    {
                        "name": (
                            "cpython-3.13.11+20261003-"
                            "aarch64-unknown-linux-gnu-install_only.tar.gz"
                        ),
                        "browser_download_url": "https://example.invalid/arm",
                    },
                ]
            },
        )

        asset = _select_standalone_asset(">=3.13,<3.14")

        self.assertEqual(asset["version"], "3.13.11")
        self.assertEqual(asset["url"], "https://example.invalid/3.13")


if __name__ == "__main__":
    unittest.main()
