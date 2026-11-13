"""Tkinter front end. Steps 1-2: Send and Receive tabs."""

from __future__ import annotations


def mono_family() -> str:
    """Consolas on Windows, a sane fixed-width fallback elsewhere."""
    try:
        import tkinter.font as tkfont

        return "Consolas" if "Consolas" in tkfont.families() else "Courier New"
    except Exception:
        return "Courier New"
