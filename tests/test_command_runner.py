# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from nodephell.command_runner import main


class CommandRunnerTests(unittest.TestCase):
    def test_loads_declared_callable_and_forwards_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "example_command.py").write_text(
                "import sys\n"
                "def run():\n"
                "    return 0 if sys.argv == ['example', '--flag'] else 9\n",
                encoding="utf-8",
            )
            sys.path.insert(0, str(root))
            try:
                with patch.object(
                    sys,
                    "argv",
                    [
                        "command_runner.py",
                        "example_command",
                        "run",
                        "example",
                        "--flag",
                    ],
                ):
                    status = main()
            finally:
                sys.path.remove(str(root))
                sys.modules.pop("example_command", None)

        self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
