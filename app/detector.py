"""DNS tunnel detection: length, entropy and rate rules over live queries.

Two layers:

* `Detector` - pure logic, no sockets. Feed it (`qname`, `source`) and it
  returns the alerts that query fired, plus whether two or more distinct
  rules have fired inside the warning window.
* `Monitor` - a UDP listener for the GUI's Detector tab. It ACKs queries
  (so the lab encoder can finish) and forwards everything to the Detector.

It watches one socket you point it at. It is not a passive sniffer.
"""

from __future__ import annotations

import math
import socket
import threading
import time
from collections import deque
from typing import Callable

from . import protocol

LENGTH_LABEL_LIMIT = 40       # a single label longer than this is suspicious
LENGTH_QUERY_LIMIT = 60       # so is a whole name longer than this
ENTROPY_LIMIT = 4.5           # bits per character; Base32 lands near 4.9
RATE_COUNT = 20               # more than this many queries ...
RATE_WINDOW = 10.0            # ... in this many seconds, per source IP
WARNING_RULES = 2             # this many distinct rules ...
WARNING_WINDOW = 60.0         # ... inside this window means "tunnel"
ALERT_COOLDOWN = 2.0          # seconds between repeated alerts for one rule

RULE_LENGTH = "length"
RULE_ENTROPY = "entropy"
RULE_RATE = "rate"


