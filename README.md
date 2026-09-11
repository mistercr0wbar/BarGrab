# BarGrab

Collect GIFs — including the ones that are actually looping videos — then pick
the ones worth adding to BARBIE.

Windows. Run from source. The crawl does not run on the cr0wbox.

## What it does

Paste a gallery URL or one-or-more GIF page URLs. Chromium loads the page and
intercepts what the tab actually downloaded (GIF, animated WebP, MP4, WebM,
blob URLs). That is how it gets past overlay / right-click tricks.

Inbox → Keep / Skip. Keep converts MP4/WebM to animated WebP, which BARBIE
already accepts. GIF and WebP are copied as-is.

It does **not** talk to Discord or to BARBIE. Keepers land in
`Pictures\BarGrab\keepers`. You add them through the board or
`barbie admin gifs add`.

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

If Playwright is missing it still runs, HTML-only, which fails on the overlay
sites this exists for. The browser checkbox is the real path.

ffmpeg is only needed when you Keep a video. Skip is free.

## Library

Default: `%USERPROFILE%\Pictures\BarGrab`

| Folder / file | What |
|---|---|
| `inbox/` | just grabbed, not decided |
| `keepers/` | Keep. These are what you add to BARBIE |
| `skip.json` | hashes of Skip, so a re-crawl does not re-offer them |

Media never goes in git. `.gitignore` blocks `inbox/`, `keepers/`, and every
common media extension. Tests use byte literals, not fixture files.

Settings: `%APPDATA%\BarGrab\settings.json`.

## Keys

In the inbox list: **K** keep, **X** skip, **Enter** play in the default app.

## Where the source is written

Same split as BarDrop. Source lives at `/root/dev/BarGrab` on the box and is
pushed to this repo. The app runs on the PC. Do not install Chromium or crawl
from the box.

## Tests

```
python -m unittest discover -s tests
```

On the box, window and live-ffmpeg tests skip. That is expected.
