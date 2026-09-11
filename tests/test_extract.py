"""HTML extraction, listing links, and URL classification. No network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grab_core as core


VIDEO_PAGE = """
<html><body>
  <div class="overlay" style="pointer-events:none"></div>
  <video autoplay loop muted>
    <source src="/clips/cat.mp4" type="video/mp4">
    <source src="/clips/cat.webm" type="video/webm">
  </video>
  <img src="/thumbs/pixel.gif">
</body></html>
"""

WEBP_PAGE = """
<html><body>
  <img data-src="https://cdn.example/a.webp" srcset="https://cdn.example/a.webp 1x, https://cdn.example/a@2.webp 2x">
  <meta property="og:video" content="https://cdn.example/og.mp4">
</body></html>
"""

LISTING_PAGE = """
<html><body>
  <a href="/gifs/longslugone">one</a>
  <a href="/gifs/longslugtwo">two</a>
  <a href="/tags/blonde">tag</a>
  <a href="/search?q=x">search</a>
  <a href="https://other.example/gifs/nope">offsite</a>
  <a href="/style.css">css</a>
  <iframe src="/embed/longslugone"></iframe>
</body></html>
"""

JUNK_PAGE = """
<html><body>
  <img src="https://www.google-analytics.com/collect.gif">
  <img src="/favicon.ico">
  <script src="/app.js"></script>
  <video src="blob:https://site.example/abc-def"></video>
</body></html>
"""


class ClassifyTests(unittest.TestCase):
    def test_url_extension(self):
        self.assertEqual(core.classify("https://x/a.mp4"), "mp4")
        self.assertEqual(core.classify("https://x/a.webm?foo=1"), "webm")
        self.assertEqual(core.classify("https://x/a.webp"), "webp")

    def test_mime_wins(self):
        self.assertEqual(core.classify("https://x/file", "video/mp4"), "mp4")
        self.assertEqual(core.classify("https://x/file", "image/webp; charset=binary"), "webp")

    def test_junk(self):
        self.assertTrue(core.is_junk_url("https://www.google-analytics.com/ga.js"))
        self.assertFalse(core.is_junk_url("https://cdn.example/clip.mp4"))

    def test_parse_urls_keeps_http_and_dedupes(self):
        text = "https://a.example/1\nhttps://a.example/1\nnot-a-url\nhttps://b.example/2#frag"
        urls = core.parse_urls(text)
        self.assertEqual(urls, ["https://a.example/1", "https://b.example/2"])


class SniffTests(unittest.TestCase):
    def test_gif(self):
        self.assertEqual(core.sniff(b"GIF89a" + b"\x00" * 20), "gif")

    def test_webp(self):
        data = b"RIFF" + (30).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 16
        self.assertEqual(core.sniff(data), "webp")

    def test_still_webp_is_not_motion(self):
        still = b"RIFF" + (30).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * 16
        self.assertFalse(core.is_animated_webp(still))
        self.assertFalse(core.is_motion(still, "webp"))
        self.assertFalse(core.is_motion(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "png"))

    def test_anmf_chunk_is_motion(self):
        anim = (
            b"RIFF" + (40).to_bytes(4, "little") + b"WEBP"
            + b"VP8X" + b"\x00\x00\x00\x0a" + b"ANMF" + b"\x00" * 16
        )
        self.assertTrue(core.is_animated_webp(anim))
        self.assertTrue(core.is_motion(anim, "webp"))

    def test_mp4(self):
        data = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
        self.assertEqual(core.sniff(data), "mp4")

    def test_webm(self):
        self.assertEqual(core.sniff(b"\x1a\x45\xdf\xa3" + b"\x00" * 16), "webm")

    def test_png_and_jpeg(self):
        self.assertEqual(core.sniff(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8), "png")
        self.assertEqual(core.sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 12), "jpg")


def _gif(n: int) -> bytes:
    return (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
        b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        + b"\x00" * n
    )


def _webp(n: int, animated: bool = False) -> bytes:
    if animated:
        return b"RIFF" + (n + 20).to_bytes(4, "little") + b"WEBPANMF" + b"\x00" * n
    return b"RIFF" + (n + 20).to_bytes(4, "little") + b"WEBPVP8 " + b"\x00" * n


class FullsizeTests(unittest.TestCase):
    def test_gif_beats_a_bigger_webp(self):
        gif = _gif(40_000)
        webp = _webp(200_000, animated=True)
        picked = core.pick_fullsize([
            (webp, "image/webp", "https://x/a.webp"),
            (gif, "image/gif", "https://x/a.gif"),
        ])
        self.assertIsNotNone(picked)
        self.assertTrue(picked[2].endswith(".gif"))

    def test_still_webp_is_never_picked(self):
        still = _webp(80_000, animated=False)
        self.assertIsNone(core.pick_fullsize([
            (still, "image/webp", "https://x/poster.webp"),
        ]))

    def test_tiny_gif_loses_to_fullsize_webp(self):
        gif = _gif(100)
        webp = _webp(80_000, animated=True)
        picked = core.pick_fullsize([
            (gif, "image/gif", "https://x/tiny.gif"),
            (webp, "image/webp", "https://x/full.webp"),
        ])
        self.assertIsNotNone(picked)
        self.assertTrue(picked[2].endswith(".webp"))

    def test_bigger_of_same_kind_wins(self):
        a = _gif(40_000)
        b = _gif(90_000)
        picked = core.pick_fullsize([
            (a, "image/gif", "https://x/small.gif"),
            (b, "image/gif", "https://x/big.gif"),
        ])
        self.assertEqual(picked[2], "https://x/big.gif")


class ExtractTests(unittest.TestCase):
    def test_video_sources_and_relative_urls(self):
        page = core.extract_html(VIDEO_PAGE, "https://site.example/watch/1")
        urls = {item.url for item in page.media}
        self.assertIn("https://site.example/clips/cat.mp4", urls)
        self.assertIn("https://site.example/clips/cat.webm", urls)
        kinds = {item.url: item.kind for item in page.media}
        self.assertEqual(kinds["https://site.example/clips/cat.mp4"], "mp4")

    def test_webp_srcset_and_og_video(self):
        page = core.extract_html(WEBP_PAGE, "https://site.example/")
        urls = {item.url for item in page.media}
        self.assertIn("https://cdn.example/a.webp", urls)
        self.assertIn("https://cdn.example/a@2.webp", urls)
        self.assertIn("https://cdn.example/og.mp4", urls)

    def test_blob_is_noted_and_not_fetchable(self):
        page = core.extract_html(JUNK_PAGE, "https://site.example/gifs/x")
        blobs = [item for item in page.media if item.url.startswith("blob:")]
        self.assertEqual(len(blobs), 1)
        self.assertFalse(core.is_fetchable(blobs[0].url))
        urls = {item.url for item in page.media}
        self.assertNotIn("https://www.google-analytics.com/collect.gif", urls)

    def test_listing_keeps_clip_paths_drops_tags_and_offsite(self):
        page = core.extract_html(LISTING_PAGE, "https://site.example/gifs")
        self.assertIn("https://site.example/gifs/longslugone", page.clip_links)
        self.assertIn("https://site.example/gifs/longslugtwo", page.clip_links)
        self.assertIn("https://site.example/embed/longslugone", page.clip_links)
        self.assertNotIn("https://site.example/tags/blonde", page.clip_links)
        self.assertNotIn("https://other.example/gifs/nope", page.clip_links)
        self.assertNotIn("https://site.example/style.css", page.clip_links)