def shannon_entropy(text: str) -> float:
    """Bits per character. 0.0 for empty or single-symbol strings."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    total = 0.0
    for count in counts.values():
        probability = count / length
        total -= probability * math.log2(probability)
    return total


def labels_of(qname: str) -> list[str]:
    return [label for label in qname.rstrip(".").split(".") if label]


def max_label_length(qname: str) -> int:
    labels = labels_of(qname)
    return max((len(label) for label in labels), default=0)


def max_label_entropy(qname: str) -> float:
    labels = labels_of(qname)
    return max((shannon_entropy(label) for label in labels), default=0.0)


def name_entropy(qname: str) -> float:
    """Highest of: the longest single label, and the labels joined.

    A 32-character Base32 chunk only reaches ~4.2-4.4 bits/char because the
    sample is short, so a single-label threshold of 4.5 almost never fires.
    Measuring the labels joined (the whole encoded name) restores the signal
    without lowering the threshold: tunnel names land near 4.5-4.8, ordinary
    names near 2.6-3.8. Both metrics still flag any long high-entropy label.
    """
    labels = labels_of(qname)
    if not labels:
        return 0.0
    return max(max_label_entropy(qname), shannon_entropy("".join(labels)))


class Detector:
    """Rule engine. `observe()` is the only entry point."""

    def __init__(
        self,
        *,
        length_label_limit: int = LENGTH_LABEL_LIMIT,
        length_query_limit: int = LENGTH_QUERY_LIMIT,
        entropy_limit: float = ENTROPY_LIMIT,
        rate_count: int = RATE_COUNT,
        rate_window: float = RATE_WINDOW,
        warning_rules: int = WARNING_RULES,
        warning_window: float = WARNING_WINDOW,
        alert_cooldown: float = ALERT_COOLDOWN,
    ) -> None:
        self.length_label_limit = length_label_limit
        self.length_query_limit = length_query_limit
        self.entropy_limit = entropy_limit
        self.rate_count = rate_count
        self.rate_window = rate_window
        self.warning_rules = warning_rules
        self.warning_window = warning_window
        self.alert_cooldown = alert_cooldown
        self._sources: dict[str, deque[tuple[float, str]]] = {}
        self._rule_fires: dict[str, deque[float]] = {}
        self._last_alert: dict[tuple[str, str], float] = {}
        self.queries = 0
        self.alerts = 0
        self.warnings = 0

    # -- rules -------------------------------------------------------------

    def _length_alert(self, qname: str) -> dict | None:
        label_len = max_label_length(qname)
        if label_len > self.length_label_limit:
            return {
                "rule": RULE_LENGTH,
                "reason": f"label {label_len} chars > {self.length_label_limit}",
            }
        if len(qname) > self.length_query_limit:
            return {
                "rule": RULE_LENGTH,
                "reason": f"query {len(qname)} chars > {self.length_query_limit}",
            }
        return None

    def _entropy_alert(self, qname: str) -> dict | None:
        entropy = name_entropy(qname)
        if entropy > self.entropy_limit:
            return {
                "rule": RULE_ENTROPY,
                "reason": f"name entropy {entropy:.2f} > {self.entropy_limit}",
            }
        return None

    def _rate_alert(self, qname: str, source: str, now: float) -> dict | None:
        bucket = self._sources.setdefault(source, deque())
        bucket.append((now, qname))
        cutoff = now - self.rate_window
        while bucket and bucket[0][0] < cutoff:
            bucket.popleft()
        if len(bucket) > self.rate_count:
            unique = len({name for _, name in bucket})
            if unique > self.rate_count:
                return {
                    "rule": RULE_RATE,
                    "reason": (f"{len(bucket)} queries / {unique} unique names "
                               f"in {self.rate_window:.0f}s from {source}"),
                }
        return None

    # -- main entry --------------------------------------------------------

    def observe(self, qname: str, source: str = "?", now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        self.queries += 1

        found: list[dict] = []
        for alert in (
            self._length_alert(qname),
            self._entropy_alert(qname),
            self._rate_alert(qname, source, now),
        ):
            if alert:
                found.append(alert)

        emitted = []
        for alert in found:
            key = (alert["rule"], source)
            last = self._last_alert.get(key)
            if last is None or now - last >= self.alert_cooldown:
                self._last_alert[key] = now
                emitted.append(alert)
            self._rule_fires.setdefault(alert["rule"], deque()).append(now)

        window_start = now - self.warning_window
        for rule, fires in list(self._rule_fires.items()):
            while fires and fires[0] < window_start:
                fires.popleft()
            if not fires:
                del self._rule_fires[rule]
        warning = len(self._rule_fires) >= self.warning_rules
        if warning and emitted:
            self.warnings += 1

        self.alerts += len(emitted)
        return {
            "qname": qname,
            "source": source,
            "time": time.strftime("%H:%M:%S"),
            "alerts": emitted,
            "warning": warning,
            "rules_in_window": sorted(self._rule_fires),
        }

    def reset(self) -> None:
        self._sources.clear()
        self._rule_fires.clear()
        self._last_alert.clear()
        self.queries = self.alerts = self.warnings = 0


class Monitor:
    """UDP listener feeding a Detector. Binds in `start()` so errors surface."""

    def __init__(
        self,
        detector: Detector | None = None,
        host: str = "0.0.0.0",
        port: int = 53,
        *,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.detector = detector or Detector()
        self.host = host
        self.port = int(port)
        self.on_event = on_event
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        bind_addr = ((self.host, self.port, 0, 0) if family == socket.AF_INET6
                     else (self.host, self.port))
        try:
            sock.bind(bind_addr)
        except OSError:
            sock.close()
            raise
        sock.settimeout(0.2)
        self._sock = sock
        self.port = sock.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dnstunnel-detector",
                                        daemon=True)
        self._thread.start()
        self._emit({"type": "listening", "host": self.host, "port": self.port})

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._emit({"type": "stopped"})

    def _emit(self, event: dict) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _run(self) -> None:
        sock = self._sock
        assert sock is not None
        while not self._stop.is_set():
            try:
                packet, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError as exc:
                if self._stop.is_set():
                    break
                self._emit({"type": "error", "message": f"socket: {exc}"})
                break
            try:
                qid, qname, question = protocol.parse_dns_query(packet)
            except protocol.ProtocolError as exc:
                self._emit({"type": "ignored", "reason": str(exc)})
                continue
            try:
                sock.sendto(protocol.build_dns_response(qid, question), addr)
            except OSError:
                pass
            result = self.detector.observe(qname, addr[0])
            self._emit({
                "type": "query",
                "qname": qname,
                "source": addr[0],
                **{k: result[k] for k in ("time", "alerts", "warning", "rules_in_window")},
            })
