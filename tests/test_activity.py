# SPDX-License-Identifier: GPL-3.0-only

import io
import unittest
from contextlib import redirect_stdout

from nodephell.activity import TerminalProgress, activity, working


class ActivityTests(unittest.TestCase):
    def test_redirected_output_gets_a_plain_patience_message(self) -> None:
        output = io.StringIO()

        with activity("Removing unused releases", output):
            pass

        self.assertEqual(
            output.getvalue(),
            "Removing unused releases. This may take a moment.\n",
        )

    def test_plain_progress_callback_receives_work_message(self) -> None:
        messages = []

        with working(messages.append, "Resolving with stock pip"):
            pass

        self.assertEqual(messages, ["Resolving with stock pip"])

    def test_terminal_progress_uses_activity_display(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            with working(TerminalProgress(), "Preparing downloads"):
                pass

        self.assertEqual(
            output.getvalue(),
            "Preparing downloads. This may take a moment.\n",
        )

    def test_rich_progress_callback_controls_work_scope(self) -> None:
        events = []

        class Progress:
            def __call__(self, message):
                events.append(("message", message))

            def working(self, message):
                class Scope:
                    def __enter__(self):
                        events.append(("start", message))

                    def __exit__(self, *unused):
                        events.append(("stop", message))

                return Scope()

        with working(Progress(), "Installing package"):
            events.append(("work", "Installing package"))

        self.assertEqual(
            events,
            [
                ("start", "Installing package"),
                ("work", "Installing package"),
                ("stop", "Installing package"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
