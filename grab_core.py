"""Collect media from GIF-labelled pages. No window, so it can be tested.

The sites this exists for do not put a .gif on img.src. They loop a muted
video, serve animated WebP, mint blob URLs, and overlay a transparent layer
that eats right-click. The bytes still went over the network. Chromium
interception is how we take them; HTML parsing is the fallback and the
path the tests actually run.

Nothing here talks to BARBIE. Keepers are files. She has her own ingest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


APP_NAME = "BarGrab"

# BARBIE's palette, same samples Gagger uses.
MAGENTA = "#F819A5"
MAGENTA_SOFT = "#FC69D7"
VEST_PURPLE = "#6C3681"
INK = "#16121A"
PANEL = "#211B27"
EDGE = "#3A2F42"
TEXT = "#EDE6F0"
MUTED = "#9A8FA3"
DANGER = "#ED4245"
WARNING = "#FEE75C"
GOOD = "#57F287"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# BARBIE's download_gif ceiling. We still keep a larger file; the window
# warns, because the board will refuse it.
BARBIE_MAX_BYTES = 12 * 1024 * 1024
MIN_BYTES = 8 * 1024
MAX_BYTES = 40 * 1024 * 1024
DEFAULT_CAP = 40
DEFAULT_DELAY = 1.5

EXT_KIND = {
    ".gif": "gif",
    ".webp": "webp",
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".webm": "webm",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
}
MIME_KIND = {
    "image/gif": "gif",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
}
KIND_EXT = {
    "gif": ".gif",
    "webp": ".webp",
    "mp4": ".mp4",
    "webm": ".webm",
    "png": ".png",
    "jpg": ".jpg",
}
VIDEO_KINDS = {"mp4", "webm"}
BARBIE_KINDS = {"gif", "webp", "png", "jpg"}

CLIP_PATH_HINTS = (
    "/watch",
    "/gif/",
    "/gifs/",
    "/clip",
    "/video/",
    "/view/",
    "/ifr/",
    "/embed/",
    "/redgifs.com/",
)
LISTING_LAST_SEGMENTS = {
    "tags", "tag", "category", "categories", "user", "users",
    "search", "login", "signup", "register", "about", "popular",
    "trending", "top", "new", "hot", "feed", "explore",
}
NOT_PAGES = {
    ".css", ".js", ".mjs", ".json", ".xml", ".woff", ".woff2",
    ".svg", ".ico", ".map", ".txt",
}
JUNK_SUBSTR = (
    "google-analytics", "googletag", "doubleclick", "facebook.com/tr",
    "scorecard", "quantserve", "hotjar", "adsystem", "adservice",
    "favicon", "/sprite", "analytics.", "cookie-law", "googlesyndication",
)
MEDIA_ATTRS = (
    "src", "data-src", "data-original", "data-lazy-src", "data-lazy",
    "data-url", "data-mp4", "data-webm", "data-gif", "data-video",
    "data-media", "href",
)
SRCSET_ATTRS = ("srcset", "data-srcset")
OG_NAMES = {
    "og:video", "og:video:url", "og:video:secure_url",
    "og:image", "og:image:url", "og:image:secure_url",
    "twitter:player:stream", "twitter:image",
}


class FetchError(Exception):
    """A page or a media URL could not be fetched."""


class ConvertError(Exception):
    """ffmpeg could not turn a video into something BARBIE will take."""


@dataclass(frozen=True)
class MediaRef:
    url: str
    kind: str | None = None
    mime: str | None = None


@dataclass
class PageExtract:
    media: list[MediaRef] = field(default_factory=list)
    clip_links: list[str] = field(default_factory=list)


@dataclass
class CrawlOptions:
    use_browser: bool = True
    gallery: bool = True
    cap: int = DEFAULT_CAP
    delay: float = DEFAULT_DELAY
    min_bytes: int = MIN_BYTES
    max_bytes: int = MAX_BYTES
    timeout: float = 30.0


@dataclass
class CrawlResult:
    saved: int = 0
    duplicates: int = 0
    skipped_known: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list)
    used_browser: bool = False


@dataclass
class InboxItem:
    path: Path
    hash: str
    kind: str
    size: int
    sidecar: dict


def resource(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def settings_file() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME / "settings.json"


def default_library() -> Path:
    return Path.home() / "Pictures" / APP_NAME


def read_settings() -> dict:
    try:
        loaded = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_settings(data: dict) -> None:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def parse_urls(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"\s+", text.strip()):
        if not raw:
            continue
        url = normalize_url(raw)
        if url is None:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


def normalize_url(url: str) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme:
        return None
    return urlunparse(parsed._replace(fragment=""))


def classify(url: str, mime: str | None = None) -> str | None:
    mime = (mime or "").split(";")[0].strip().lower()
    if mime in MIME_KIND:
        return MIME_KIND[mime]
    path = urlparse(url).path.lower()
    for ext, kind in EXT_KIND.items():
        if path.endswith(ext):
            return kind
    return None


def is_junk_url(url: str) -> bool:
    lower = url.lower()
    return any(bit in lower for bit in JUNK_SUBSTR)


def is_fetchable(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def sniff(data: bytes) -> str | None:
    if len(data) < 12:
        return None
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


def parse_srcset(value: str) -> list[str]:
    out: list[str] = []
    for part in value.split(","):
        token = part.strip().split()
        if token:
            out.append(token[0])
    return out


def _abs(base: str, url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith(("#", "javascript:", "mailto:")):
        return None
    if url.startswith("blob:") or url.startswith("data:"):
        return url
    joined = urljoin(base, url)
    return normalize_url(joined)


class _Collector(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.media: list[MediaRef] = []
        self.links: list[str] = []
        self._seen_media: set[str] = set()
        self._seen_links: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        a = {k.lower(): v for k, v in attrs if v}
        tag = tag.lower()
        if tag == "meta":
            name = (a.get("property") or a.get("name") or "").lower()
            if name in OG_NAMES:
                self._add_media(a.get("content"))
            return
        if tag == "iframe":
            self._add_link(a.get("src"))
        for key in MEDIA_ATTRS:
            if key in a:
                if tag == "a" and key == "href":
                    self._add_link(a[key])
                    self._add_media(a[key])
                else:
                    self._add_media(a[key])
        for key in SRCSET_ATTRS:
            if key in a:
                for item in parse_srcset(a[key]):
                    self._add_media(item)

    def _add_media(self, raw: str | None) -> None:
        url = _abs(self.base, raw)
        if not url or url in self._seen_media or is_junk_url(url):
            return
        kind = classify(url)
        if url.startswith("blob:"):
            kind = kind or "blob"
        elif url.startswith("data:"):
            header = url.split(",", 1)[0]
            mime = header[5:].split(";")[0] if header.startswith("data:") else ""
            kind = MIME_KIND.get(mime)
            if kind is None:
                return
        elif kind is None:
            return
        self._seen_media.add(url)
        self.media.append(MediaRef(url=url, kind=kind))

    def _add_link(self, raw: str | None) -> None:
        url = _abs(self.base, raw)
        if not url or not is_fetchable(url) or url in self._seen_links:
            return
        self._seen_links.add(url)
        self.links.append(url)


def extract_html(html: str, base_url: str) -> PageExtract:
    collector = _Collector(base_url)
    try:
        collector.feed(html)
        collector.close()
    except Exception:
        # Broken HTML still yields whatever was seen before the parser gave up.
        pass
    clips = [
        url for url in collector.links
        if is_clip_like(url, base_url)
    ]
    return PageExtract(media=collector.media, clip_links=clips)


def is_clip_like(url: str, page_url: str) -> bool:
    parsed = urlparse(url)
    page = urlparse(page_url)
    if parsed.netloc and page.netloc and parsed.netloc != page.netloc:
        return False
    path = parsed.path.rstrip("/")
    if not path or path == page.path.rstrip("/"):
        return False
    lower_path = path.lower()
    for ext in list(EXT_KIND) + list(NOT_PAGES):
        if lower_path.endswith(ext):
            return False
    parts = [p.lower() for p in path.split("/") if p]
    if any(part in LISTING_LAST_SEGMENTS for part in parts):
        return False
    last = parts[-1]
    lower = url.lower()
    if any(hint in lower for hint in CLIP_PATH_HINTS):
        return True
    return len(last) >= 6


def webp_command(ffmpeg: str, src: Path, dest: Path) -> list[str]:
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-an",
        "-loop", "0",
        "-vf", "scale='min(720,iw)':-2:flags=lanczos",
        "-c:v", "libwebp",
        "-quality", "70",
        str(dest),
    ]


def gif_command(ffmpeg: str, src: Path, dest: Path) -> list[str]:
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-an",
        "-vf", (
            "fps=12,scale='min(480,iw)':-2:flags=lanczos,"
            "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
        ),
        str(dest),
    ]


def convert_video(src: Path, dest: Path, ffmpeg: str | None = None) -> Path:
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise ConvertError("ffmpeg is not installed")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = webp_command(ffmpeg, src, dest)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, text=True)
    except FileNotFoundError as exc:
        raise ConvertError("ffmpeg is not installed") from exc
    if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
        return dest
    if dest.exists():
        dest.unlink()
    gif_dest = dest.with_suffix(".gif")
    proc = subprocess.run(
        gif_command(ffmpeg, src, gif_dest),
        capture_output=True, timeout=120, text=True,
    )
    if proc.returncode == 0 and gif_dest.exists() and gif_dest.stat().st_size > 0:
        return gif_dest
    detail = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
    raise ConvertError(detail.splitlines()[-1] if detail else "ffmpeg failed")


def _request(url: str, referer: str | None = None) -> Request:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,"
                  "image/*,video/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return Request(url, headers=headers)


def fetch_bytes(url: str, referer: str | None = None, timeout: float = 25.0) -> bytes:
    try:
        with urlopen(_request(url, referer), timeout=timeout) as resp:
            data = resp.read()
    except HTTPError as exc:
        raise FetchError(f"{url} -> HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{url} -> {exc}") from exc
    return data


def fetch_text(url: str, timeout: float = 25.0) -> str:
    data = fetch_bytes(url, timeout=timeout)
    return data.decode("utf-8", errors="replace")


def decode_data_url(url: str) -> bytes | None:
    if not url.startswith("data:") or "," not in url:
        return None
    header, payload = url.split(",", 1)
    try:
        if ";base64" in header:
            import base64
            return base64.b64decode(payload)
        from urllib.parse import unquote_to_bytes
        return unquote_to_bytes(payload)
    except Exception:
        return None


class Library:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.keepers = self.root / "keepers"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.keepers.mkdir(parents=True, exist_ok=True)
        self.skip_path = self.root / "skip.json"
        self._skip = self._load_skip()

    def _load_skip(self) -> set[str]:
        try:
            loaded = json.loads(self.skip_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if isinstance(loaded, list):
            return {str(item) for item in loaded}
        return set()

    def _write_skip(self) -> None:
        self.skip_path.write_text(
            json.dumps(sorted(self._skip), indent=2) + "\n", encoding="utf-8"
        )

    def known(self, digest: str) -> str | None:
        if digest in self._skip:
            return "skip"
        prefix = digest[:12]
        if any(self.inbox.glob(f"{prefix}.*")):
            return "inbox"
        if any(self.keepers.glob(f"{prefix}.*")):
            return "keep"
        return None

    def save_bytes(
        self,
        data: bytes,
        *,
        source_url: str,
        page_url: str,
        mime: str | None = None,
        min_bytes: int = MIN_BYTES,
        max_bytes: int = MAX_BYTES,
    ) -> InboxItem | str:
        """Return the new item, or 'duplicate' / 'skip' / 'tiny' / 'huge' / 'unknown'."""
        kind = sniff(data) or classify(source_url, mime)
        if kind is None:
            return "unknown"
        if len(data) < min_bytes:
            return "tiny"
        if len(data) > max_bytes:
            return "huge"
        digest = hashlib.sha256(data).hexdigest()
        already = self.known(digest)
        if already == "skip":
            return "skip"
        if already in ("inbox", "keep"):
            return "duplicate"
        ext = KIND_EXT[kind]
        path = self.inbox / f"{digest[:12]}{ext}"
        path.write_bytes(data)
        sidecar = {
            "hash": digest,
            "source_url": source_url,
            "page_url": page_url,
            "mime": mime,
            "kind": kind,
            "bytes": len(data),
        }
        path.with_suffix(".json").write_text(
            json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
        )
        return InboxItem(
            path=path, hash=digest, kind=kind, size=len(data), sidecar=sidecar
        )

    def inbox_items(self) -> list[InboxItem]:
        items: list[InboxItem] = []
        for path in sorted(self.inbox.iterdir()):
            if path.suffix.lower() == ".json" or not path.is_file():
                continue
            sidecar = {}
            side_path = path.with_suffix(".json")
            try:
                loaded = json.loads(side_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    sidecar = loaded
            except (OSError, ValueError):
                pass
            digest = str(sidecar.get("hash") or path.stem)
            kind = str(sidecar.get("kind") or sniff(path.read_bytes()[:32]) or "gif")
            items.append(InboxItem(
                path=path,
                hash=digest,
                kind=kind,
                size=path.stat().st_size,
                sidecar=sidecar,
            ))
        return items

    def keep(self, item: InboxItem) -> Path:
        if item.kind in VIDEO_KINDS:
            dest = self.keepers / f"{item.hash[:12]}.webp"
            written = convert_video(item.path, dest)
        else:
            dest = self.keepers / f"{item.hash[:12]}{KIND_EXT.get(item.kind, item.path.suffix)}"
            shutil.copy2(item.path, dest)
            written = dest
        sidecar = dict(item.sidecar)
        sidecar["kept_as"] = written.name
        sidecar["kept_bytes"] = written.stat().st_size
        sidecar["over_barbie_cap"] = written.stat().st_size > BARBIE_MAX_BYTES
        written.with_suffix(".json").write_text(
            json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
        )
        self._forget_inbox(item)
        return written

    def skip(self, item: InboxItem) -> None:
        self._skip.add(item.hash)
        self._write_skip()
        self._forget_inbox(item)

    def _forget_inbox(self, item: InboxItem) -> None:
        item.path.unlink(missing_ok=True)
        item.path.with_suffix(".json").unlink(missing_ok=True)


def _save_captured(
    library: Library,
    data: bytes,
    source_url: str,
    page_url: str,
    mime: str | None,
    opts: CrawlOptions,
    result: CrawlResult,
) -> None:
    outcome = library.save_bytes(
        data,
        source_url=source_url,
        page_url=page_url,
        mime=mime,
        min_bytes=opts.min_bytes,
        max_bytes=opts.max_bytes,
    )
    if isinstance(outcome, InboxItem):
        result.saved += 1
    elif outcome == "duplicate":
        result.duplicates += 1
    elif outcome == "skip":
        result.skipped_known += 1


def capture_html_only(
    url: str, library: Library, opts: CrawlOptions, result: CrawlResult
) -> PageExtract:
    html = fetch_text(url, timeout=opts.timeout)
    extracted = extract_html(html, url)
    for ref in extracted.media:
        try:
            if ref.url.startswith("data:"):
                data = decode_data_url(ref.url)
                if not data:
                    continue
                _save_captured(library, data, ref.url[:80], url, ref.mime, opts, result)
                continue
            if not is_fetchable(ref.url):
                continue
            data = fetch_bytes(ref.url, referer=url, timeout=opts.timeout)
            _save_captured(library, data, ref.url, url, ref.mime, opts, result)
        except FetchError as exc:
            result.errors.append(str(exc))
    return extracted


def capture_browser(
    url: str, library: Library, opts: CrawlOptions, result: CrawlResult
) -> PageExtract:
    from playwright.sync_api import sync_playwright

    intercepted: list[tuple[bytes, str | None, str]] = []

    def on_response(response) -> None:
        try:
            if response.status != 200:
                return
            mime = (response.headers.get("content-type") or "").split(";")[0]
            kind = classify(response.url, mime)
            if kind is None or is_junk_url(response.url):
                return
            body = response.body()
        except Exception:
            return
        if body:
            intercepted.append((body, mime or None, response.url))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=int(opts.timeout * 1000))
            page.wait_for_timeout(2500)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
            except Exception:
                pass
            html = page.content()
        finally:
            browser.close()

    for body, mime, source in intercepted:
        _save_captured(library, body, source, url, mime, opts, result)
    extracted = extract_html(html, url)
    seen_sources = {source for _body, _mime, source in intercepted}
    for ref in extracted.media:
        if not is_fetchable(ref.url) or ref.url in seen_sources:
            continue
        try:
            data = fetch_bytes(ref.url, referer=url, timeout=opts.timeout)
            _save_captured(library, data, ref.url, url, ref.mime, opts, result)
        except FetchError as exc:
            result.errors.append(str(exc))
    return extracted


def crawl(
    urls: list[str],
    library: Library,
    opts: CrawlOptions | None = None,
    progress=None,
    should_stop=None,
) -> CrawlResult:
    opts = opts or CrawlOptions()
    result = CrawlResult()
    use_browser = bool(opts.use_browser and browser_available())
    result.used_browser = use_browser
    if opts.use_browser and not use_browser and progress:
        progress("Playwright not installed; HTML-only")

    def note(message: str) -> None:
        if progress:
            progress(message)

    def stopped() -> bool:
        return bool(should_stop and should_stop())

    visited: set[str] = set()
    discovered: list[str] = []

    def visit(page_url: str, harvest_links: bool) -> None:
        if page_url in visited or stopped():
            return
        visited.add(page_url)
        note(f"{page_url}")
        try:
            if use_browser:
                extracted = capture_browser(page_url, library, opts, result)
            else:
                extracted = capture_html_only(page_url, library, opts, result)
        except Exception as exc:
            result.errors.append(f"{page_url} -> {exc}")
            return
        result.pages += 1
        if harvest_links:
            for link in extracted.clip_links:
                if link not in visited and link not in discovered:
                    discovered.append(link)

    seeds = [url for url in urls if is_fetchable(url)]
    for seed in seeds:
        if result.pages >= opts.cap or stopped():
            break
        visit(seed, harvest_links=opts.gallery)

    for link in discovered:
        if result.pages >= opts.cap or stopped():
            break
        if opts.delay:
            time.sleep(opts.delay)
        visit(link, harvest_links=False)

    note(
        f"saved {result.saved}, dupes {result.duplicates}, "
        f"pages {result.pages}"
    )
    return result


def first_frame_png(path: Path, size: tuple[int, int] = (320, 200)) -> bytes | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        import io
        with Image.open(path) as im:
            im.load()
            frame = im.convert("RGBA")
            frame.thumbnail(size)
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None


def open_path(path: Path) -> None:
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Grab media URLs from a page.")
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--library", type=Path, default=None)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    args = parser.parse_args(argv)
    library = Library(args.library or default_library())
    opts = CrawlOptions(use_browser=not args.html_only, cap=args.cap)
    result = crawl(args.urls, library, opts, progress=print)
    for err in result.errors:
        print("error:", err, file=sys.stderr)
    return 0 if result.saved or not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
