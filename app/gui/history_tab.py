"""History tab: every transfer, straight out of history.db."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import report
from ..history import History
from ..utils import format_size, format_time
from . import ERROR_FG, SUCCESS_FG, TEXT_OPTIONS, mono_family, open_path

COLUMNS = (
    ("date", "Date", 140, "w"),
    ("filename", "Filename", 260, "w"),
    ("size", "Size", 80, "e"),
    ("session", "Session", 80, "center"),
    ("server", "Server", 140, "w"),
    ("mode", "Mode", 100, "w"),
    ("chunks", "Chunks", 70, "e"),
    ("result", "Result", 70, "center"),
    ("time", "Time taken", 90, "e"),
)


class HistoryTab(ttk.Frame):
    def __init__(self, master, history: History) -> None:
        super().__init__(master, padding=12)
        self.history = history
        self._rows: list[dict] = []
        self._build()
        self.refresh()

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(3, weight=2)

        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self.count_var = tk.StringVar(value="0 transfers")
        ttk.Label(bar, textvariable=self.count_var, style="Head.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        buttons = ttk.Frame(bar)
        buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Button(buttons, text="Clear history", command=self._clear).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="Export to CSV", command=self._export).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="Generate report",
                   command=self._generate_report).pack(side="left", padx=(6, 0))

        table = ttk.Frame(self)
        table.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            table, columns=[c[0] for c in COLUMNS], show="headings", height=10
        )
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=key in ("filename", "server"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("pass", foreground=SUCCESS_FG)
        self.tree.tag_configure("fail", foreground=ERROR_FG)
        self.tree.bind("<<TreeviewSelect>>", self._show_details)

        self._build_details()

    def _build_details(self) -> None:
        frame = ttk.LabelFrame(self, text="Details", padding=10)
        frame.grid(row=2, column=0, rowspan=2, sticky="nsew", pady=(10, 0))
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        grid = ttk.Frame(frame)
        grid.grid(row=0, column=0, sticky="ew")
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        grid.columnconfigure(5, weight=1)

        self.detail_vars: dict[str, tk.StringVar] = {}
        fields = (
            ("date", "Date"), ("direction", "Direction"), ("filename", "Filename"),
            ("size", "Size"), ("session", "Session"), ("server", "Server"),
            ("mode", "Mode"), ("chunks", "Chunks"), ("result", "Result"),
            ("time", "Time taken"), ("size_match", "Size match"),
            ("sha256_match", "SHA256 match"), ("path", "Saved to"),
            ("sha256", "SHA256"),
        )
        for index, (key, label) in enumerate(fields):
            row, col = divmod(index, 3)
            ttk.Label(grid, text=label).grid(row=row, column=col * 2, sticky="w",
                                             padx=(0, 6), pady=1)
            var = tk.StringVar(value="-")
            ttk.Label(grid, textvariable=var,
                      style="Mono.TLabel" if key == "sha256" else "TLabel").grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 18), pady=1
            )
            self.detail_vars[key] = var

        ttk.Label(frame, text="Log snippet").grid(row=1, column=0, sticky="nw",
                                                  pady=(8, 0))
        self.log_view = tk.Text(frame, height=6, wrap="none", state="disabled",
                                font=(mono_family(), 9), **TEXT_OPTIONS)
        self.log_view.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        frame.rowconfigure(2, weight=1)

    # -- data --------------------------------------------------------------

    def refresh(self) -> None:
        self._rows = self.history.list_transfers()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self._rows:
            self.tree.insert(
                "", "end", iid=str(row["id"]),
                values=(
                    row["timestamp"],
                    row["filename"],
                    format_size(row["size"] or 0),
                    row["session"] or "-",
                    f"{row['server'] or '-'}:{row['port'] or '-'}",
                    row["mode"] or "-",
                    row["chunks"] if row["chunks"] is not None else "-",
                    row["result"] or "-",
                    format_time(row["time_seconds"] or 0.0),
                ),
                tags=("pass" if row["result"] == "PASS" else "fail",),
            )
        self.count_var.set(f"{len(self._rows)} transfer"
                           f"{'' if len(self._rows) == 1 else 's'}")

    def _show_details(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.history.get_transfer(int(selection[0]))
        if not row:
            return
        self.detail_vars["date"].set(row["timestamp"])
        self.detail_vars["direction"].set(row["direction"])
        self.detail_vars["filename"].set(row["filename"])
        self.detail_vars["size"].set(
            f"{format_size(row['size'] or 0)} ({row['size']} bytes)"
        )
        self.detail_vars["session"].set(row["session"] or "-")
        self.detail_vars["server"].set(f"{row['server'] or '-'}:{row['port'] or '-'}")
        self.detail_vars["mode"].set(row["mode"] or "-")
        self.detail_vars["chunks"].set(str(row["chunks"] if row["chunks"] is not None else "-"))
        self.detail_vars["result"].set(row["result"] or "-")
        self.detail_vars["time"].set(format_time(row["time_seconds"] or 0.0))
        self.detail_vars["size_match"].set(_bool_text(row["size_match"]))
        self.detail_vars["sha256_match"].set(_bool_text(row["sha256_match"]))
        self.detail_vars["path"].set(row["path"] or "-")
        self.detail_vars["sha256"].set(row["sha256"] or "-")
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.insert("end", row["log"] or "(no log recorded)")
        self.log_view.configure(state="disabled")

    def _generate_report(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("No row selected",
                                   "Click a transfer first, then generate its report.")
            return
        try:
            path, kind = report.generate_report(int(selection[0]), self.history)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Report failed", str(exc))
            return
        if messagebox.askyesno(
            "Report ready",
            f"{kind.upper()} report written to\n{path}\n\nOpen it now?",
        ):
            try:
                open_path(str(path))
            except OSError as exc:
                messagebox.showerror("Cannot open", str(exc))

    def _clear(self) -> None:
        if not self._rows:
            return
        if not messagebox.askyesno(
            "Clear history",
            f"Delete all {len(self._rows)} history rows? The database file stays.",
        ):
            return
        self.history.clear()
        for key in self.detail_vars:
            self.detail_vars[key].set("-")
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.configure(state="disabled")
        self.refresh()

    def _export(self) -> None:
        if not self._rows:
            messagebox.showinfo("Nothing to export", "No transfers recorded yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export history to CSV",
            defaultextension=".csv",
            initialfile="dnstunnel-history.csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            written = self.history.export_csv(path)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))
            return
        messagebox.showinfo("Exported", f"{len(self._rows)} rows to\n{written}")


def _bool_text(value) -> str:
    if value is None:
        return "-"
    return "PASS" if int(value) else "FAIL"
