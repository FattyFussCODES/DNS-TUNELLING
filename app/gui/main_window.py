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
    ERROR_FG,
    MUTED_FG,
    RAISED_BG,
    SUCCESS_FG,
    SURFACE_BG,
    TEXT_FG,
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
        root.geometry("1280x800")
        root.minsize(1100, 700)
        apply_window_icon(root)

        self._apply_style()

        self.config = config.load_config()
        self.history = History(config.history_path(self.config))

        self._build_header()
        warnings = getattr(config, "MIGRATION_WARNINGS", ())
        if warnings:
            ttk.Label(
                root,
                text="Data migration needs attention: " + "  ".join(warnings),
                style="Bad.TLabel",
                wraplength=1100,
                padding=(18, 6),
            ).pack(fill="x")

        footer = ttk.Label(
            root,
            text=f"{BRAND_NAME}  /  Lab only: your own files, your own machines, "
                 "your own decoder. Port 53 requires Admin on Windows; 5353 does not.",
            style="Footer.TLabel", padding=(18, 7),
        )
        footer.pack(fill="x", side="bottom")

        shell = ttk.Frame(root)
        shell.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        sidebar = ttk.Frame(shell, style="Sidebar.TFrame", padding=(10, 16))
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        ttk.Label(sidebar, text="WORKSPACE", style="SidebarCaption.TLabel").pack(
            anchor="w", padx=10, pady=(0, 12)
        )
        self.notebook = ttk.Notebook(shell, style="Shell.TNotebook")
        self.notebook.pack(side="left", fill="both", expand=True)

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

        self._nav_buttons = {}
        self._pages = {}
        for label, page in (
            ("Send", self.send_tab),
            ("Receive", self.receive_tab),
            ("History", self.history_tab),
            ("Detector", self.detector_tab),
            ("Settings", self.settings_tab),
        ):
            button = ttk.Button(
                sidebar, text=f"   {label}", style="Nav.TButton",
                command=lambda name=label: self.navigate(name),
                width=16,
            )
            button.pack(fill="x", pady=(0, 4))
            self._nav_buttons[str(page)] = (button, label)
            self._pages[label] = page

        # One socket: the receiver's. The detector is a passive tap on it.
        self.receive_tab.query_sink = self.detector_tab.observe_query
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)
        self.notebook.enable_traversal()
        self._on_tab_change()

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
        ttk.Label(title, text=BRAND_NAME, style="Brand.TLabel").pack(anchor="w")
        ttk.Label(title, text=BRAND_TAGLINE, style="Hint.TLabel").pack(anchor="w")

    def _apply_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        field = "#101010"
        border = "#2c2c2c"
        accent = "#a1a1aa"

        self.root.configure(background=SURFACE_BG)
        self.root.option_add("*Text.background", field)
        self.root.option_add("*Text.foreground", TEXT_FG)
        self.root.option_add("*Text.insertBackground", TEXT_FG)
        self.root.option_add("*Text.selectBackground", "#414141")
        self.root.option_add("*Text.selectForeground", TEXT_FG)
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#414141")
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT_FG)

        style.configure(".", background=SURFACE_BG, foreground=TEXT_FG,
                        font=("Segoe UI", 9))
        style.configure("TFrame", background=SURFACE_BG)
        style.configure("TLabel", background=SURFACE_BG, foreground=TEXT_FG)
        style.configure("Hint.TLabel", foreground=MUTED_FG)
        style.configure("Ok.TLabel", foreground=SUCCESS_FG)
        style.configure("Bad.TLabel", foreground=ERROR_FG)
        style.configure("Mono.TLabel", font=(mono_family(), 9))
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Brand.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Footer.TLabel", background="#101010", foreground=MUTED_FG)
        style.configure("Sidebar.TFrame", background=RAISED_BG)
        style.configure("SidebarCaption.TLabel", background=RAISED_BG,
                        foreground=MUTED_FG, font=("Segoe UI", 8, "bold"))
        style.configure("TButton", background="#262626", foreground=TEXT_FG,
                        bordercolor=border, lightcolor=border, darkcolor=border,
                        focusthickness=2, focuscolor=accent, padding=(9, 5))
        style.map("TButton",
                  background=[("disabled", "#292929"), ("pressed", "#505050"),
                              ("active", "#454545")],
                  foreground=[("disabled", "#858585")])
        style.configure("Nav.TButton", background=RAISED_BG, foreground=MUTED_FG,
                        borderwidth=0, anchor="w", padding=(10, 9))
        style.map("Nav.TButton",
                  background=[("pressed", "#353535"), ("active", "#303030")],
                  foreground=[("active", TEXT_FG)])
        style.configure("Selected.Nav.TButton", background="#262626",
                        foreground=TEXT_FG, font=("Segoe UI", 9, "bold"))
        style.map("Selected.Nav.TButton",
                  background=[("pressed", "#393939"), ("active", "#303030")],
                  foreground=[("active", "#ffffff")])
        style.configure("TLabelframe", background=SURFACE_BG, bordercolor=border,
                        lightcolor=border, darkcolor=border, relief="solid")
        style.configure("TLabelframe.Label", background=SURFACE_BG, foreground=TEXT_FG,
                        font=("Segoe UI", 9, "bold"))
        style.configure("TEntry", fieldbackground=field, foreground=TEXT_FG,
                        insertcolor=TEXT_FG, bordercolor=border, lightcolor=border,
                        darkcolor=border)
        style.configure("TCombobox", fieldbackground=field, foreground=TEXT_FG,
                        background=RAISED_BG, arrowcolor=TEXT_FG, bordercolor=border)
        style.map("TCombobox", fieldbackground=[("readonly", field)],
                  foreground=[("readonly", TEXT_FG)])
        style.configure("Treeview", background=field, fieldbackground=field,
                        foreground=TEXT_FG, bordercolor=border, rowheight=24)
        style.map("Treeview", background=[("selected", "#414141")],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=RAISED_BG, foreground=TEXT_FG,
                        relief="flat", padding=(5, 5))
        style.map("Treeview.Heading", background=[("active", "#454545")])
        style.configure("TProgressbar", background=accent, troughcolor=field,
                        bordercolor=border, lightcolor=accent, darkcolor=accent)
        style.configure("TScrollbar", background="#505050", troughcolor=field,
                        bordercolor=field, lightcolor=field, darkcolor=field,
                        arrowcolor=TEXT_FG)
        style.configure("TCheckbutton", background=SURFACE_BG, foreground=TEXT_FG)
        style.configure("TRadiobutton", background=SURFACE_BG, foreground=TEXT_FG)
        style.configure("Shell.TNotebook", background=SURFACE_BG, borderwidth=0,
                        bordercolor=border, lightcolor=border, darkcolor=border)
        style.layout("Shell.TNotebook.Tab", [])

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

    def navigate(self, name: str) -> None:
        """Select a workspace page by its displayed name."""
        self.notebook.select(self._pages[name])

    def _on_tab_change(self, _event=None) -> None:
        selected = self.notebook.select()
        for page, (button, label) in self._nav_buttons.items():
            active = page == selected
            button.configure(
                text=f"{'▸' if active else ' '}  {label}",
                style="Selected.Nav.TButton" if active else "Nav.TButton",
            )
        if selected == str(self.history_tab):
            self.history_tab.refresh()

    def _on_close(self) -> None:
        self.send_tab.shutdown()
        self.receive_tab.shutdown()
        self.detector_tab.shutdown()
        self.history.close()
        self.root.destroy()
