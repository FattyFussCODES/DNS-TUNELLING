"""Tkinter front end. Steps 1-2: Send and Receive tabs."""

from __future__ import annotations

import os
import subprocess
import sys


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
