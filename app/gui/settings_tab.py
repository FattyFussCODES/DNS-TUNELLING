"""Settings tab: defaults, transport mode, peer-tool status, About."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import __version__, config as app_config


class SettingsTab(ttk.Frame):
    def __init__(self, master, *, config: dict, on_save=None) -> None:
        super().__init__(master, padding=12)
        self.cfg = dict(config)
        self.on_save = on_save
        self._mode = self.cfg.get("mode", "Skein")
        self._build()
        self._load_into_widgets()
        self._refresh_status()

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        defaults = ttk.LabelFrame(self, text="Defaults", padding=10)
        defaults.grid(row=0, column=0, sticky="ew")
        defaults.columnconfigure(1, weight=1)

        self.server_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.delay_var = tk.StringVar()
        self.received_var = tk.StringVar()
        self.history_var = tk.StringVar()

        self._row(defaults, 0, "Default server", self.server_var)
        self._row(defaults, 1, "Default port", self.port_var, width=10)
        self._row(defaults, 2, "Default delay (s/chunk)", self.delay_var, width=10)
        self._browse_row(defaults, 3, "Received folder", self.received_var, "dir")
        self._browse_row(defaults, 4, "History database", self.history_var, "db")

        ttk.Label(
            defaults,
            text="Relative paths are resolved against the app folder. "
                 "Port 53 needs Admin; 5353 does not.",
            style="Hint.TLabel",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

        mode_frame = ttk.LabelFrame(self, text="Transport mode", padding=10)
        mode_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.mode_var = tk.StringVar(value=self._mode)
        for index, mode in enumerate(app_config.MODES):
            label = f"{mode} ({app_config.DOMAIN_MODE_SERVER})" if mode == "Domain" else mode
            ttk.Radiobutton(
                mode_frame, text=label, value=mode, variable=self.mode_var,
                command=self._on_mode_change,
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 18), pady=2)

        self.domain_verified_var = tk.BooleanVar(value=bool(self.cfg["domain_verified"]))
        self.domain_check = ttk.Checkbutton(
            mode_frame,
            text="I ran the direct public relay test and it passed",
            variable=self.domain_verified_var,
        )
        self.domain_check.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self.domain_warning_var = tk.StringVar(value="")
        self.domain_warning = ttk.Label(
            mode_frame, textvariable=self.domain_warning_var, style="Bad.TLabel",
            wraplength=980, justify="left",
        )
        self.domain_warning.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        status_frame = ttk.LabelFrame(self, text="Peer tools", padding=10)
        status_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        status_frame.columnconfigure(1, weight=1)
        self.skein_var = tk.StringVar(value="checking...")
        self.playit_var = tk.StringVar(value="checking...")
        ttk.Label(status_frame, text="Skein").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.skein_var, style="Hint.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Label(status_frame, text="Playit").grid(row=1, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.playit_var, style="Hint.TLabel").grid(
            row=1, column=1, sticky="w", padx=(10, 0)
        )
        ttk.Button(status_frame, text="Re-check", command=self._refresh_status).grid(
            row=0, column=2, rowspan=2, sticky="e"
        )

        about = ttk.LabelFrame(self, text="About", padding=10)
        about.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            about,
            text=(
                f"DNS Tunnel - Lab File Transfer {__version__}\n"
                f"Author: {'Aviral Bohra'}\n"
                "Lab only: your own machines, own files, own decoder. MIT licence."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Save", command=self._save).pack(side="left")
        self.save_status = tk.StringVar(value="")
        ttk.Label(actions, textvariable=self.save_status, style="Ok.TLabel").pack(
            side="left", padx=(10, 0)
        )

    def _row(self, parent, row: int, label: str, var: tk.StringVar, width: int = 30):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=1, sticky="w", padx=(10, 0), pady=2
        )

    def _browse_row(self, parent, row: int, label: str, var: tk.StringVar, kind: str):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=var, width=52).grid(
            row=row, column=1, sticky="ew", padx=(10, 0), pady=2
        )
        ttk.Button(
            parent, text="Browse", command=lambda: self._browse(var, kind)
        ).grid(row=row, column=2, sticky="w", padx=(6, 0), pady=2)

    def _browse(self, var: tk.StringVar, kind: str) -> None:
        if kind == "dir":
            path = filedialog.askdirectory(title="Choose the received-files folder")
        else:
            path = filedialog.asksaveasfilename(
                title="Choose the history database",
                defaultextension=".db",
                initialfile="history.db",
                filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
            )
        if path:
            var.set(path)

    # -- state -------------------------------------------------------------

    def _load_into_widgets(self) -> None:
        self.server_var.set(str(self.cfg["server"]))
        self.port_var.set(str(self.cfg["port"]))
        self.delay_var.set(f"{float(self.cfg['delay']):.2f}")
        self.received_var.set(str(self.cfg["received_dir"]))
        self.history_var.set(str(self.cfg["history_db"]))
        self.mode_var.set(self.cfg.get("mode", "Skein"))
        self._on_mode_change()

    def _on_mode_change(self) -> None:
        if self.mode_var.get() != "Domain":
            self.domain_warning_var.set("")
            return
        if self.domain_verified_var.get():
            self.domain_warning_var.set(
                "Domain mode: sends to 8.8.8.8, so the domain needs NS + glue "
                "records pointing at your decoder. You marked the public relay "
                "test as passed."
            )
        else:
            self.domain_warning_var.set(
                "Domain mode is NOT verified yet. It needs ns1.dnstunnel.cc.cd glue "
                "to your public decoder IP and an NS change, and the direct public "
                "relay test (docs/PORT_FORWARDING_TEST.md) must pass first. "
                "Saving with Domain selected will ask you to confirm."
            )

    def _refresh_status(self) -> None:
        self.skein_var.set(_skein_status())
        configured = str(self.cfg.get("playit_address") or "").strip()
        self.playit_var.set(_playit_status(configured))

    # -- save --------------------------------------------------------------

    def _save(self) -> None:
        server = self.server_var.get().strip()
        if not server:
            messagebox.showwarning("Bad server", "Default server must not be empty.")
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Bad port", "Port must be 1-65535.")
            return
        try:
            delay = round(float(self.delay_var.get()), 2)
            if not 0.01 <= delay <= 1.0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Bad delay", "Delay must be between 0.01 and 1.0.")
            return

        mode = self.mode_var.get()
        domain_verified = bool(self.domain_verified_var.get())
        if mode == "Domain":
            if not domain_verified:
                messagebox.showwarning(
                    "Domain mode not verified",
                    "Domain mode needs glue + NS records and a passing direct "
                    "public relay test. Tick the confirmation or pick another mode.",
                )
                self.mode_var.set(self.cfg.get("mode", "Skein"))
                self._on_mode_change()
                return
            if not messagebox.askyesno(
                "Enable Domain mode?",
                "Domain mode sends the tunnel to 8.8.8.8 and relies on "
                "ns1.dnstunnel.cc.cd glue plus an NS change. Enable it?",
            ):
                self.mode_var.set(self.cfg.get("mode", "Skein"))
                self._on_mode_change()
                return

        updated = dict(self.cfg)
        updated.update({
            "server": server,
            "port": port,
            "delay": delay,
            "received_dir": self.received_var.get().strip() or "received",
            "history_db": self.history_var.get().strip() or "history.db",
            "mode": mode,
            "domain_verified": domain_verified,
        })
        try:
            written = app_config.save_config(updated)
        except OSError as exc:
            messagebox.showerror("Cannot save", str(exc))
            return

        self.cfg = updated
        self.save_status.set(f"Saved to {written.name}")
        self._on_mode_change()
        self._refresh_status()
        if self.on_save is not None:
            self.on_save(updated)


def _run(cmd: list[str], timeout: float = 3.0) -> str | None:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout or "").strip()


def _process_running(name: str) -> bool:
    if sys.platform.startswith("win"):
        out = _run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/NH"])
        return bool(out) and name.lower() in out.lower()
    return shutil.which("pgrep") is not None and _run(["pgrep", "-x", name]) not in (None, "")


def _skein_status() -> str:
    cli = shutil.which("skein") or shutil.which("skein.exe")
    if cli:
        for args in (["peers"], ["status"]):
            out = _run([cli, *args])
            if out:
                return "skein " + " ".join(args) + ": " + out.replace("\n", "; ")[:300]
        return f"Skein CLI found at {cli} (no peers output)"
    if _process_running("skeind"):
        return ("Skein service 'skeind' is running, but no skein CLI is on PATH, "
                "so peers cannot be read here. Open Skein Desktop to see them.")
    return "Skein not detected, start Skein Desktop"


def _playit_status(configured: str) -> str:
    cli = shutil.which("playit") or shutil.which("playit.exe")
    if cli:
        out = _run([cli, "status"])
        if out:
            return out.replace("\n", "; ")[:300]
        return f"Playit CLI found at {cli}"
    if _process_running("playit"):
        base = "Playit agent is running (tunnel address not reported by CLI)"
        return f"{base}; configured: {configured}" if configured else base
    if configured:
        return f"Playit not detected; configured address: {configured}"
    return "Playit not detected, start the Playit agent and set playit_address in config.json"
