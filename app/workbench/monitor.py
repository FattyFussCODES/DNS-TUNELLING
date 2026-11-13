"""Explicit, metadata-only UDP observation listener.

The listener binds only when the user starts monitoring. It accepts ordinary
DNS query packets (never response packets), feeds them to the existing detector
with monotonic timestamps, and persists metadata with UTC timestamps. It never
sends a DNS reply, forwards a packet, or reconstructs a file.

The socket deliberately does not set ``SO_REUSEADDR``: a bind conflict is a
real conflict and is reported through ``monitor.error`` instead of being hidden
by a fallback port or a second silent listener.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import threading
import time
from typing import Any

from ..detector import (
    Detector,
    ENTROPY_LIMIT,
    LENGTH_LABEL_LIMIT,
    LENGTH_QUERY_LIMIT,
    RATE_COUNT,
    RATE_WINDOW,
    name_entropy,
)
from ..protocol import ProtocolError, parse_dns_query
from .store import Store, utc_now_ms

COVERAGE_NOTE = (
    "Observes only DNS queries intentionally delivered to the configured local "
    "UDP endpoint. No packet capture, DNS replies, forwarding, scanning or file "
    "reconstruction. Metrics cover this observation window, not network-wide "
    "traffic."
)

COOLDOWN_NOTE = (
    "The detector applies a 2-second per-rule, per-source alert cooldown. A "
    "suspicious query can therefore be stored without alert evidence, so flag "
    "counts are lower bounds and the detection rate is a heuristic flag rate, "
    "not detection accuracy. Anomalies count distinct observed queries with at "
    "least one recorded rule alert."
)

RULE_INFO: list[dict[str, str]] = [
    {
        "id": "length",
        "title": "Length threshold",
        "description": (
            "Flags a single label over "
            f"{LENGTH_LABEL_LIMIT} characters or a full query name over "
            f"{LENGTH_QUERY_LIMIT} characters."
        ),
    },
    {
        "id": "entropy",
        "title": "Entropy threshold",
        "description": (
            "Flags a measured name entropy above "
            f"{ENTROPY_LIMIT:.1f} bits per character."
        ),
    },
    {
        "id": "rate",
        "title": "Rate threshold",
        "description": (
            f"Flags more than {RATE_COUNT} queries with more than "
            f"{RATE_COUNT} unique names in {RATE_WINDOW:.0f} seconds from one "
            "source."
        ),
    },
]


class Monitor:
    """Owns at most one UDP observation socket and one monitor thread."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._session_id: int | None = None
        self._host = ""
        self._port = 0
        self._error: str | None = None
        self._detector: Detector | None = None
        self._received = 0
        self._malformed = 0

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def state(self, configured_host: str, configured_port: int) -> dict[str, Any]:
        """Current monitor state, using configured values while stopped."""
        with self._lock:
            running = self.running
            return {
                "running": running,
                "host": self._host if running else configured_host,
                "port": self._port if running else int(configured_port),
                "error": self._error,
            }

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._error = message

    # -- lifecycle ---------------------------------------------------------

    def start(self, host: str, port: int) -> None:
        """Bind the configured endpoint and begin observing.

        Bind and store failures are retained in ``state()['error']``; they are
        never replaced by a fallback endpoint.
        """
        with self._lock:
            if self.running:
                return
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None
                self._finish_session()
            self._error = None

            address = ipaddress.ip_address(host)
            family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_DGRAM)
            bind_address = (host, int(port), 0, 0) if family == socket.AF_INET6 else (
                host,
                int(port),
            )
            try:
                sock.bind(bind_address)
            except OSError as exc:
                sock.close()
                self._error = f"cannot bind UDP {host}:{int(port)}: {exc}"
                return

            try:
                sock.settimeout(0.2)
                actual_port = int(sock.getsockname()[1])
                session_id = self._store.start_session(host, actual_port)
            except Exception as exc:
                sock.close()
                self._error = f"cannot start observation session: {exc}"
                return

            self._sock = sock
            self._session_id = session_id
            self._host = host
            self._port = actual_port
            self._detector = Detector()
            self._received = 0
            self._malformed = 0
            self._stop.clear()
            thread = threading.Thread(
                target=self._run,
                args=(sock, self._detector),
                name="dnsmuggle-workbench-monitor",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        """Stop the listener, join its thread and close the session."""
        thread = self._thread
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)
            if thread.is_alive():
                thread.join(timeout=1.0)
        with self._lock:
            self._thread = None
            self._sock = None
            self._detector = None
        self._finish_session()

    def _finish_session(self) -> None:
        with self._lock:
            session_id = self._session_id
            self._session_id = None
        if session_id is not None:
            try:
                self._store.stop_session(session_id)
            except Exception as exc:
                self._set_error(f"cannot close observation session: {exc}")

    # -- listener ----------------------------------------------------------

    def _run(self, sock: socket.socket, detector: Detector) -> None:
        try:
            while not self._stop.is_set():
                try:
                    packet, address = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self._stop.is_set():
                        self._set_error(f"observation socket error: {exc}")
                    break
                if not self._handle(packet, address, detector):
                    break
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._finish_session()

    def _handle(
        self,
        packet: bytes,
        address: tuple[Any, ...],
        detector: Detector,
    ) -> bool:
        """Record one packet. Return False only on a fatal storage failure."""
        if len(packet) < 12:
            self._malformed += 1
            return True
        flags = struct.unpack(">H", packet[2:4])[0]
        # QR=1 is a response; a non-zero opcode is not a standard query.
        if flags & 0x8000 or ((flags >> 11) & 0x0F) != 0:
            self._malformed += 1
            return True
        try:
            _qid, qname, _question = parse_dns_query(packet)
        except (ProtocolError, ValueError, struct.error):
            self._malformed += 1
            return True
        except Exception:
            self._malformed += 1
            return True

        source = str(address[0])
        monotonic_now = time.monotonic()
        observed_ms = utc_now_ms()
        try:
            result = detector.observe(qname, source, now=monotonic_now)
        except Exception as exc:
            self._set_error(f"detector failed: {exc}")
            return False

        self._received += 1
        try:
            self._store.add_observation(
                observed_ms=observed_ms,
                qname=qname,
                source=source,
                entropy=name_entropy(qname),
                length=len(qname),
                alerts=result["alerts"],
                warning=bool(result["warning"]),
                session_id=self._session_id,
            )
        except Exception as exc:
            self._set_error(f"cannot store observation: {exc}")
            return False
        return True