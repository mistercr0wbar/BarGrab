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
    DEFAULT_CAP,
    DEFAULT_DELAY,
    EDGE,
    INK,
    MAGENTA,
    MAGENTA_SOFT,
    MUTED,
    PANEL,
    TEXT,
    VEST_PURPLE,
    VIDEO_KINDS,
    Cancel,
    CrawlOptions,
    InboxItem,
    Library,
    browser_available,
    crawl,
    default_library,
    find_ffmpeg,
    open_path,
    parse_urls,
    preview_frames,
    read_settings,
    sanitize_folder,
    write_settings,
)

PREVIEW_SIZE = (400, 250)


class BarGrab(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x780")
        self.minsize(860, 600)
        self.configure(bg=INK)

        settings = read_settings()
        lib = settings.get("library") or str(default_library())
        self.library = Library(lib)
        self._items: list[InboxItem] = []
        self._busy = False
        self._cancel = Cancel()
        self._preview_frames: list[tk.PhotoImage] = []
        self._preview_durations: list[int] = []
        self._preview_index = 0
        self._preview_job = None
        self._folder_default = settings.get("folder") or "unsorted"

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
            text="paste a page, grab clips, keep the ones you want",
            bg=INK,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(10, 0), pady=(7, 0))

        self.urls = tk.Text(
            self,
            height=4,
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
        self.urls.insert("1.0", "Paste a GIF page or a gallery URL.")
        self.urls.bind("<FocusIn>", self._clear_hint)

        controls = tk.Frame(self, bg=INK)
        controls.pack(fill="x", padx=14, pady=(8, 0))

        tk.Label(
            controls, text="Keep in folder", bg=INK, fg=MUTED, font=("Segoe UI", 9)
        ).pack(side="left")
        self.folder = tk.Entry(
            controls,
            width=18,
            bg=PANEL,
            fg=TEXT,
            insertbackground=MAGENTA,
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.folder.insert(0, self._folder_default)
        self.folder.pack(side="left", padx=(6, 14), ipady=3)

        tk.Label(
            controls, text="How many", bg=INK, fg=MUTED, font=("Segoe UI", 9)
        ).pack(side="left")
        self.cap = tk.Spinbox(
            controls, from_=1, to=200, width=4, font=("Segoe UI", 9)
        )
        self.cap.delete(0, "end")
        self.cap.insert(0, str(DEFAULT_CAP))
        self.cap.pack(side="left", padx=(4, 12))

        self.grab_btn = self._button(controls, "Grab", self.start_grab, primary=True)
        self.grab_btn.pack(side="right")
        self._button(controls, "Open folder", self.open_keepers).pack(
            side="right", padx=(0, 8)
        )
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
            selectmode="extended",
            exportselection=False,
        )
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._show_selected())
        self.listbox.bind("<Key-k>", lambda e: self.keep_selected())
        self.listbox.bind("<Key-K>", lambda e: self.keep_selected())
        self.listbox.bind("<Key-x>", lambda e: self.skip_selected())
        self.listbox.bind("<Key-X>", lambda e: self.skip_selected())
        self.listbox.bind("<Delete>", lambda e: self.delete_selected())
        self.listbox.bind("<BackSpace>", lambda e: self.delete_selected())
        self.listbox.bind("<Return>", lambda e: self.open_selected())
        self.listbox.bind("<Control-a>", self._select_all)
        self.listbox.bind("<Control-A>", self._select_all)

        right = tk.Frame(body, bg=INK, width=420)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        self.preview_frame = tk.Frame(
            right, bg=PANEL, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1],
            highlightbackground=EDGE, highlightthickness=1,
        )
        self.preview_frame.pack(pady=(0, 8))
        self.preview_frame.pack_propagate(False)
        self.preview = tk.Label(
            self.preview_frame, text="nothing selected", bg=PANEL, fg=MUTED,
            font=("Segoe UI", 10),
        )
        self.preview.pack(fill="both", expand=True)
        self.meta = tk.Label(
            right, text="", bg=INK, fg=TEXT, font=("Consolas", 9),
            justify="left", anchor="nw", wraplength=400,
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
        self._button(actions, "Delete  Del", self.delete_selected).pack(
            fill="x", pady=(0, 6)
        )
        self._button(actions, "Play", self.open_selected).pack(fill="x")

        footer = tk.Label(
            self,
            text=(
                "Ctrl+click / Shift+click to multi-select.  Del removes.  "
                "Skip remembers not to grab it again.  Keep goes into the folder named above."
            ),
            bg=INK, fg=MUTED, font=("Segoe UI", 8), anchor="w",
        )
        footer.pack(fill="x", padx=16, pady=(6, 10))

    def _folder_name(self) -> str:
        return sanitize_folder(self.folder.get())

    def _clear_hint(self, _event=None) -> None:
        current = self.urls.get("1.0", "end").strip()
        if current.startswith("Paste a GIF page"):
            self.urls.delete("1.0", "end")

    def _ready_text(self) -> str:
        bits = [str(self.library.keeper_dir(self._folder_name()))]
        if not browser_available():
            bits.append("Chromium missing — most GIF sites will fail")
        if find_ffmpeg() is None:
            bits.append("ffmpeg missing — keeping a video will fail")
        return "  ·  ".join(bits)

    def _persist(self) -> None:
        settings = read_settings()
        settings["library"] = str(self.library.root)
        settings["folder"] = self._folder_name()
        write_settings(settings)

    def pick_library(self) -> None:
        chosen = filedialog.askdirectory(
            title="BarGrab library",
            initialdir=str(self.library.root),
        )
        if not chosen:
            return
        self.library = Library(chosen)
        self._persist()
        self.status.config(text=self._ready_text())
        self.refresh_inbox()

    def start_grab(self) -> None:
        if self._busy:
            self.status.config(text="stopping…")
            self._cancel.stop()
            return
        urls = parse_urls(self.urls.get("1.0", "end"))
        if not urls:
            messagebox.showinfo(APP_NAME, "Paste at least one http(s) URL.")
            return
        try:
            cap = int(self.cap.get())
        except ValueError:
            messagebox.showinfo(APP_NAME, "How many has to be a number.")
            return
        self._busy = True
        self._cancel = Cancel()
        self.grab_btn.config(text="Stop")
        opts = CrawlOptions(
            use_browser=browser_available(),
            gallery=True,
            cap=max(1, cap),
            delay=DEFAULT_DELAY,
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
                    cancel=self._cancel,
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
        prefix = "stopped. " if result.stopped else ""
        self.status.config(
            text=(
                f"{prefix}saved {result.saved}, dupes {result.duplicates}, "
                f"already skipped {result.skipped_known}, "
                f"pages {result.pages}{extra}"
            )
        )
        if result.errors and result.saved == 0 and not result.stopped:
            messagebox.showwarning(
                APP_NAME,
                "Nothing saved.\n\n" + "\n".join(result.errors[:8]),
            )

    def refresh_inbox(self) -> None:
        self._stop_preview()
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
            self.meta.config(text="")

    def _selected_items(self) -> list[InboxItem]:
        return [
            self._items[i]
            for i in self.listbox.curselection()
            if 0 <= i < len(self._items)
        ]

    def _select_all(self, _event=None):
        self.listbox.selection_set(0, "end")
        self._show_selected()
        return "break"

    def _stop_preview(self) -> None:
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self._preview_frames = []
        self._preview_durations = []
        self._preview_index = 0

    def _tick_preview(self) -> None:
        if not self._preview_frames:
            return
        self._preview_index = (self._preview_index + 1) % len(self._preview_frames)
        self.preview.config(image=self._preview_frames[self._preview_index])
        delay = self._preview_durations[self._preview_index]
        self._preview_job = self.after(delay, self._tick_preview)

    def _show_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        item = items[0]
        self._stop_preview()
        frames = [] if item.kind in VIDEO_KINDS else preview_frames(
            item.path, size=PREVIEW_SIZE
        )
        photos: list[tk.PhotoImage] = []
        durations: list[int] = []
        for png, duration in frames:
            try:
                photos.append(
                    tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
                )
                durations.append(duration)
            except tk.TclError:
                continue
        if photos:
            self._preview_frames = photos
            self._preview_durations = durations
            self._preview_index = 0
            self.preview.config(image=photos[0], text="", width=0, height=0)
            if len(photos) > 1:
                self._preview_job = self.after(durations[0], self._tick_preview)
        else:
            label = "video — press Play" if item.kind in VIDEO_KINDS else "no preview"
            self.preview.config(image="", text=label)
        extra = f"\n{len(items)} selected" if len(items) > 1 else ""
        warn = ""
        if item.size > BARBIE_MAX_BYTES:
            warn = "\n\nThis is over BARBIE's 12 MB cap. She will refuse it."
        self.meta.config(
            text=(
                f"{item.path.name}\n{item.kind}  {item.size/1024:.1f} KB"
                f"{extra}{warn}\n\n"
                f"{item.sidecar.get('page_url') or ''}\n"
                f"{item.sidecar.get('source_url') or ''}"
            )
        )

    def keep_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        folder = self._folder_name()
        self.folder.delete(0, "end")
        self.folder.insert(0, folder)
        self._persist()
        kept = 0
        last = None
        for item in items:
            try:
                last = self.library.keep(item, folder)
                kept += 1
            except Exception as exc:
                messagebox.showerror(APP_NAME, str(exc))
                break
        note = f"kept {kept} → {folder}"
        if last is not None and last.stat().st_size > BARBIE_MAX_BYTES:
            note += " — last file is over 12 MB, BARBIE will refuse it"
        self.status.config(text=note)
        self.refresh_inbox()

    def skip_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        for item in items:
            self.library.skip(item)
        self.status.config(text=f"skipped {len(items)}")
        self.refresh_inbox()

    def delete_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        for item in items:
            self.library.delete(item)
        self.status.config(text=f"deleted {len(items)}")
        self.refresh_inbox()

    def open_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        open_path(items[0].path)

    def open_keepers(self) -> None:
        open_path(self.library.keeper_dir(self._folder_name()))

    def _on_close(self) -> None:
        self._stop_preview()
        self._persist()
        self._cancel.stop()
        self.destroy()


def main() -> None:
    app = BarGrab()
    app.mainloop()


if __name__ == "__main__":
    main()
