# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import unittest

from nodephell.errors import NodePhellError
from nodephell.runtime import Runtime, select_runtime
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
    def test_matches_bounded_requirement(self) -> None:
        self.assertTrue(matches_runtime("3.13.15", ">=3.13,<3.14"))
        self.assertFalse(matches_runtime("3.14.0", ">=3.13,<3.14"))

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


if __name__ == "__main__":
    unittest.main()
