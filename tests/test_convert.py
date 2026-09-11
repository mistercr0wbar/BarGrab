"""ffmpeg command shape. A live encode is skipped unless ffmpeg is installed."""

from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grab_core as core


class CommandTests(unittest.TestCase):
    def test_webp_command_loops_and_uses_libwebp(self):
        cmd = core.webp_command("/usr/bin/ffmpeg", Path("in.mp4"), Path("out.webp"))
        self.assertIn("-loop", cmd)
        self.assertEqual(cmd[cmd.index("-loop") + 1], "0")
        self.assertIn("libwebp", cmd)
        self.assertTrue(cmd[-1].endswith("out.webp"))

    def test_gif_fallback_uses_a_palette(self):
        cmd = core.gif_command("/usr/bin/ffmpeg", Path("in.mp4"), Path("out.gif"))
        joined = " ".join(cmd)
        self.assertIn("palettegen", joined)
        self.assertTrue(cmd[-1].endswith("out.gif"))

    def test_convert_without_ffmpeg_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.mp4"
            src.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
            dest = Path(tmp) / "out.webp"
            with unittest.mock.patch.object(core, "find_ffmpeg", return_value=None):
                with self.assertRaises(core.ConvertError):
                    core.convert_video(src, dest, ffmpeg=None)


@unittest.skipUnless(core.find_ffmpeg(), "ffmpeg not on PATH")
class LiveEncodeTests(unittest.TestCase):
    def test_lavfi_color_becomes_webp_or_gif(self):
        ffmpeg = core.find_ffmpeg()
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.mp4"
            dest = Path(tmp) / "out.webp"
            make = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=32x32:d=0.4",
                str(src),
            ]
            import subprocess
            built = subprocess.run(make, capture_output=True, timeout=30)
            if built.returncode != 0:
                self.skipTest("ffmpeg could not mint a test mp4")
            written = core.convert_video(src, dest, ffmpeg)
            self.assertGreater(written.stat().st_size, 0)
            kind = core.sniff(written.read_bytes())
            self.assertIn(kind, ("webp", "gif"))
            self.assertIn(written.suffix, (".webp", ".gif"))
