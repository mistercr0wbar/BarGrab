# BarGrab

Collect GIFs — including the ones that are actually looping videos — then pick
the ones worth adding to BARBIE.

Windows. Run from source. The crawl does not run on the cr0wbox.

## What it does

Paste a GIF page or a gallery URL. Grab. Chromium loads the page and intercepts
what the tab actually downloaded (GIF, animated WebP, MP4, WebM). That is how
it gets past overlay / right-click tricks.

Name a folder in the app (e.g. `whip`). Keep puts files in
`Pictures\BarGrab\keepers\<folder>\`. Multi-select with Ctrl/Shift. Delete
removes; Skip remembers not to grab that clip again.

GIF and WebP are copied as-is. MP4/WebM become animated WebP (GIF if WebP
comes out as a still). You add keepers to BARBIE yourself.

It does **not** pre-size to BARBIE's 320×200 canvas. She keeps originals and
resizes on ingest. A keeper over 12 MB is flagged because she will refuse it.

## Getting it onto the Windows PC

```bat
cd C:\dev
git clone https://github.com/mistercr0wbar/BarGrab.git
cd BarGrab
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
winget install --id Gyan.FFmpeg -e
python bargrab.py
```

The repo is public, so HTTPS does not need a GitHub SSH key. ffmpeg only needs installing once.

Later: `git pull` then `python bargrab.py`. Or double-click `BarGrab.bat`.

Chromium is used automatically when Playwright is installed. ffmpeg is only
needed when you Keep a video.

## Library

Default: `%USERPROFILE%\Pictures\BarGrab`

| Folder / file | What |
|---|---|
| `inbox/` | just grabbed, not decided |
| `keepers/<folder>/` | Keep. Named in the app. These are what you add to BARBIE |
| `skip.json` | hashes of Skip, so a re-crawl does not re-offer them |

Media never goes in git. `.gitignore` blocks `inbox/`, `keepers/`, and every
common media extension. Tests use byte literals, not fixture files.

Settings: `%APPDATA%\BarGrab\settings.json`.

## Keys

In the inbox list: **K** keep, **X** skip, **Del** delete, **Enter** play,
**Ctrl+A** select all. Preview loops GIF/WebP frames.

## Where the source is written

Same split as BarDrop. Source lives at `/root/dev/BarGrab` on the box and is
pushed to this repo. The app runs on the PC. Do not install Chromium or crawl
from the box.

## Tests

```
python -m unittest discover -s tests
```

On the box, window and live-ffmpeg tests skip. That is expected.
