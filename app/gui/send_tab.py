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

from .. import config as app_config, protocol
from ..utils import format_size, format_time, stamp
from . import mono_family, text_tail

LOG_LIMIT = 4000


class SendTab(ttk.Frame):
    def __init__(self, master, *, history=None, config=None) -> None:
        super().__init__(master, padding=12)
        self.history = history
        self.cfg = dict(config) if config is not None else dict(app_config.DEFAULTS)
        self._mode = self.cfg.get("mode", app_config.DEFAULTS["mode"])
        self._file_path: Path | None = None
        self._file_bytes: bytes | None = None
        self._chunks = 0
        self._stream_len = 0
        self._acked = 0
        self._preview_header: dict | None = None
        self._slow = False
        self._queue: queue.Queue = queue.Queue()
        self._cancel: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._started = 0.0
        self._total = 0
        self._log_lines = 0
        self._run_info: dict = {}
        self._recorded = False
        self._build()
        self.chunk_size_var.trace_add("write", self._on_chunk_size_change)
        self.password_var.trace_add("write", lambda *_args: self._refresh_preview())
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
        self.preset_var = tk.StringVar(value=app_config.PRESETS[0]["label"])
        self.preset_box = ttk.Combobox(
            frame, textvariable=self.preset_var, state="readonly", width=24,
            values=[preset["label"] for preset in app_config.PRESETS],
        )
        self.preset_box.grid(row=0, column=1, sticky="w", padx=(6, 16))
        self.preset_box.bind("<<ComboboxSelected>>", self._on_preset)

        ttk.Label(frame, text="Server").grid(row=0, column=2, sticky="w")
        self.server_var = tk.StringVar(value=self.cfg["server"])
        ttk.Entry(frame, textvariable=self.server_var, width=22).grid(
            row=0, column=3, sticky="w", padx=(6, 16)
        )

        ttk.Label(frame, text="Port").grid(row=0, column=4, sticky="w")
        self.port_var = tk.StringVar(value=str(self.cfg["port"]))
        ttk.Entry(frame, textvariable=self.port_var, width=8).grid(
            row=0, column=5, sticky="w", padx=(6, 0)
        )

        ttk.Label(
            frame,
            text="Port 53 needs Admin on Windows; 5353 does not.",
            style="Hint.TLabel",
        ).grid(row=1, column=2, columnspan=4, sticky="w", pady=(4, 0))

        ttk.Label(frame, text="Delay").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.delay_var = tk.DoubleVar(value=self.cfg["delay"])
        delay_row = ttk.Frame(frame)
        delay_row.grid(row=2, column=1, columnspan=5, sticky="ew", pady=(10, 0))
        delay_row.columnconfigure(0, weight=1)
        self.delay_scale = ttk.Scale(
            delay_row, from_=0.01, to=1.0, variable=self.delay_var,
            orient="horizontal", command=lambda _v: self._on_delay_change(),
        )
        self.delay_scale.grid(row=0, column=0, sticky="ew")
        self.delay_label_var = tk.StringVar(value=f"{self.cfg['delay']:.2f} s/chunk")
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

        ttk.Label(frame, text="Chunk size").grid(row=5, column=0, sticky="w", pady=(8, 0))
        chunk_row = ttk.Frame(frame)
        chunk_row.grid(row=5, column=1, columnspan=5, sticky="ew", pady=(8, 0))
        chunk_row.columnconfigure(0, weight=1)
        self.chunk_size_var = tk.IntVar(value=protocol.CHUNK_SIZE)
        self.chunk_scale = tk.Scale(
            chunk_row, from_=16, to=63, resolution=1, orient="horizontal",
            variable=self.chunk_size_var, showvalue=False, highlightthickness=0,
        )
        self.chunk_scale.grid(row=0, column=0, sticky="ew")
        self.chunk_size_label_var = tk.StringVar(value=f"{protocol.CHUNK_SIZE} chars")
        ttk.Label(chunk_row, textvariable=self.chunk_size_label_var,
                  width=14).grid(row=0, column=1, padx=(12, 0))
        self.chunk_warning_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.chunk_warning_var, style="Hint.TLabel").grid(
            row=6, column=1, columnspan=5, sticky="w"
        )

        checks = ttk.Frame(frame)
        checks.grid(row=7, column=0, columnspan=6, sticky="w", pady=(8, 0))
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
        self.window_var = tk.StringVar(
            value=f"Window: {protocol.WINDOW_SIZE} chunks, ACK after {protocol.WINDOW_SIZE}"
        )
        ttk.Label(frame, textvariable=self.window_var, style="Hint.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0)
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
                chunk_size=self.chunk_size_var.get(),
            )
        except Exception as exc:  # crypto/stdlib failure should not kill the tab
            self.meta_var.set(f"Cannot preview this file: {exc}")
            self.sha_var.set("")
            self.estimate_var.set("")
            self._chunks = 0
            self._stream_len = 0
            return

        self._chunks = len(protocol.chunk_stream(stream, chunk_size=self.chunk_size_var.get()))
        self._stream_len = len(stream)
        self._preview_header = header
        layers = "raw"
        if header["compressed"]:
            layers = "zlib"
        if header["encrypted"]:
            layers += " + encrypted"
        self.meta_var.set(
            f"{name}  |  {format_size(len(self._file_bytes))}  |  "
            f"{self.chunk_size_var.get()}-char chunks  |  {layers}"
        )
        self.sha_var.set(f"sha256 {header['sha256']}")
        self._update_estimate()

    def _update_estimate(self) -> None:
        if not self._chunks:
            self.estimate_var.set("")
            return
        delay = float(self.delay_var.get())
        seconds = self._chunks * delay
        shown = format_time(seconds)
        extra = ""
        if self._stream_len:
            extra = f", {self._stream_len} base32 chars"
        self.estimate_var.set(
            f"{self._chunks} chunks{extra}  |  about {shown} at {delay:.2f} s/chunk "
            f"(plus ACK waits)"
        )

    def _on_delay_change(self) -> None:
        value = round(float(self.delay_var.get()), 2)
        self.delay_label_var.set(f"{value:.2f} s/chunk")
        self._update_estimate()

    def _on_chunk_size_change(self, *_args) -> None:
        value = self.chunk_size_var.get()
        clamped = max(16, min(63, value))
        if value != clamped:
            self.chunk_size_var.set(clamped)
            warning = f"Chunk size {value} is outside 16-63; using {clamped}."
        elif clamped > 40:
            warning = "Chunk size >40 will trigger the Detector length rule."
        else:
            warning = ""
        if clamped > 40 and value != clamped:
            warning += " Chunk size >40 will trigger the Detector length rule."
        self.chunk_warning_var.set(warning)
        self.chunk_size_label_var.set(f"{clamped} chars")
        self._refresh_preview()

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_pw_var.get() else "*")

    def _on_preset(self, _event=None) -> None:
        label = self.preset_var.get()
        for preset in app_config.PRESETS:
            if preset["label"] == label:
                self._mode = preset["mode"]
                if preset["server"]:
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
        chunk_size = self.chunk_size_var.get()

        self._clear_log()
        self._slow = False
        self._started = time.monotonic()
        self._run_info = {}
        self._recorded = False
        self._total = 0
        self._acked = 0
        self.window_var.set(
            f"Window: {protocol.WINDOW_SIZE} chunks, ACK after {protocol.WINDOW_SIZE}"
        )
        self.progress.configure(value=0, maximum=100)
        self.progress_var.set("Chunks sent: 0/0")
        self.rate_var.set("")
        self._set_running(True)

        self._cancel = threading.Event()
        self._log(
            f"Sending {self._file_path.name} to {server}:{port} "
            f"(delay {delay:.2f}s, chunk size {chunk_size}, compression {'on' if compress else 'off'}, "
            f"encryption {'on' if password else 'off'})"
        )

        self._worker = threading.Thread(
            target=self._run_send,
            args=(self._file_path, server, port, delay, password, compress, chunk_size, self._cancel),
            name="dnstunnel-send",
            daemon=True,
        )
        self._worker.start()

    def _run_send(self, path: Path, server: str, port: int, delay: float,
                  password: str | None, compress: bool, chunk_size: int,
                  cancel: threading.Event) -> None:
        try:
            protocol.send_file(
                path, server, port,
                delay=delay, password=password, compress=compress, chunk_size=chunk_size,
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
            self._run_info = {
                "filename": event["filename"],
                "size": event["size"],
                "sha256": event["sha256"],
                "session": event["session"],
                "chunks": event["chunks"],
            }
            self.progress.configure(maximum=max(1, self._total), value=0)
            self.window_var.set(
                f"Window: {protocol.WINDOW_SIZE} chunks, ACK after {protocol.WINDOW_SIZE}"
            )
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
            self._acked += 1
            self.progress.configure(value=self._acked)
            self.progress_var.set(f"Chunks sent: {self._acked}/{event['total']}")
            rate, eta = self._rate(self._acked, event["total"])
            self.rate_var.set(f"{rate:.1f} chunks/s  |  ETA {eta}")
            self._log(f"Chunk {event['seq']:03d} sent, ACK received")
        elif kind == "retry":
            self._log(f"Chunk {event['seq']:03d} no ACK, retry {event['attempt']}/"
                      f"{protocol.MAX_RETRIES}")
        elif kind == "window":
            self.window_var.set(
                f"Window: {protocol.WINDOW_SIZE} chunks, ACK after {protocol.WINDOW_SIZE}"
                f"  |  {event['window']}/{event['windows']} completed"
            )
            before = (event["window"] - 1) * protocol.WINDOW_SIZE
            window_total = min(protocol.WINDOW_SIZE, event["total"] - before)
            self._log(
                f"Window {event['window']}/{event['windows']} sent, "
                f"{event['acked'] - before}/{window_total} ACKs"
            )
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
            self._record("PASS", elapsed)
            self._set_running(False)
        elif kind == "cancelled":
            self._log(f"Cancelled: {event['sent']}/{event['total']} chunks sent")
            self._record("FAIL", time.monotonic() - self._started)
            self._set_running(False)
        elif kind == "error":
            self._log(f"Error: {event['message']}")
            self._record("FAIL", time.monotonic() - self._started)
            self._set_running(False)
        elif kind == "worker_finished":
            if self.send_button.instate(["disabled"]):
                self._set_running(False)

    def _record(self, result: str, elapsed: float | None) -> None:
        """One history row per run, PASS only when every chunk was ACKed."""
        if self.history is None or self._recorded or not self._run_info:
            return
        self._recorded = True
        info = self._run_info
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = None
        self.history.save_transfer(
            direction="send",
            filename=info.get("filename", "?"),
            size=info.get("size", 0),
            sha256=info.get("sha256"),
            session=info.get("session"),
            server=self.server_var.get().strip(),
            port=port,
            mode=self._mode_for(self.server_var.get().strip()),
            chunks=info.get("chunks"),
            result=result,
            time_seconds=elapsed,
            log=text_tail(self.log),
        )

    def _mode_for(self, server: str) -> str:
        for preset in app_config.PRESETS:
            if preset["server"] and preset["server"] == server:
                return preset["mode"]
        return "Custom"

    def apply_config(self, config: dict) -> None:
        """Called by the Settings tab after a save."""
        self.cfg = dict(config)
        self.server_var.set(self.cfg["server"])
        self.port_var.set(str(self.cfg["port"]))
        self.delay_var.set(self.cfg["delay"])
        self._on_delay_change()
        self._mode = self.cfg.get("mode", self._mode)

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
