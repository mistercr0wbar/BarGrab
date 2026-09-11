"""ffmpeg command shape. A live encode is skipped unless ffmpeg is installed."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grab_core as core


class CommandTests(unittest.TestCase):
    def test_gif_fallback_uses_a_palette(self):
        cmd = core.gif_command("/usr/bin/ffmpeg", Path("in.mp4"), Path("out.gif"))
        joined = " ".join(cmd)
        self.assertIn("palettegen", joined)
        self.assertTrue(cmd[-1].endswith("out.gif"))

    def test_winget_ffmpeg_is_found_under_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"x")
            with unittest.mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                with unittest.mock.patch.object(core.shutil, "which", return_value=None):
                    self.assertEqual(core.find_ffmpeg(), str(binary))

    def test_playwright_ffmpeg_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "ms-playwright" / "ffmpeg-1011"
            folder.mkdir(parents=True)
            (folder / "ffmpeg-win64.exe").write_bytes(b"x")
            with unittest.mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                with unittest.mock.patch.object(core.shutil, "which", return_value=None):
                    self.assertIsNone(core.find_ffmpeg())

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
            self.assertEqual(written.suffix, ".gif")
            self.assertEqual(core.sniff(written.read_bytes()), "gif")
