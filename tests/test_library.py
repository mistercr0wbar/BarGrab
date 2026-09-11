"""Inbox, keep, skip, and hash dedupe. No ffmpeg, no network."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grab_core as core

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
# 1x1 GIF is under MIN_BYTES. Pad so the library will keep it, without
# changing the GIF header sniff.
PADDED_GIF = TINY_GIF + b"\x00" * (core.MIN_BYTES)
PADDED_GIF_2 = TINY_GIF + b"\x01" * (core.MIN_BYTES)
PADDED_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * core.MIN_BYTES


class LibraryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lib = core.Library(Path(directory.name))

    def test_save_then_duplicate(self):
        first = self.lib.save_bytes(
            PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        self.assertIsInstance(first, core.InboxItem)
        self.assertEqual(first.kind, "gif")
        self.assertTrue(first.path.exists())
        again = self.lib.save_bytes(
            PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        self.assertEqual(again, "duplicate")
        self.assertEqual(len(self.lib.inbox_items()), 1)

    def test_skip_remembers_hash_and_deletes_file(self):
        item = self.lib.save_bytes(
            PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        path = item.path
        self.lib.skip(item)
        self.assertFalse(path.exists())
        self.assertEqual(self.lib.inbox_items(), [])
        again = self.lib.save_bytes(
            PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        self.assertEqual(again, "skip")

    def test_keep_copies_a_gif_without_ffmpeg(self):
        item = self.lib.save_bytes(
            PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        kept = self.lib.keep(item)
        self.assertEqual(kept.suffix, ".gif")
        self.assertTrue(kept.exists())
        self.assertEqual(kept.read_bytes()[:6], b"GIF89a")
        self.assertEqual(self.lib.inbox_items(), [])
        again = self.lib.save_bytes(
            PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        self.assertEqual(again, "duplicate")

    def test_keep_video_calls_convert(self):
        item = self.lib.save_bytes(
            PADDED_MP4, source_url="https://x/a.mp4", page_url="https://x/"
        )
        self.assertEqual(item.kind, "mp4")

        def fake_convert(src, dest, ffmpeg=None):
            dest.write_bytes(b"RIFF" + (30).to_bytes(4, "little") + b"WEBP" + b"\x00" * 8)
            return dest

        with patch.object(core, "convert_video", side_effect=fake_convert):
            kept = self.lib.keep(item)
        self.assertEqual(kept.suffix, ".webp")
        self.assertTrue(kept.exists())
        self.assertFalse(item.path.exists())

    def test_two_different_gifs_both_land(self):
        a = self.lib.save_bytes(PADDED_GIF, source_url="https://x/a.gif", page_url="https://x/")
        b = self.lib.save_bytes(PADDED_GIF_2, source_url="https://x/b.gif", page_url="https://x/")
        self.assertIsInstance(a, core.InboxItem)
        self.assertIsInstance(b, core.InboxItem)
        self.assertEqual(len(self.lib.inbox_items()), 2)

    def test_tiny_is_refused(self):
        outcome = self.lib.save_bytes(
            TINY_GIF, source_url="https://x/a.gif", page_url="https://x/"
        )
        self.assertEqual(outcome, "tiny")
