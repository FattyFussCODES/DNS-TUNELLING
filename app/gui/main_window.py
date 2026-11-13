"""Main window: a ttk.Notebook holding the Send and Receive tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import mono_family
from .receive_tab import ReceiveTab
from .send_tab import SendTab

APP_TITLE = "DNS Tunnel - Lab File Transfer"


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1100x700")
        root.minsize(940, 620)

        self._apply_style()

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self.send_tab = SendTab(self.notebook)
        self.receive_tab = ReceiveTab(self.notebook)
        self.notebook.add(self.send_tab, text="  Send  ")
        self.notebook.add(self.receive_tab, text="  Receive  ")

        footer = ttk.Label(
            root,
            text="Lab only: your own files, your own machines, your own decoder. "
                 "Port 53 needs Admin on Windows; 5353 does not.",
            foreground="#666666",
            padding=(10, 2, 10, 8),
        )
        footer.pack(fill="x", side="bottom")

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Ok.TLabel", foreground="#1a7f37")
        style.configure("Bad.TLabel", foreground="#c5221f")
        style.configure("Mono.TLabel", font=(mono_family(), 9))
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))

    def _on_close(self) -> None:
        self.send_tab.shutdown()
        self.receive_tab.shutdown()
        self.root.destroy()
