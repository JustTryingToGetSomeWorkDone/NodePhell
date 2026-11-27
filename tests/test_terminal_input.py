# SPDX-License-Identifier: GPL-3.0-only

from contextlib import ExitStack, redirect_stdout
import io
import termios
import unittest
from unittest.mock import Mock, patch

from nodephell.terminal_input import read_browser_choice


class Terminal(io.StringIO):
    def isatty(self):
        return True


class BrowserInputTests(unittest.TestCase):
    def read_keys(self, keys, error=None):
        source = Mock()
        source.isatty.return_value = True
        source.fileno.return_value = 17
        original = ["original attributes"]
        output = Terminal()
        with ExitStack() as stack:
            stack.enter_context(patch("sys.stdin", source))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(patch("termios.tcgetattr", return_value=original))
            stack.enter_context(patch("tty.setcbreak"))
            restore = stack.enter_context(patch("termios.tcsetattr"))
            stack.enter_context(patch("nodephell.terminal_input.os.read", side_effect=keys))
            stack.enter_context(patch("nodephell.terminal_input.select.select", return_value=([17], [], [])))
            if error is not None:
                with self.assertRaises(error):
                    read_browser_choice("Choose: ")
                result = None
            else:
                result = read_browser_choice("Choose: ")
            restore.assert_called_once_with(17, termios.TCSADRAIN, original)
        return result

    def test_arrows_work_without_enter(self):
        self.assertEqual(self.read_keys([b"\x1b", b"[", b"C"]), "right")
        self.assertEqual(self.read_keys([b"\x1b", b"O", b"D"]), "left")

    def test_letter_jump_and_editable_numeric_selection(self):
        self.assertEqual(self.read_keys([b"Z"]), "z")
        self.assertEqual(self.read_keys([b"1", b"2", b"\x7f", b"6", b"\n"]), "16")

    def test_terminal_mode_is_restored_after_cancel_and_eof(self):
        self.read_keys([b"\x03"], KeyboardInterrupt)
        self.read_keys([b""], EOFError)

    def test_unhandled_arrow_does_not_become_a_letter_jump(self):
        self.assertEqual(self.read_keys([b"\x1b", b"[", b"A", b"z"]), "z")

    def test_redirected_input_keeps_line_based_fallback(self):
        source = Mock()
        source.isatty.return_value = False
        fallback = Mock(return_value="next")
        with patch("sys.stdin", source), patch("tty.setcbreak") as cbreak:
            self.assertEqual(read_browser_choice("Choose: ", fallback), "next")
        fallback.assert_called_once_with("Choose: ")
        cbreak.assert_not_called()


if __name__ == "__main__":
    unittest.main()
