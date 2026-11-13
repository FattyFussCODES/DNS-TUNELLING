"""Entry point: python -m app.main (or the dnstunnel-app script, Step 6)."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from . import __version__
from .gui.main_window import MainWindow


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Cannot start the GUI: {exc}", file=sys.stderr)
        return 1

    def on_error(exc_type, exc_value, exc_tb):
        # Tk swallows callback exceptions into stderr unless a handler is set.
        import traceback

        traceback.print_exception(exc_type, exc_value, exc_tb)
        if root.winfo_exists():
            messagebox.showerror("Unexpected error", f"{exc_type.__name__}: {exc_value}")

    root.report_callback_exception = on_error
    MainWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
