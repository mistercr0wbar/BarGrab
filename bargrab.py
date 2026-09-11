"""BarGrab — collect GIFs (and the videos pretending to be GIFs), then pick.

The finding and converting lives in grab_core.py. This file is the window.
"""

from __future__ import annotations

import base64
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from grab_core import (
    APP_NAME,
    BARBIE_MAX_BYTES,
    DANGER,
    DEFAULT_CAP,
    DEFAULT_DELAY,
    EDGE,
    GOOD,
    INK,
    MAGENTA,
    MAGENTA_SOFT,
    MUTED,
    PANEL,
    TEXT,
    VEST_PURPLE,
    VIDEO_KINDS,
    WARNING,
    CrawlOptions,
    InboxItem,
    Library,
    browser_available,
    crawl,
    default_library,
    find_ffmpeg,
    first_frame_png,
    open_path,
    parse_urls,
    read_settings,
    write_settings,
)


class BarGrab(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x740")
        self.minsize(780, 560)
        self.configure(bg=INK)

        settings = read_settings()
        lib = settings.get("library") or str(default_library())
        self.library = Library(lib)
        self._items: list[InboxItem] = []
        self._busy = False
        self._stop = threading.Event()
        self._preview_image = None

        self._build()
        self.refresh_inbox()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _button(self, parent, label, command, *, primary=False):
        return tk.Button(
            parent,
            text=label,
            command=command,
            bg=MAGENTA if primary else EDGE,
            fg=INK if primary else TEXT,
            activebackground=MAGENTA_SOFT if primary else VEST_PURPLE,
            activeforeground=INK if primary else TEXT,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=4,
            cursor="hand2",
            borderwidth=0,
        )

    def _build(self) -> None:
        header = tk.Frame(self, bg=INK)
        header.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(
            header, text=APP_NAME, bg=INK, fg=MAGENTA, font=("Segoe UI", 17, "bold")
        ).pack(side="left")
        tk.Label(
            header,
            text="collect, then pick. BARBIE ingest is a later step.",
            bg=INK,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(10, 0), pady=(7, 0))

        self.urls = tk.Text(
            self,
            height=5,
            bg=PANEL,
            fg=TEXT,
            insertbackground=MAGENTA,
            selectbackground=VEST_PURPLE,
            relief="flat",
            highlightbackground=EDGE,
            highlightcolor=MAGENTA,
            highlightthickness=1,
            font=("Consolas", 11),
            wrap="word",
            undo=True,
        )
        self.urls.pack(fill="x", padx=14, pady=(10, 0))
        self.urls.insert("1.0", "Paste a gallery URL or GIF page URLs, one per line.")
        self.urls.bind("<FocusIn>", self._clear_hint)

        controls = tk.Frame(self, bg=INK)
        controls.pack(fill="x", padx=14, pady=(8, 0))

        tk.Label(controls, text="cap", bg=INK, fg=MUTED, font=("Segoe UI", 9)).pack(
            side="left"
        )
        self.cap = tk.Spinbox(
            controls, from_=1, to=200, width=4, font=("Segoe UI", 9)
        )
        self.cap.delete(0, "end")
        self.cap.insert(0, str(DEFAULT_CAP))
        self.cap.pack(side="left", padx=(4, 12))

        tk.Label(controls, text="delay s", bg=INK, fg=MUTED, font=("Segoe UI", 9)).pack(
            side="left"
        )
        self.delay = tk.Spinbox(
            controls, from_=0, to=10, increment=0.5, width=4, font=("Segoe UI", 9)
        )
        self.delay.delete(0, "end")
        self.delay.insert(0, str(DEFAULT_DELAY))
        self.delay.pack(side="left", padx=(4, 12))

        self.use_browser = tk.BooleanVar(value=browser_available())
        tk.Checkbutton(
            controls,
            text="browser",
            variable=self.use_browser,
            bg=INK,
            fg=TEXT,
            selectcolor=PANEL,
            activebackground=INK,
            activeforeground=TEXT,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 8))

        self.gallery = tk.BooleanVar(value=True)
        tk.Checkbutton(
            controls,
            text="walk listing",
            variable=self.gallery,
            bg=INK,
            fg=TEXT,
            selectcolor=PANEL,
            activebackground=INK,
            activeforeground=TEXT,
            font=("Segoe UI", 9),
        ).pack(side="left")

        self.grab_btn = self._button(controls, "Grab", self.start_grab, primary=True)
        self.grab_btn.pack(side="right")
        self._button(controls, "Library…", self.pick_library).pack(
            side="right", padx=(0, 8)
        )

        self.status = tk.Label(
            self, text=self._ready_text(), bg=INK, fg=MUTED,
            font=("Segoe UI", 9), anchor="w",
        )
        self.status.pack(fill="x", padx=16, pady=(6, 0))

        body = tk.Frame(self, bg=INK)
        body.pack(fill="both", expand=True, padx=14, pady=(8, 0))

        left = tk.Frame(body, bg=EDGE)
        left.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(
            left,
            bg=PANEL,
            fg=TEXT,
            selectbackground=VEST_PURPLE,
            selectforeground=TEXT,
            relief="flat",
            font=("Consolas", 10),
            activestyle="none",
            highlightthickness=0,
        )
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._show_selected())
        self.listbox.bind("<Key-k>", lambda e: self.keep_selected())
        self.listbox.bind("<Key-x>", lambda e: self.skip_selected())
        self.listbox.bind("<Return>", lambda e: self.open_selected())

        right = tk.Frame(body, bg=INK, width=340)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        self.preview = tk.Label(
            right, text="nothing selected", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10), width=38, height=12,
        )
        self.preview.pack(fill="x", pady=(0, 8))
        self.meta = tk.Label(
            right, text="", bg=INK, fg=TEXT, font=("Consolas", 9),
            justify="left", anchor="nw", wraplength=320,
        )
        self.meta.pack(fill="x")

        actions = tk.Frame(right, bg=INK)
        actions.pack(fill="x", pady=(12, 0))
        self._button(actions, "Keep  K", self.keep_selected, primary=True).pack(
            fill="x", pady=(0, 6)
        )
        self._button(actions, "Skip  X", self.skip_selected).pack(
            fill="x", pady=(0, 6)
        )
        self._button(actions, "Play", self.open_selected).pack(fill="x", pady=(0, 6))
        self._button(actions, "Open keepers", self.open_keepers).pack(fill="x")

        footer = tk.Label(
            self,
            text="Keepers go to Pictures\\BarGrab\\keepers. Add them to BARBIE yourself.",
            bg=INK, fg=MUTED, font=("Segoe UI", 8), anchor="w",
        )
        footer.pack(fill="x", padx=16, pady=(6, 10))

    def _clear_hint(self, _event=None) -> None:
        current = self.urls.get("1.0", "end").strip()
        if current.startswith("Paste a gallery URL"):
            self.urls.delete("1.0", "end")

    def _ready_text(self) -> str:
        bits = [str(self.library.root)]
        if self.use_browser.get() and not browser_available():
            bits.append("Playwright missing — HTML-only")
        if find_ffmpeg() is None:
            bits.append("ffmpeg missing — video keep will fail")
        return "  ·  ".join(bits)

    def pick_library(self) -> None:
        chosen = filedialog.askdirectory(
            title="BarGrab library",
            initialdir=str(self.library.root),
        )
        if not chosen:
            return
        self.library = Library(chosen)
        settings = read_settings()
        settings["library"] = chosen
        write_settings(settings)
        self.status.config(text=self._ready_text())
        self.refresh_inbox()

    def start_grab(self) -> None:
        if self._busy:
            self._stop.set()
            self.status.config(text="stopping…")
            return
        urls = parse_urls(self.urls.get("1.0", "end"))
        if not urls:
            messagebox.showinfo(APP_NAME, "Paste at least one http(s) URL.")
            return
        try:
            cap = int(self.cap.get())
            delay = float(self.delay.get())
        except ValueError:
            messagebox.showinfo(APP_NAME, "Cap and delay have to be numbers.")
            return
        self._busy = True
        self._stop.clear()
        self.grab_btn.config(text="Stop")
        opts = CrawlOptions(
            use_browser=self.use_browser.get(),
            gallery=self.gallery.get(),
            cap=max(1, cap),
            delay=max(0.0, delay),
        )

        def work() -> None:
            def progress(message: str) -> None:
                self.after(0, lambda m=message: self.status.config(text=m))

            try:
                result = crawl(
                    urls,
                    self.library,
                    opts,
                    progress=progress,
                    should_stop=self._stop.is_set,
                )
            except Exception as exc:
                self.after(0, lambda: self._grab_done(error=str(exc)))
                return
            self.after(0, lambda: self._grab_done(result=result))

        threading.Thread(target=work, daemon=True).start()

    def _grab_done(self, result=None, error: str | None = None) -> None:
        self._busy = False
        self.grab_btn.config(text="Grab")
        self.refresh_inbox()
        if error:
            self.status.config(text=error)
            messagebox.showerror(APP_NAME, error)
            return
        assert result is not None
        extra = ""
        if result.errors:
            extra = f"  ·  {len(result.errors)} page errors"
        self.status.config(
            text=(
                f"saved {result.saved}, dupes {result.duplicates}, "
                f"already skipped {result.skipped_known}, "
                f"pages {result.pages}{extra}"
            )
        )
        if result.errors and result.saved == 0:
            messagebox.showwarning(
                APP_NAME,
                "Nothing saved.\n\n" + "\n".join(result.errors[:8]),
            )

    def refresh_inbox(self) -> None:
        self._items = self.library.inbox_items()
        self.listbox.delete(0, "end")
        for item in self._items:
            over = "  TOO BIG" if item.size > BARBIE_MAX_BYTES else ""
            self.listbox.insert(
                "end",
                f"{item.kind:4}  {item.size/1024:7.1f} KB  {item.path.name}{over}",
            )
        if self._items:
            self.listbox.selection_set(0)
            self._show_selected()
        else:
            self.preview.config(image="", text="inbox empty")
            self._preview_image = None
            self.meta.config(text="")

    def _selected(self) -> InboxItem | None:
        choice = self.listbox.curselection()
        if not choice:
            return None
        index = int(choice[0])
        if index < 0 or index >= len(self._items):
            return None
        return self._items[index]

    def _show_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        png = None if item.kind in VIDEO_KINDS else first_frame_png(item.path)
        if png:
            try:
                self._preview_image = tk.PhotoImage(
                    data=base64.b64encode(png).decode("ascii")
                )
                self.preview.config(image=self._preview_image, text="")
            except tk.TclError:
                self._preview_image = None
                self.preview.config(image="", text="preview failed")
        else:
            self._preview_image = None
            label = "video — press Play" if item.kind in VIDEO_KINDS else "no preview"
            self.preview.config(image="", text=label)
        source = item.sidecar.get("source_url") or ""
        page = item.sidecar.get("page_url") or ""
        warn = ""
        if item.size > BARBIE_MAX_BYTES:
            warn = "\n\nThis is over BARBIE's 12 MB cap. She will refuse it."
        self.meta.config(
            text=(
                f"{item.path.name}\n{item.kind}  {item.size/1024:.1f} KB"
                f"{warn}\n\n{page}\n{source}"
            )
        )

    def keep_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        try:
            written = self.library.keep(item)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        note = f"kept {written.name}"
        if written.stat().st_size > BARBIE_MAX_BYTES:
            note += " — over 12 MB, BARBIE will refuse it"
        self.status.config(text=note)
        self.refresh_inbox()

    def skip_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        self.library.skip(item)
        self.status.config(text=f"skipped {item.path.name}")
        self.refresh_inbox()

    def open_selected(self) -> None:
        item = self._selected()
        if item is None:
            return
        open_path(item.path)

    def open_keepers(self) -> None:
        self.library.keepers.mkdir(parents=True, exist_ok=True)
        open_path(self.library.keepers)

    def _on_close(self) -> None:
        self._stop.set()
        self.destroy()


def main() -> None:
    app = BarGrab()
    app.mainloop()


if __name__ == "__main__":
    main()
