"""Send tab: choose a file, pick a transport, stream it out as DNS queries.

All network work happens on a worker thread; the UI only reads events from a
queue, so the window never freezes mid-transfer.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import config, protocol
from ..utils import format_size, format_time, stamp
from . import mono_family

LOG_LIMIT = 4000


class SendTab(ttk.Frame):
    def __init__(self, master) -> None:
        super().__init__(master, padding=12)
        self._file_path: Path | None = None
        self._file_bytes: bytes | None = None
        self._chunks = 0
        self._preview_header: dict | None = None
        self._slow = False
        self._queue: queue.Queue = queue.Queue()
        self._cancel: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._started = 0.0
        self._total = 0
        self._log_lines = 0
        self._build()
        self.after(80, self._poll)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._build_file_frame().grid(row=0, column=0, sticky="ew")
        self._build_transport_frame().grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._build_actions().grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self._build_log().grid(row=3, column=0, sticky="nsew", pady=(10, 0))

    def _build_file_frame(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="File", padding=10)
        frame.columnconfigure(0, weight=1)

        row = ttk.Frame(frame)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.file_var = tk.StringVar(value="No file selected")
        ttk.Entry(row, textvariable=self.file_var, state="readonly").grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(row, text="Choose file", command=self._choose_file).grid(
            row=0, column=1, padx=(8, 0)
        )

        self.meta_var = tk.StringVar(value="Pick a file to see its size, SHA256 and chunk count.")
        ttk.Label(frame, textvariable=self.meta_var, style="Hint.TLabel",
                  justify="left").grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.sha_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.sha_var, style="Mono.TLabel").grid(
            row=2, column=0, sticky="w"
        )

        self.estimate_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.estimate_var, style="Head.TLabel").grid(
            row=3, column=0, sticky="w", pady=(6, 0)
        )
        return frame

    def _build_transport_frame(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="Transport", padding=10)
        frame.columnconfigure(6, weight=1)

        ttk.Label(frame, text="Preset").grid(row=0, column=0, sticky="w")
        self.preset_var = tk.StringVar(value=config.PRESETS[0]["label"])
        self.preset_box = ttk.Combobox(
            frame, textvariable=self.preset_var, state="readonly", width=24,
            values=[preset["label"] for preset in config.PRESETS],
        )
        self.preset_box.grid(row=0, column=1, sticky="w", padx=(6, 16))
        self.preset_box.bind("<<ComboboxSelected>>", self._on_preset)

        ttk.Label(frame, text="Server").grid(row=0, column=2, sticky="w")
        self.server_var = tk.StringVar(value=config.DEFAULT_SERVER)
        ttk.Entry(frame, textvariable=self.server_var, width=22).grid(
            row=0, column=3, sticky="w", padx=(6, 16)
        )

        ttk.Label(frame, text="Port").grid(row=0, column=4, sticky="w")
        self.port_var = tk.StringVar(value=str(config.DEFAULT_PORT))
        ttk.Entry(frame, textvariable=self.port_var, width=8).grid(
            row=0, column=5, sticky="w", padx=(6, 0)
        )

        ttk.Label(
            frame,
            text="Port 53 needs Admin on Windows; 5353 does not.",
            style="Hint.TLabel",
        ).grid(row=1, column=2, columnspan=4, sticky="w", pady=(4, 0))

        ttk.Label(frame, text="Delay").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.delay_var = tk.DoubleVar(value=config.DEFAULT_DELAY)
        delay_row = ttk.Frame(frame)
        delay_row.grid(row=2, column=1, columnspan=5, sticky="ew", pady=(10, 0))
        delay_row.columnconfigure(0, weight=1)
        self.delay_scale = ttk.Scale(
            delay_row, from_=0.01, to=1.0, variable=self.delay_var,
            orient="horizontal", command=lambda _v: self._on_delay_change(),
        )
        self.delay_scale.grid(row=0, column=0, sticky="ew")
        self.delay_label_var = tk.StringVar(value=f"{config.DEFAULT_DELAY:.2f} s/chunk")
        ttk.Label(delay_row, textvariable=self.delay_label_var, style="Hint.TLabel",
                  width=14).grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Label(frame, text="Password").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.password_var = tk.StringVar(value="")
        self.password_entry = ttk.Entry(frame, textvariable=self.password_var, show="*", width=26)
        self.password_entry.grid(row=3, column=1, columnspan=2, sticky="ew",
                                 padx=(6, 16), pady=(8, 0))
        self.password_entry.bind("<FocusOut>", lambda _e: self._refresh_preview())
        self.password_entry.bind("<Return>", lambda _e: self._refresh_preview())
        self.show_pw_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Show", variable=self.show_pw_var,
                        command=self._toggle_password).grid(row=3, column=3, sticky="w",
                                                            pady=(8, 0))
        ttk.Label(frame, text="Leave blank for no encryption. Receiver needs the same password.",
                  style="Hint.TLabel").grid(row=4, column=1, columnspan=4, sticky="w")

        checks = ttk.Frame(frame)
        checks.grid(row=5, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self.compress_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Compress (zlib, files over 1 KB)",
                        variable=self.compress_var,
                        command=self._refresh_preview).pack(side="left")
        self.encrypt_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(checks, text="Encrypt if password set",
                        variable=self.encrypt_var,
                        command=self._refresh_preview).pack(side="left", padx=(18, 0))
        return frame

    def _build_actions(self) -> ttk.Widget:
        frame = ttk.Frame(self)
        frame.columnconfigure(2, weight=1)

        self.send_button = ttk.Button(frame, text="Send", command=self._start_send)
        self.send_button.grid(row=0, column=0)
        self.cancel_button = ttk.Button(frame, text="Cancel", command=self._cancel_send,
                                        state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=(8, 16))

        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate",
                                        maximum=100)
        self.progress.grid(row=0, column=2, sticky="ew")

        self.progress_var = tk.StringVar(value="Chunks sent: 0/0")
        ttk.Label(frame, textvariable=self.progress_var).grid(row=1, column=0, columnspan=2,
                                                               sticky="w", pady=(6, 0))
        self.rate_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.rate_var, style="Hint.TLabel").grid(
            row=1, column=2, sticky="e", pady=(6, 0)
        )
        return frame

    def _build_log(self) -> ttk.Widget:
        frame = ttk.LabelFrame(self, text="Log", padding=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log = tk.Text(frame, height=12, wrap="none", state="disabled",
                           font=(mono_family(), 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        return frame

    # -- file + preview ----------------------------------------------------

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(title="Choose a file to send")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            messagebox.showerror("Cannot read file", str(exc))
            return
        self._file_path = Path(path)
        self._file_bytes = data
        self.file_var.set(path)
        self._refresh_preview()

    def _password(self) -> str | None:
        if not self.encrypt_var.get():
            return None
        value = self.password_var.get()
        return value or None

    def _refresh_preview(self) -> None:
        self._toggle_password()
        if self._file_bytes is None or self._file_path is None:
            return
        name = self._file_path.name
        try:
            stream, header = protocol.build_stream(
                self._file_bytes, name, password=self._password(),
                compress=self.compress_var.get(),
            )
        except Exception as exc:  # crypto/stdlib failure should not kill the tab
            self.meta_var.set(f"Cannot preview this file: {exc}")
            self.sha_var.set("")
            self.estimate_var.set("")
            self._chunks = 0
            return

        self._chunks = header["chunks"]
        self._preview_header = header
        layers = "raw"
        if header["compressed"]:
            layers = "zlib"
        if header["encrypted"]:
            layers += " + encrypted"
        self.meta_var.set(
            f"{name}  |  {format_size(len(self._file_bytes))}  |  "
            f"{protocol.CHUNK_SIZE}-char chunks ({protocol.CHUNK_PAYLOAD_BYTES} B each)  |  {layers}"
        )
        self.sha_var.set(f"sha256 {header['sha256']}")
        self._update_estimate(len(stream))

    def _update_estimate(self, stream_len: int | None = None) -> None:
        if not self._chunks:
            self.estimate_var.set("")
            return
        delay = float(self.delay_var.get())
        seconds = self._chunks * delay
        shown = format_time(seconds)
        extra = ""
        if stream_len:
            extra = f", {stream_len} base32 chars"
        self.estimate_var.set(
            f"{self._chunks} chunks{extra}  |  about {shown} at {delay:.2f} s/chunk "
            f"(plus ACK waits)"
        )

    def _on_delay_change(self) -> None:
        value = round(float(self.delay_var.get()), 2)
        self.delay_label_var.set(f"{value:.2f} s/chunk")
        self._update_estimate()

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_pw_var.get() else "*")

    def _on_preset(self, _event=None) -> None:
        label = self.preset_var.get()
        for preset in config.PRESETS:
            if preset["label"] == label and preset["server"]:
                self.server_var.set(preset["server"])
                self.port_var.set(str(preset["port"]))
                return

    # -- sending -----------------------------------------------------------

    def _start_send(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        if self._file_path is None or self._file_bytes is None:
            messagebox.showwarning("No file", "Choose a file first.")
            return
        server = self.server_var.get().strip()
        if not server:
            messagebox.showwarning("No server", "Enter the decoder address.")
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Bad port", "Port must be a number from 1 to 65535.")
            return

        delay = round(float(self.delay_var.get()), 2)
        password = self._password()
        compress = self.compress_var.get()

        self._clear_log()
        self._slow = False
        self._started = time.monotonic()
        self._total = 0
        self.progress.configure(value=0, maximum=100)
        self.progress_var.set("Chunks sent: 0/0")
        self.rate_var.set("")
        self._set_running(True)

        self._cancel = threading.Event()
        self._log(
            f"Sending {self._file_path.name} to {server}:{port} "
            f"(delay {delay:.2f}s, compression {'on' if compress else 'off'}, "
            f"encryption {'on' if password else 'off'})"
        )

        self._worker = threading.Thread(
            target=self._run_send,
            args=(self._file_path, server, port, delay, password, compress, self._cancel),
            name="dnstunnel-send",
            daemon=True,
        )
        self._worker.start()

    def _run_send(self, path: Path, server: str, port: int, delay: float,
                  password: str | None, compress: bool, cancel: threading.Event) -> None:
        try:
            protocol.send_file(
                path, server, port,
                delay=delay, password=password, compress=compress,
                cancel=cancel, on_event=self._queue.put,
            )
        except Exception as exc:  # surfaced in the log, never silently swallowed
            self._queue.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            self._queue.put({"type": "worker_finished"})

    def _cancel_send(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self._log("Cancel requested, finishing the chunk in flight...")

    # -- event pump --------------------------------------------------------

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
        if kind == "start":
            self._total = event["chunks"]
            self.progress.configure(maximum=max(1, self._total), value=0)
            layers = "raw"
            if event["compressed"]:
                layers = "zlib"
            if event["encrypted"]:
                layers += " + encrypted"
            self._log(
                f"Session {event['session']} started, {event['chunks']} chunks "
                f"({format_size(event['size'])}), {layers}"
            )
        elif kind == "chunk":
            self.progress.configure(value=event["seq"])
            self.progress_var.set(f"Chunks sent: {event['seq']}/{event['total']}")
            rate, eta = self._rate(event["seq"], event["total"])
            self.rate_var.set(f"{rate:.1f} chunks/s  |  ETA {eta}")
            self._log(f"Chunk {event['seq']:03d} sent, ACK received")
        elif kind == "retry":
            self._log(f"Chunk {event['seq']:03d} no ACK, retry {event['attempt']}/"
                      f"{protocol.MAX_RETRIES}")
        elif kind == "chunk_failed":
            self._log(f"Chunk {event['seq']:03d} failed after {event['attempts']} tries")
        elif kind == "end":
            self._log("END sent, ACK received" if event["acked"]
                      else "END sent, no ACK (receiver may still have every chunk)")
        elif kind == "done":
            elapsed = event["elapsed"]
            self.progress.configure(value=event["total"])
            self.progress_var.set(f"Chunks sent: {event['sent']}/{event['total']}")
            self.rate_var.set(f"{event['sent'] / elapsed:.1f} chunks/s  |  "
                              f"done in {format_time(elapsed)}")
            self._log(f"Done: {event['sent']}/{event['total']} chunks sent, END sent "
                      f"in {format_time(elapsed)}")
            self._set_running(False)
        elif kind == "cancelled":
            self._log(f"Cancelled: {event['sent']}/{event['total']} chunks sent")
            self._set_running(False)
        elif kind == "error":
            self._log(f"Error: {event['message']}")
            self._set_running(False)
        elif kind == "worker_finished":
            if self.send_button.instate(["disabled"]):
                self._set_running(False)

    def _rate(self, done: int, total: int) -> tuple[float, str]:
        elapsed = max(time.monotonic() - self._started, 1e-6)
        rate = done / elapsed
        remaining = max(total - done, 0)
        eta = remaining / rate if rate > 0 else float("inf")
        return rate, format_time(eta) if remaining else "0.0 s"

    def _set_running(self, running: bool) -> None:
        self.send_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")

    # -- log ---------------------------------------------------------------

    def _log(self, message: str) -> None:
        if self._log_lines >= LOG_LIMIT:
            if not self._slow:
                self._slow = True
                self._append("[--:--:--] log truncated at "
                             f"{LOG_LIMIT} lines; the transfer continues\n")
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

    def shutdown(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
