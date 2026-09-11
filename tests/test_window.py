"""The window itself, built and thrown away.

Skips on a headless box, so it does nothing on the Linux server and does the
real check on a machine with a desktop.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _has_desktop() -> bool:
    try:
        import tkinter
    except ImportError:
        return False
    try:
        probe = tkinter.Tk()
    except Exception:
        return False
    probe.destroy()
    return True


@unittest.skipUnless(_has_desktop(), "no desktop to draw on")
class WindowTests(unittest.TestCase):
    def setUp(self) -> None:
        import bargrab

        self.app = bargrab.BarGrab()
        self.addCleanup(self.app.destroy)

    def test_it_builds_and_has_its_pieces(self):
        self.assertEqual(self.app.title(), "BarGrab")
        for piece in (
            "urls", "listbox", "preview", "preview_frame",
            "grab_btn", "status", "folder",
        ):
            with self.subtest(piece=piece):
                self.assertTrue(hasattr(self.app, piece))
