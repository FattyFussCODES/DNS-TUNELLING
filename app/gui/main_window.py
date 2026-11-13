"""Main window: brand header, the notebook, the shared config and history."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import config
from ..history import History
from . import (
    BRAND_NAME,
    BRAND_TAGLINE,
    APPLogo,
    apply_window_icon,
    load_image,
    mono_family,
)
from .detector_tab import DetectorTab
from .history_tab import HistoryTab
from .receive_tab import ReceiveTab
from .send_tab import SendTab
from .settings_tab import SettingsTab

APP_TITLE = BRAND_NAME


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1100x700")
        root.minsize(940, 620)
        apply_window_icon(root)

        self._apply_style()

        self.config = config.load_config()
        self.history = History(config.history_path(self.config))

        self._build_header()

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(6, 4))

        self.send_tab = SendTab(self.notebook, history=self.history, config=self.config)
        self.receive_tab = ReceiveTab(self.notebook, history=self.history,
                                      config=self.config)
        self.history_tab = HistoryTab(self.notebook, self.history)
        self.detector_tab = DetectorTab(self.notebook, receiver=self.receive_tab,
                                        config=self.config)
        self.settings_tab = SettingsTab(
            self.notebook, config=self.config, on_save=self._apply_settings
        )

        self.notebook.add(self.send_tab, text="  Send  ")
        self.notebook.add(self.receive_tab, text="  Receive  ")
        self.notebook.add(self.history_tab, text="  History  ")
        self.notebook.add(self.detector_tab, text="  Detector  ")
        self.notebook.add(self.settings_tab, text="  Settings  ")

        # One socket: the receiver's. The detector is a passive tap on it.
        self.receive_tab.query_sink = self.detector_tab.observe_query
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        footer = ttk.Label(
            root,
            text=f"{BRAND_NAME} - lab only: your own files, your own machines, "
                 "your own decoder. Port 53 needs Admin on Windows; 5353 does not.",
            foreground="#666666",
            padding=(10, 2, 10, 8),
        )
        footer.pack(fill="x", side="bottom")

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_header(self) -> None:
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=10, pady=(8, 0))

        icon = APPLogo.icon_png()
        if icon is not None:
            try:
                self._logo_image = load_image(self.root, icon, square=48)
                ttk.Label(header, image=self._logo_image).pack(side="left")
            except tk.TclError:
                self._logo_image = None

        title = ttk.Frame(header)
        title.pack(side="left", padx=(10, 0))
        ttk.Label(title, text=BRAND_NAME,
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(title, text=BRAND_TAGLINE, style="Hint.TLabel").pack(anchor="w")

    def _apply_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Ok.TLabel", foreground="#1a7f37")
        style.configure("Bad.TLabel", foreground="#c5221f")
        style.configure("Mono.TLabel", font=(mono_family(), 9))
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))

    def _apply_settings(self, updated: dict) -> None:
        previous_db = config.history_path(self.config)
        self.config = dict(updated)
        new_db = config.history_path(self.config)
        if new_db != previous_db:
            self.history.close()
            self.history = History(new_db)
            for tab in (self.send_tab, self.receive_tab, self.history_tab):
                tab.history = self.history
        self.send_tab.apply_config(self.config)
        self.receive_tab.apply_config(self.config)
        self.detector_tab.apply_config(self.config)
        self.history_tab.refresh()

    def _on_tab_change(self, _event=None) -> None:
        if self.notebook.select() == str(self.history_tab):
            self.history_tab.refresh()

    def _on_close(self) -> None:
        self.send_tab.shutdown()
        self.receive_tab.shutdown()
        self.detector_tab.shutdown()
        self.history.close()
        self.root.destroy()
