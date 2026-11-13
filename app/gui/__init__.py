"""Tkinter front end: shared asset loading, the brand marks, and helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

BRAND_NAME = "DNSMuggle"
BRAND_TAGLINE = "Smuggle a file out using only DNS queries"

# The logo art sits on this near-black background.
LOGO_BG = "#0d0d0d"


class APPLogo:
    """Locations of the packaged brand assets (they ship as package data)."""

    @staticmethod
    def path(name: str) -> Path | None:
        candidate = ASSETS_DIR / name
        return candidate if candidate.is_file() else None

    @classmethod
    def logo(cls) -> Path | None:
        return cls.path("dnsmuggle-logo.png")

    @classmethod
    def icon_png(cls) -> Path | None:
        return cls.path("dnsmuggle-icon.png")

    @classmethod
    def icon_ico(cls) -> Path | None:
        return cls.path("dnsmuggle-icon.ico")


def load_image(master, path: str | Path, *, square: int | None = None,
               width: int | None = None):
    """PhotoImage from a PNG, resized when Pillow is available.

    Without Pillow the image is subsampled by the nearest integer factor,
    which is close enough for a header mark and needs no extra dependency.
    """
    source = str(path)
    try:
        from PIL import Image, ImageTk
    except ImportError:
        photo = tk.PhotoImage(file=source, master=master)
        target = square or width
        if target:
            factor = max(1, round(photo.width() / target))
            if factor > 1:
                photo = photo.subsample(factor, factor)
        return photo

    image = Image.open(source)
    if square:
        image = image.resize((square, square), Image.LANCZOS)
    elif width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.LANCZOS)
    return ImageTk.PhotoImage(image, master=master)


def apply_window_icon(root: tk.Tk) -> None:
    """Title bar + taskbar mark: ICO on Windows, PNG everywhere."""
    png = APPLogo.icon_png()
    ico = APPLogo.icon_ico()
    if ico is not None and sys.platform.startswith("win"):
        try:
            root.iconbitmap(default=str(ico))
        except tk.TclError:
            pass
    if png is not None:
        try:
            photo = tk.PhotoImage(file=str(png), master=root)
            root.iconphoto(True, photo)
            root._dnsmuggle_icon = photo  # keep a reference
        except tk.TclError:
            pass


def mono_family() -> str:
    """Consolas on Windows, a sane fixed-width fallback elsewhere."""
    try:
        import tkinter.font as tkfont

        return "Consolas" if "Consolas" in tkfont.families() else "Courier New"
    except Exception:
        return "Courier New"


def text_tail(widget, lines: int = 30) -> str:
    """Last N log lines from a tk.Text, for the history row."""
    content = widget.get("1.0", "end").strip()
    if not content:
        return ""
    return "\n".join(content.splitlines()[-lines:])


def open_path(path: str) -> None:
    """Open a file or folder with the OS default handler."""
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
