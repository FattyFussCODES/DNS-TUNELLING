"""Entry point: python -m app.main, or the `dnsmuggle` command."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from . import __version__
from .gui import APPLogo, apply_window_icon, load_image
from .gui.main_window import MainWindow

SPLASH_MS = 1000


def _set_app_user_model_id() -> None:
    """Give Windows its own taskbar group/icon instead of a generic Python one."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DNSMuggle.1.0.0"
        )
    except Exception:
        pass


def _show_splash(root: tk.Tk) -> tk.Toplevel | None:
    logo = APPLogo.path("dnsmuggle-icon.png")
    if logo is None:
        return None
    try:
        splash = tk.Toplevel(root)
        splash.overrideredirect(True)
        splash.configure(bg="#0d0d0d")
        image = load_image(splash, logo, square=260)
        label = tk.Label(splash, image=image, bg="#0d0d0d", bd=0)
        label.image = image  # keep a reference
        label.pack(padx=18, pady=18)
        splash.attributes("-topmost", True)
        splash.update_idletasks()
        width = splash.winfo_width()
        height = splash.winfo_height()
        x = (splash.winfo_screenwidth() - width) // 2
        y = (splash.winfo_screenheight() - height) // 2
        splash.geometry(f"+{x}+{y}")
        splash.update()
        return splash
    except tk.TclError:
        return None


def main() -> int:
    _set_app_user_model_id()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Cannot start the GUI: {exc}", file=sys.stderr)
        return 1

    root.withdraw()
    apply_window_icon(root)
    splash = _show_splash(root)

    def on_error(exc_type, exc_value, exc_tb):
        import traceback

        traceback.print_exception(exc_type, exc_value, exc_tb)
        if root.winfo_exists():
            messagebox.showerror("DNSmuggle error", f"{exc_type.__name__}: {exc_value}")

    root.report_callback_exception = on_error
    MainWindow(root)

    def finish_startup() -> None:
        if splash is not None and splash.winfo_exists():
            splash.destroy()
        root.deiconify()
        root.lift()
        try:
            root.focus_force()
        except tk.TclError:
            pass

    root.after(SPLASH_MS, finish_startup)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
