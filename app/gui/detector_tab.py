"""Detector tab: passive detection on the Receiver's socket.

No second bind. The Receive tab owns the one UDP socket; this tab subscribes
to `protocol.Receiver.on_query` and evaluates every parsed DNS question.
Starting monitoring here starts that shared listener if it is not running.
Stopping only detaches the detector; the receiver keeps listening.
"""

from __future__ import annotations

import os
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .. import config as app_config, detector, protocol

ALERT_ROWS_LIMIT = 500
GRAPH_SECONDS = 60
ENCODER_TEST_CHUNKS = 25


class DetectorTab(ttk.Frame):
    def __init__(self, master, *, receiver=None, config=None) -> None:
        super().__init__(master, padding=12)
        self.cfg = dict(config) if config is not None else dict(app_config.DEFAULTS)
        self.receiver = receiver          # the ReceiveTab, i.e. the socket owner
        self.detector = detector.Detector()
        self.observing = False
        self._queue: queue.Queue = queue.Queue()
        self._qps: dict[int, int] = {}
        self._rows = 0
        self._build()
        self.after(80, self._poll)
        self.after(500, self._redraw)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        controls = ttk.LabelFrame(self, text="Monitor (shared listener)", padding=10)
        controls.grid(row=0, column=0, sticky="ew")

        self.listener_var = tk.StringVar(value="Receiver: not listening")
        ttk.Label(controls, textvariable=self.listener_var, style="Head.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        self.start_button = ttk.Button(controls, text="Start monitoring",
                                       command=self._start)
        self.start_button.grid(row=0, column=1, padx=(16, 0))
        self.stop_button = ttk.Button(controls, text="Stop monitoring",
                                      command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(6, 0))

        self.status_var = tk.StringVar(value="Detached")
        self.status_label = ttk.Label(controls, textvariable=self.status_var,
                                      style="Bad.TLabel")
        self.status_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Label(
            controls,
            text="The detector never opens a socket: it reads every query the "
                 "Receive tab's listener sees. Set host and port on the Receive tab.",
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tests = ttk.Frame(controls)
        tests.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(tests, text="Test with my encoder",
                   command=self._test_my_encoder).pack(side="left")
        ttk.Button(tests, text="Test with normal DNS",
                   command=self._test_normal_dns).pack(side="left", padx=(6, 0))
        ttk.Button(tests, text="Clear", command=self._clear).pack(side="left", padx=(6, 0))

        self.stats_var = tk.StringVar(
            value="Queries: 0  |  Alerts: 0  |  Rules in window: -"
        )
        ttk.Label(controls, textvariable=self.stats_var, style="Hint.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        graph_frame = ttk.LabelFrame(self, text="Queries per second", padding=6)
        graph_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        graph_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(graph_frame, height=140, bg="white",
                                highlightthickness=1, highlightbackground="#cccccc")
        self.canvas.grid(row=0, column=0, sticky="ew")

        self.banner_var = tk.StringVar(value="")
        self.banner = ttk.Label(self, textvariable=self.banner_var, style="Bad.TLabel",
                                font=("Segoe UI", 11, "bold"))
        self.banner.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.banner.grid_remove()

        alerts_frame = ttk.LabelFrame(self, text="Alerts", padding=6)
        alerts_frame.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        alerts_frame.columnconfigure(0, weight=1)
        alerts_frame.rowconfigure(0, weight=1)

        columns = ("time", "rule", "reason", "qname")
        self.tree = ttk.Treeview(alerts_frame, columns=columns, show="headings",
                                 height=8)
        for key, title, width, anchor, stretch in (
            ("time", "Time", 90, "center", False),
            ("rule", "Rule", 90, "w", False),
            ("reason", "Reason", 320, "w", False),
            ("qname", "Example query", 500, "w", True),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(alerts_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("warn", foreground="#c5221f")

    # -- attach / detach ---------------------------------------------------

    def _start(self) -> bool:
        if self.receiver is None:
            self._set_status("No receiver available", ok=False)
            return False
        ok, message = self.receiver.start_listening()
        if not ok:
            self._set_status(message, ok=False)
            self._update_listener_label()
            return False

        self.observing = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.listener_var.set(f"Receiver: {message}")
        self._set_status(f"Monitoring {message}", ok=True)
        return True

    def _stop(self) -> None:
        self.observing = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.banner_var.set("")
        self.banner.grid_remove()
        if self._receiver_running():
            self._set_status("Detached - the receiver is still listening", ok=False)
        else:
            self._set_status("Detached - receiver stopped", ok=False)

    def _set_status(self, text: str, *, ok: bool) -> None:
        self.status_var.set(text)
        self.status_label.configure(style="Ok.TLabel" if ok else "Bad.TLabel")

    def _update_listener_label(self) -> None:
        if self.receiver is not None and self.receiver.receiver is not None \
                and self.receiver.receiver.running:
            self.listener_var.set(
                f"Receiver: {self.receiver.host_var.get()}:{self.receiver.listen_port}"
            )
        else:
            self.listener_var.set("Receiver: not listening")

    def _receiver_running(self) -> bool:
        return (self.receiver is not None
                and self.receiver.receiver is not None
                and self.receiver.receiver.running)

    # -- tap called on the listener thread ---------------------------------

    def observe_query(self, qname: str, source: str) -> None:
        if not self.observing:
            return
        result = self.detector.observe(qname, source)
        second = int(time.time())
        self._qps[second] = self._qps.get(second, 0) + 1
        if result["alerts"] or result["warning"]:
            self._queue.put({
                "type": "query",
                "qname": qname,
                "source": source,
                "time": result["time"],
                "alerts": result["alerts"],
                "warning": result["warning"],
                "rules_in_window": result["rules_in_window"],
            })

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
        if kind == "query":
            for alert in event["alerts"]:
                self._add_alert(event, alert)
            if event["warning"]:
                rules = ", ".join(event["rules_in_window"])
                self.banner_var.set(
                    f"Possible DNS tunnel detected - {len(event['rules_in_window'])} "
                    f"rules fired within 60 s ({rules})"
                )
                self.banner.grid()
            self._update_stats(event["rules_in_window"])
        elif kind == "selftest_done":
            self._set_status(event["message"], ok=event.get("ok", True))
            self._update_stats(sorted(self.detector._rule_fires))

    def _add_alert(self, event: dict, alert: dict) -> None:
        if self._rows >= ALERT_ROWS_LIMIT:
            return
        self.tree.insert(
            "", 0,
            values=(event.get("time", time.strftime("%H:%M:%S")), alert["rule"],
                    alert["reason"], event["qname"][:110]),
            tags=("warn",),
        )
        self._rows += 1

    def _update_stats(self, rules) -> None:
        self.stats_var.set(
            f"Queries: {self.detector.queries}  |  Alerts: {self.detector.alerts}  |  "
            f"Rules in window: {', '.join(rules) if rules else '-'}"
        )

    def _clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._rows = 0
        self.detector.reset()
        self._qps.clear()
        self.banner_var.set("")
        self.banner.grid_remove()
        self._update_stats([])

    # -- self-tests --------------------------------------------------------

    def _test_my_encoder(self) -> None:
        """Real encoder chunks through the shared listener.

        Chunks only, no END: the detector still sees exactly what a transfer
        sends, while the receiver does not save a junk file or a history row.
        """
        if not self._start():
            return
        port = self.receiver.listen_port
        if port is None:
            self._set_status("Receiver is not listening", ok=False)
            return
        self._clear()
        self._set_status("Encoder self-test running (real tunnel chunks)...", ok=True)

        def run() -> None:
            before = self.detector.alerts
            try:
                stream, header = protocol.build_stream(
                    os.urandom(1200), "detector-selftest.txt", compress=False
                )
                chunks = protocol.chunk_stream(stream)[:ENCODER_TEST_CHUNKS]
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sent = 0
                try:
                    for seq, chunk in enumerate(chunks, start=1):
                        qname = f"{seq:03d}.{chunk}.{header['session']}.dnstunnel.cc.cd"
                        if protocol.send_query(sock, qname, "127.0.0.1", port,
                                               timeout=1.0, max_retries=2):
                            sent += 1
                        time.sleep(0.01)
                finally:
                    sock.close()
                fired = self.detector.alerts - before
                self._queue.put({
                    "type": "selftest_done",
                    "ok": fired > 0,
                    "message": (f"Encoder test: {sent} encoder chunks sent, "
                                f"{fired} alerts raised"),
                })
            except Exception as exc:  # surfaced, never swallowed
                self._queue.put({"type": "selftest_done", "ok": False,
                                 "message": f"Encoder test failed: {exc}"})

        threading.Thread(target=run, name="detector-selftest", daemon=True).start()

    def _test_normal_dns(self) -> None:
        """Ordinary names through the same listener; they must raise no alerts."""
        if not self._start():
            return
        port = self.receiver.listen_port
        if port is None:
            self._set_status("Receiver is not listening", ok=False)
            return
        self._clear()
        self._set_status("Normal-DNS test running...", ok=True)
        names = [
            "www.google.com", "mail.google.com", "api.github.com",
            "docs.python.org", "fonts.gstatic.com", "time.windows.com",
            "outlook.office365.com", "example.com",
        ]

        def run() -> None:
            before = self.detector.alerts
            sent = 0
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                for name in names:
                    if protocol.send_query(sock, name, "127.0.0.1", port,
                                           timeout=0.5, max_retries=1):
                        sent += 1
                    time.sleep(0.05)
            finally:
                sock.close()
            fired = self.detector.alerts - before
            self._queue.put({
                "type": "selftest_done",
                "ok": fired == 0,
                "message": (f"Normal DNS test: {sent}/{len(names)} names seen, "
                            f"{fired} alerts"
                            + (" - all passed" if fired == 0 else " - unexpected")),
            })

        threading.Thread(target=run, name="detector-normal", daemon=True).start()

    # -- graph + housekeeping ---------------------------------------------

    def _redraw(self) -> None:
        if self.observing and not self._receiver_running():
            self.observing = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._set_status("Receiver stopped - start it on the Receive tab", ok=False)
        elif not self.observing and self.status_var.get().startswith("Detached"):
            # Keep the detach message honest if the receiver starts or stops
            # from the Receive tab while the detector is not monitoring.
            text = ("Detached - the receiver is still listening"
                    if self._receiver_running() else "Detached - receiver stopped")
            if self.status_var.get() != text:
                self._set_status(text, ok=False)
        self._update_listener_label()

        canvas = self.canvas
        width = max(canvas.winfo_width(), 200)
        height = max(canvas.winfo_height(), 80)
        canvas.delete("all")

        left, top, bottom = 42, 10, height - 18
        plot_width = max(width - left - 12, 10)
        plot_height = max(bottom - top, 10)
        now = int(time.time())
        counts = [self._qps.get(now - offset, 0)
                  for offset in range(GRAPH_SECONDS - 1, -1, -1)]
        peak = max(1, max(counts))

        for fraction in (0.5, 1.0):
            y = bottom - plot_height * fraction
            canvas.create_line(left, y, width - 12, y, fill="#e2e2e2")
            canvas.create_text(left - 6, y, text=str(int(peak * fraction)),
                               anchor="e", fill="#666666",
                               font=("Segoe UI", 8))

        points: list[float] = []
        for index, count in enumerate(counts):
            x = left + plot_width * index / (GRAPH_SECONDS - 1)
            y = bottom - plot_height * (count / peak)
            points.extend((x, y))
        if len(points) >= 4:
            canvas.create_line(*points, fill="#1a7f37", width=2)

        canvas.create_line(left, bottom, width - 12, bottom, fill="#999999")
        canvas.create_text(left, height - 6, text=f"{GRAPH_SECONDS} s ago",
                           anchor="w", fill="#666666", font=("Segoe UI", 8))
        canvas.create_text(width - 12, height - 6, text="now", anchor="e",
                           fill="#666666", font=("Segoe UI", 8))
        if self.detector.queries:
            self._update_stats(sorted(self.detector._rule_fires))
        self.after(500, self._redraw)

    def apply_config(self, config: dict) -> None:
        self.cfg = dict(config)

    def shutdown(self) -> None:
        self.observing = False
