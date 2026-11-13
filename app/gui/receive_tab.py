"""Receive tab: listen for tunnel queries, show chunks live, verify the file."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import config, protocol
from ..utils import format_size, format_time, sha256_file, stamp
from . import mono_family

LOG_LIMIT = 4000
ROWS_LIMIT = 2000


class ReceiveTab(ttk.Frame):
    def __init__(self, master) -> None:
        super().__init__(master, padding=12)
        self.receiver: protocol.Receiver | None = None
        self.last_result: dict | None = None
        self._queue: queue.Queue = queue.Queue()
        self._log_lines = 0
        self._slow = False
        self._rows = 0
        self._rows_capped = False
        self._build()
        self.after(80, self._poll)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(3, weight=2)

        self._build_listener_frame().grid(row=0, column=0, sticky="ew")
        self._build_chunk_frame().grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self._build_result_frame().grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._build_log().grid(row=3, column=0, sticky="nsew", pady=(10, 0))

    def _build_listener_frame(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="Listener", padding=10)
        frame.columnconfigure(9, weight=1)

        ttk.Label(frame, text="Host").grid(row=0, column=0, sticky="w")
        self.host_var = tk.StringVar(value="0.0.0.0")
        ttk.Entry(frame, textvariable=self.host_var, width=18).grid(
            row=0, column=1, sticky="w", padx=(6, 16)
        )

        ttk.Label(frame, text="Port").grid(row=0, column=2, sticky="w")
        self.port_var = tk.StringVar(value=str(config.DEFAULT_PORT))
        ttk.Entry(frame, textvariable=self.port_var, width=8).grid(
            row=0, column=3, sticky="w", padx=(6, 16)
        )

        ttk.Label(frame, text="Password").grid(row=0, column=4, sticky="w")
        self.password_var = tk.StringVar(value="")
        self.password_entry = ttk.Entry(frame, textvariable=self.password_var, show="*", width=18)
        self.password_entry.grid(row=0, column=5, sticky="w", padx=(6, 8))
        self.show_pw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Show", variable=self.show_pw_var,
                        command=self._toggle_password).grid(row=0, column=6, sticky="w")

        self.start_button = ttk.Button(frame, text="Start", command=self._start)
        self.start_button.grid(row=0, column=7, padx=(16, 0))
        self.stop_button = ttk.Button(frame, text="Stop", command=self._stop,
                                       state="disabled")
        self.stop_button.grid(row=0, column=8, padx=(6, 0))

        self.status_var = tk.StringVar(value="Stopped")
        self.status_label = ttk.Label(frame, textvariable=self.status_var, style="Bad.TLabel")
        self.status_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Label(frame, text="Only needed if the sender encrypted the stream.",
                  style="Hint.TLabel").grid(row=1, column=4, columnspan=5, sticky="w",
                                            pady=(8, 0))

        self.count_var = tk.StringVar(value="Chunks: 0  |  Queries: 0  |  Files: 0")
        ttk.Label(frame, textvariable=self.count_var, style="Hint.TLabel").grid(
            row=2, column=0, columnspan=9, sticky="w", pady=(4, 0)
        )
        return frame

    def _build_chunk_frame(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="Live chunks", padding=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        columns = ("seq", "len", "time", "status", "session", "query")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for column, title, width, anchor, stretch in (
            ("seq", "Seq", 70, "e", False),
            ("len", "Length", 70, "e", False),
            ("time", "Time", 90, "center", False),
            ("status", "Status", 90, "w", False),
            ("session", "Session", 90, "center", False),
            ("query", "Query", 420, "w", True),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        return frame

    def _build_result_frame(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="Result", padding=10)
        frame.columnconfigure(1, weight=1)

        self.result_vars: dict[str, tk.StringVar] = {}
        rows = (
            ("filename", "Filename"),
            ("size", "Size"),
            ("sha256", "SHA256"),
            ("size_match", "Size match"),
            ("sha256_match", "SHA256 match"),
            ("saved", "Saved to"),
        )
        for index, (key, label) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w",
                                              padx=(0, 10), pady=1)
            var = tk.StringVar(value="-")
            style = "Mono.TLabel" if key == "sha256" else "TLabel"
            widget = ttk.Label(frame, textvariable=var, style=style)
            widget.grid(row=index, column=1, sticky="w", pady=1)
            self.result_vars[key] = var
            setattr(self, f"_{key}_label", widget)

        buttons = ttk.Frame(frame)
        buttons.grid(row=0, column=2, rowspan=6, sticky="ne", padx=(16, 0))
        self.open_button = ttk.Button(buttons, text="Open recovered file",
                                      command=self._open_file, state="disabled")
        self.open_button.pack(fill="x")
        self.folder_button = ttk.Button(buttons, text="Open folder",
                                        command=self._open_folder, state="disabled")
        self.folder_button.pack(fill="x", pady=(6, 0))
        self.compare_button = ttk.Button(buttons, text="Compare with original...",
                                         command=self._compare, state="disabled")
        self.compare_button.pack(fill="x", pady=(6, 0))
        return frame

    def _build_log(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="Log", padding=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log = tk.Text(frame, height=9, wrap="none", state="disabled",
                           font=(mono_family(), 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        return frame

    # -- listener control --------------------------------------------------

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_pw_var.get() else "*")

    def _start(self) -> None:
        if self.receiver is not None and self.receiver.running:
            return
        host = self.host_var.get().strip() or "0.0.0.0"
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Bad port", "Port must be a number from 1 to 65535.")
            return
        password = self.password_var.get() or None

        self._clear_results()
        self._clear_log()
        receiver = protocol.Receiver(
            host, port,
            out_dir=config.RECEIVED_DIR,
            password=password,
            on_event=self._queue.put,
        )
        self.receiver = receiver
        try:
            receiver.start()
        except PermissionError:
            hint = ("needs Admin/sudo (ports under 1024)"
                    if port < 1024 else
                    "refused: the port is already in use by another process "
                    "(Windows reports that as permission denied)")
            self._set_status(f"Port {port} {hint}", ok=False)
            self.receiver = None
            return
        except OSError as exc:
            self._set_status(f"Cannot listen on {host}:{port}: {exc}", ok=False)
            self.receiver = None
            return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._set_status(f"Listening on {host}:{receiver.port}", ok=True)

    def _stop(self) -> None:
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._set_status("Stopped", ok=False)

    def _set_status(self, text: str, *, ok: bool) -> None:
        self.status_var.set(text)
        self.status_label.configure(style="Ok.TLabel" if ok else "Bad.TLabel")

    # -- events ------------------------------------------------------------

    def _poll(self) -> None:
        drained = 0
        while drained < 400:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self._handle(event)
        self.after(80, self._poll)

    def _handle(self, event: dict) -> None:
        kind = event["type"]
        if kind == "listening":
            self._log(f"Listening on {event['host']}:{event['port']} "
                      f"for *.{event['domain']}")
        elif kind == "chunk":
            self._add_row(event)
            self._log(f"Session {event['session']}: chunk {event['seq']:>3} "
                      f"({event['count']} stored)")
            self._update_counts()
        elif kind == "duplicate":
            self._log(f"Session {event['session']}: chunk {event['seq']:>3} duplicate "
                      f"({event['count']} stored)")
            self._update_counts()
        elif kind == "complete":
            self._show_result(event)
        elif kind == "end_empty":
            self._log(event["message"])
        elif kind == "error":
            self._log(f"Error: {event['message']}")
        elif kind == "foreign":
            self._log(f"Ignoring foreign query ({event['ignored']} so far): "
                      f"{event['qname'][:70]}")
        elif kind == "ignored":
            self._log(f"Ignoring bad packet: {event['reason']}")
        elif kind == "stopped":
            self._set_status("Stopped", ok=False)

    def _add_row(self, event: dict) -> None:
        if self._rows >= ROWS_LIMIT:
            if not self._rows_capped:
                self._rows_capped = True
                self._log(f"Live chunk table capped at {ROWS_LIMIT} rows; "
                          "the transfer keeps going.")
            return
        self.tree.insert("", "end", values=(
            event["seq"], event["length"], event.get("time", stamp()),
            "received", event["session"], event.get("qname", ""),
        ))
        self._rows += 1
        self.tree.yview_moveto(1.0)

    def _update_counts(self) -> None:
        stats = self.receiver.stats if self.receiver else {"queries": 0, "chunks": 0, "sessions": 0}
        self.count_var.set(
            f"Chunks: {stats['chunks']}  |  Queries: {stats['queries']}  |  "
            f"Files: {stats['sessions']}"
        )

    def _show_result(self, event: dict) -> None:
        self.last_result = event
        self.result_vars["filename"].set(event["filename"])
        self.result_vars["size"].set(
            f"{format_size(event['size'])}  ({event['size']} bytes, "
            f"{event['chunks']} chunks, {format_time(event['elapsed'])})"
        )
        self.result_vars["sha256"].set(event["sha256"])
        self.result_vars["size_match"].set("PASS" if event["size_match"] else "FAIL")
        self.result_vars["sha256_match"].set("PASS" if event["sha256_match"] else "FAIL")
        self.result_vars["saved"].set(event["path"])
        for key in ("size_match", "sha256_match"):
            self.__dict__[f"_{key}_label"].configure(
                style="Ok.TLabel" if event[key] else "Bad.TLabel"
            )
        for button in (self.open_button, self.folder_button, self.compare_button):
            button.configure(state="normal")

        self._update_counts()
        self._log(f"Session {event['session']}: rebuilt {event['filename']} -> {event['path']}")
        self._log(f"  size match: {event['size_match']} "
                  f"({event['size']} / {event['expected_size']})")
        self._log(f"  sha256 match: {event['sha256_match']}")
        if event["encrypted"]:
            self._log("  stream was encrypted (decrypted with the password on this tab)")
        if event["compressed"]:
            self._log("  stream was zlib-compressed")
        if not (event["size_match"] and event["sha256_match"]):
            self._log("  transfer FAILED verification; the saved file is kept for inspection")

    # -- result actions ----------------------------------------------------

    def _open_file(self) -> None:
        if not self.last_result:
            return
        path = self.last_result["path"]
        try:
            _open_path(path)
        except OSError as exc:
            messagebox.showerror("Cannot open", str(exc))

    def _open_folder(self) -> None:
        folder = config.RECEIVED_DIR
        folder.mkdir(parents=True, exist_ok=True)
        try:
            _open_path(str(folder))
        except OSError as exc:
            messagebox.showerror("Cannot open", str(exc))

    def _compare(self) -> None:
        if not self.last_result:
            return
        original = filedialog.askopenfilename(title="Pick the original file to compare")
        if not original:
            return
        recovered = self.last_result["path"]
        want = sha256_file(original)
        got = sha256_file(recovered)
        same = want == got
        messagebox.showinfo(
            "Compare SHA256",
            f"Original\n  {original}\n  {want}\n\n"
            f"Recovered\n  {recovered}\n  {got}\n\n"
            f"{'MATCH - byte identical' if same else 'MISMATCH'}",
        )

    # -- log ---------------------------------------------------------------

    def _log(self, message: str) -> None:
        if self._log_lines >= LOG_LIMIT:
            if not self._slow:
                self._slow = True
                self._append(f"[--:--:--] log truncated at {LOG_LIMIT} lines\n")
            return
        self._append(f"[{stamp()}] {message}\n")

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self._log_lines += 1
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._log_lines = 0
        self._slow = False

    def _clear_results(self) -> None:
        self.last_result = None
        for key, var in self.result_vars.items():
            var.set("-")
        for key in ("size_match", "sha256_match"):
            self.__dict__[f"_{key}_label"].configure(style="TLabel")
        for button in (self.open_button, self.folder_button, self.compare_button):
            button.configure(state="disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._rows = 0
        self._rows_capped = False
        self.count_var.set("Chunks: 0  |  Queries: 0  |  Files: 0")

    def shutdown(self) -> None:
        if self.receiver is not None:
            self.receiver.stop()
            self.receiver = None


def _open_path(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
