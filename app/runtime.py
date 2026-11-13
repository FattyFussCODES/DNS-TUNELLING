"""Small platform helpers shared by the workbench and Lab tools entry points."""

from __future__ import annotations

import sys


def set_app_user_model_id(version: str) -> None:
    """Give Windows a named taskbar group instead of a generic Python one."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"DNSMuggle.{version}"
        )
    except OSError:
        pass