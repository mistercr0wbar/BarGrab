"""Stop actually stops, including during the between-page delay."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grab_core as core


class StopTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lib = core.Library(Path(directory.name))

    def test_stop_during_first_page_skips_the_rest(self):
        cancel = core.Cancel()
        calls: list[str] = []

        def fake(url, library, opts, result, cancel=None):
            calls.append(url)
            cancel.stop()
            return core.PageExtract(
                clip_links=["https://site.example/gifs/abcdefg"]
            )

        with patch.object(core, "capture_html_only", side_effect=fake):
            result = core.crawl(
                ["https://site.example/gifs/listingpage"],
                self.lib,
                core.CrawlOptions(
                    use_browser=False, gallery=True, delay=5, cap=40
                ),
                cancel=cancel,
            )
        self.assertTrue(result.stopped)
        self.assertEqual(calls, ["https://site.example/gifs/listingpage"])
        self.assertEqual(result.pages, 1)

    def test_stop_does_not_wait_out_the_delay(self):
        cancel = core.Cancel()
        calls: list[str] = []

        def fake(url, library, opts, result, cancel=None):
            calls.append(url)
            if len(calls) == 1:
                return core.PageExtract(
                    clip_links=["https://site.example/gifs/clippage1"]
                )
            return core.PageExtract()

        def stopper(url, library, opts, result, cancel=None):
            out = fake(url, library, opts, result, cancel)
            # After the listing is in, Stop is hit before the 8s delay.
            if len(calls) == 1:
                cancel.stop()
            return out

        t0 = time.monotonic()
        with patch.object(core, "capture_html_only", side_effect=stopper):
            result = core.crawl(
                ["https://site.example/gifs/listingpage"],
                self.lib,
                core.CrawlOptions(
                    use_browser=False, gallery=True, delay=8, cap=40
                ),
                cancel=cancel,
            )
        elapsed = time.monotonic() - t0
        self.assertTrue(result.stopped)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(calls, ["https://site.example/gifs/listingpage"])

    def test_cancel_stop_with_no_browser_is_safe(self):
        cancel = core.Cancel()
        cancel.stop()
        self.assertTrue(cancel.is_set())
        with self.assertRaises(core.Stopped):
            cancel.raise_if_set()
