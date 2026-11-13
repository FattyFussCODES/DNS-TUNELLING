"""DNS tunnel wire protocol: hand-built packets, chunking, ACKs, rebuild.

No GUI and no CLI parsing in here. Two consumers drive this module:

* `send_file()` emits structured dict events through `on_event` while it
  streams a file out as DNS questions, and returns a result dict.
* `Receiver` binds a UDP socket, answers every question (that is the ACK),
  files chunks by sequence number, and rebuilds the file on END.

Stream layout, unchanged from the original scripts plus two optional layers:

    <header JSON>\\n<processed bytes>

`processed bytes` is the original file after compress (zlib, >1 KB only)
then encrypt (Fernet + PBKDF2 key, only when a password is set). The header
records both flags plus the size and SHA256 of the *original* file, so the
receiver verifies the plaintext end to end.

Everything is Base32 (lowercase, padding stripped), cut into 32-character
chunks. 32 Base32 chars carry exactly 20 bytes.
"""

from __future__ import annotations

import base64
import json
import os
import random
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Callable

from .compress import compress_bytes, decompress_bytes, should_compress
from .crypto import DecryptionError, decrypt_bytes, encrypt_bytes
from .utils import sha256_bytes, unique_path

DOMAIN = "dnstunnel.cc.cd"
CHUNK_SIZE = 32
CHUNK_PAYLOAD_BYTES = CHUNK_SIZE * 5 // 8  # 20 bytes per chunk
TIMEOUT = 2.0
MAX_RETRIES = 3
DEFAULT_DELAY = 0.2
ACK_IP = "1.1.1.1"

EventHook = Callable[[dict], None]


class ProtocolError(Exception):
    """A stream that cannot be decoded."""


def new_session() -> str:
    return f"{random.randint(0, 999999):06d}"


# --------------------------------------------------------------------------
# Stream building
# --------------------------------------------------------------------------

def _base32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=").lower()


def _encode_stream(header: dict, payload: bytes) -> str:
    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return _base32(blob + b"\n" + payload)


def chunk_count(stream: str) -> int:
    return -(-len(stream) // CHUNK_SIZE)


def build_stream(
    file_bytes: bytes,
    filename: str,
    *,
    password: str | None = None,
    compress: bool = True,
    session: str | None = None,
) -> tuple[str, dict]:
    """Return (base32 stream, header). Header carries the true chunk count.

    "chunks" sits inside the header, and the header length feeds the chunk
    count, so the count is settled by iterating until it is stable. Each
    iteration can only grow the encoded stream, so this converges.
    """
    session = session or new_session()
    original = file_bytes
    payload = original
    compressed = False
    if compress and should_compress(payload):
        payload = compress_bytes(payload)
        compressed = True
    encrypted = False
    if password:
        payload = encrypt_bytes(payload, password)
        encrypted = True

    header = {
        "filename": filename,
        "size": len(original),
        "sha256": sha256_bytes(original),
        "compressed": compressed,
        "encrypted": encrypted,
        "chunks": 0,
        "session": session,
    }
    stream = _encode_stream(header, payload)
    for _ in range(8):
        count = chunk_count(stream)
        if header["chunks"] == count:
            break
        header["chunks"] = count
        stream = _encode_stream(header, payload)
    return stream, header


def chunk_stream(stream: str) -> list[str]:
    return [stream[i:i + CHUNK_SIZE] for i in range(0, len(stream), CHUNK_SIZE)]


# --------------------------------------------------------------------------
# DNS packet handling (hand-built, no DNS library)
# --------------------------------------------------------------------------

def build_dns_query(qname: str, qid: int) -> bytes:
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = b""
    for label in qname.split("."):
        encoded = label.encode("ascii")
        if not encoded:
            raise ProtocolError(f"empty label in {qname!r}")
        if len(encoded) > 63:
            raise ProtocolError(f"label too long ({len(encoded)} > 63): {label!r}")
        question += struct.pack("B", len(encoded)) + encoded
    question += b"\x00" + struct.pack(">HH", 1, 1)  # QTYPE A, QCLASS IN
    if len(qname) > 253:
        raise ProtocolError("name exceeds the 253-character DNS limit")
    return header + question


def parse_dns_query(packet: bytes) -> tuple[int, str, bytes]:
    """Return (qid, qname, raw question section). Raises ProtocolError."""
    if len(packet) < 12:
        raise ProtocolError("packet shorter than a DNS header")
    qid, _flags, qdcount, _an, _ns, _ar = struct.unpack(">HHHHHH", packet[:12])
    if qdcount != 1:
        raise ProtocolError("expected exactly one question")
    labels: list[str] = []
    pos = 12
    while True:
        if pos >= len(packet):
            raise ProtocolError("truncated QNAME")
        length = packet[pos]
        if length == 0:
            pos += 1
            break
        if pos + 1 + length > len(packet):
            raise ProtocolError("truncated label")
        labels.append(packet[pos + 1:pos + 1 + length].decode("ascii", "replace"))
        pos += 1 + length
    end = pos + 4
    if end > len(packet):
        raise ProtocolError("truncated question")
    return qid, ".".join(labels), packet[12:end]


def build_dns_response(qid: int, question: bytes) -> bytes:
    header = struct.pack(">HHHHHH", qid, 0x8180, 1, 1, 0, 0)
    answer = struct.pack(">HHHIH", 0xC00C, 1, 1, 60, 4) + socket.inet_aton(ACK_IP)
    return header + question + answer


def parse_qname(qname: str, domain: str = DOMAIN) -> tuple[str, str | None, str] | None:
    """Split a tunnel name into (seq, chunk, session), or None if foreign.

    END.<session>.<domain> becomes ("END", None, "<session>").
    """
    labels = qname.rstrip(".").split(".")
    domain_labels = domain.lower().split(".")
    if len(labels) <= len(domain_labels):
        return None
    if [label.lower() for label in labels[-len(domain_labels):]] != domain_labels:
        return None
    body = labels[:-len(domain_labels)]
    if not body:
        return None
    if body[0].upper() == "END":
        return ("END", None, body[1] if len(body) > 1 else "")
    if len(body) < 3:
        return None
    return (body[0], body[1], body[2])


def _seq_key(seq: str) -> int | str:
    try:
        return int(seq)
    except ValueError:
        return seq


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------

def _emit(hook: EventHook | None, event: dict) -> None:
    if hook is not None:
        hook(event)


def send_query(
    sock: socket.socket,
    qname: str,
    server: str,
    port: int,
    *,
    timeout: float = TIMEOUT,
    max_retries: int = MAX_RETRIES,
    on_retry: Callable[[int], None] | None = None,
) -> bool:
    """Send one question, wait for a reply with the same QID. True on ACK."""
    qid = random.randint(0, 65535)
    packet = build_dns_query(qname, qid)
    dest = (server, port, 0, 0) if sock.family == socket.AF_INET6 else (server, port)
    for attempt in range(1, max_retries + 1):
        try:
            sock.sendto(packet, dest)
            sock.settimeout(timeout)
            resp, _ = sock.recvfrom(512)
            if len(resp) >= 2 and struct.unpack(">H", resp[:2])[0] == qid:
                return True
        except socket.timeout:
            if on_retry is not None and attempt < max_retries:
                on_retry(attempt + 1)
            continue
        except OSError:
            return False
    return False


def send_file(
    path: str | Path,
    server: str,
    port: int,
    *,
    delay: float = DEFAULT_DELAY,
    password: str | None = None,
    compress: bool = True,
    timeout: float = TIMEOUT,
    max_retries: int = MAX_RETRIES,
    domain: str = DOMAIN,
    cancel: threading.Event | None = None,
    on_event: EventHook | None = None,
) -> dict:
    """Stream a file out as DNS queries. Blocking; run it in a thread."""
    source = Path(path)
    data = source.read_bytes()
    session = new_session()
    stream, header = build_stream(
        data, source.name, password=password, compress=compress, session=session
    )
    chunks = chunk_stream(stream)
    total = len(chunks)

    _emit(on_event, {
        "type": "start",
        "filename": source.name,
        "size": header["size"],
        "sha256": header["sha256"],
        "chunks": total,
        "session": session,
        "compressed": header["compressed"],
        "encrypted": header["encrypted"],
        "server": server,
        "port": port,
    })

    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    started = time.monotonic()
    sent = 0
    try:
        for seq, chunk in enumerate(chunks, start=1):
            if cancel is not None and cancel.is_set():
                return _cancelled(on_event, sent, total, session, header, started)
            qname = f"{seq:03d}.{chunk}.{session}.{domain}"
            acked = send_query(
                sock, qname, server, port,
                timeout=timeout, max_retries=max_retries,
                on_retry=lambda attempt, s=seq: _emit(on_event, {
                    "type": "retry", "seq": s, "total": total, "attempt": attempt,
                }),
            )
            if not acked:
                message = (
                    f"Chunk {seq:03d} got no ACK after {max_retries} tries; stopped."
                )
                _emit(on_event, {
                    "type": "chunk_failed", "seq": seq, "total": total,
                    "attempts": max_retries,
                })
                _emit(on_event, {"type": "error", "message": message, "session": session})
                return {
                    "ok": False, "cancelled": False, "sent": sent, "total": total,
                    "session": session, "header": header, "error": message,
                    "elapsed": time.monotonic() - started,
                }
            sent += 1
            _emit(on_event, {
                "type": "chunk", "seq": seq, "total": total,
                "session": session, "acked": True, "qname": qname,
            })
            if delay:
                if cancel is not None:
                    if cancel.wait(delay):
                        return _cancelled(on_event, sent, total, session, header, started)
                else:
                    time.sleep(delay)

        end_acked = send_query(
            sock, f"END.{session}.{domain}", server, port,
            timeout=timeout, max_retries=max_retries,
        )
        _emit(on_event, {"type": "end", "acked": end_acked, "session": session})
        elapsed = time.monotonic() - started
        result = {
            "ok": True, "cancelled": False, "sent": sent, "total": total,
            "session": session, "header": header, "elapsed": elapsed,
            "end_acked": end_acked, "server": server, "port": port,
        }
        _emit(on_event, {"type": "done", **result})
        return result
    finally:
        sock.close()


def _cancelled(
    on_event: EventHook | None,
    sent: int,
    total: int,
    session: str,
    header: dict,
    started: float,
) -> dict:
    _emit(on_event, {
        "type": "cancelled", "sent": sent, "total": total, "session": session,
    })
    return {
        "ok": False, "cancelled": True, "sent": sent, "total": total,
        "session": session, "header": header,
        "elapsed": time.monotonic() - started,
    }


# --------------------------------------------------------------------------
# Receiving
# --------------------------------------------------------------------------

class Receiver:
    """UDP listener that ACKs tunnel questions and rebuilds files on END.

    `start()` binds the socket synchronously, so a busy port or a missing
    privilege raises right away instead of dying inside the thread. Events
    are delivered on the listener thread through `on_event`.

    `on_query(qname, source)` is a passive tap for the detector: it fires for
    every DNS question that parses, including names this receiver ignores
    (ordinary DNS). The receiver owns the only socket; consumers share it.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 53,
        *,
        out_dir: str | Path = "received",
        prefix: str = "",
        password: str | None = None,
        domain: str = DOMAIN,
        on_event: EventHook | None = None,
        on_query: Callable[[str, str], None] | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.out_dir = Path(out_dir)
        self.prefix = prefix
        self.password = password
        self.domain = domain
        self.on_event = on_event
        self.on_query = on_query
        self.stats = {"queries": 0, "chunks": 0, "ignored": 0, "sessions": 0}
        self._sessions: dict[str, dict[int | str, str]] = {}
        self._started_at: dict[str, float] = {}
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        bind_addr = (
            (self.host, self.port, 0, 0) if family == socket.AF_INET6
            else (self.host, self.port)
        )
        try:
            sock.bind(bind_addr)
        except OSError:
            sock.close()
            raise
        sock.settimeout(0.2)
        self._sock = sock
        self.port = sock.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="dnstunnel-receiver", daemon=True
        )
        self._thread.start()
        _emit(self.on_event, {
            "type": "listening", "host": self.host, "port": self.port,
            "domain": self.domain,
        })

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        _emit(self.on_event, {"type": "stopped"})

    # -- listener ----------------------------------------------------------

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
                _emit(self.on_event, {"type": "error", "message": f"socket: {exc}"})
                break
            try:
                qid, qname, question = parse_dns_query(packet)
            except ProtocolError as exc:
                self.stats["ignored"] += 1
                _emit(self.on_event, {"type": "ignored", "reason": str(exc)})
                continue
            # Answer even foreign names: it is harmless, and the encoder's
            # ACK check is just "reply with my QID".
            try:
                sock.sendto(build_dns_response(qid, question), addr)
            except OSError:
                pass
            self.stats["queries"] += 1

            if self.on_query is not None:
                try:
                    self.on_query(qname, addr[0])
                except Exception:
                    # A tap must never kill the listener.
                    pass

            parsed = parse_qname(qname, self.domain)
            if parsed is None:
                self.stats["ignored"] += 1
                if self.stats["ignored"] <= 5 or self.stats["ignored"] % 500 == 0:
                    _emit(self.on_event, {
                        "type": "foreign", "qname": qname, "ignored": self.stats["ignored"],
                    })
                continue
            self._handle_tunnel_query(parsed, addr, qname)

    def _handle_tunnel_query(
        self, parsed: tuple[str, str | None, str], addr, qname: str
    ) -> None:
        seq, chunk, session = parsed
        if seq == "END":
            if not self._sessions.get(session):
                _emit(self.on_event, {
                    "type": "end_empty", "session": session,
                    "message": f"Session {session}: END with no chunks",
                })
                return
            try:
                self._finish(session)
            except (ProtocolError, DecryptionError, ValueError) as exc:
                self._sessions.pop(session, None)
                self._started_at.pop(session, None)
                _emit(self.on_event, {
                    "type": "error", "session": session, "message": str(exc),
                })
            return

        if chunk is None:
            return
        store = self._sessions.setdefault(session, {})
        key = _seq_key(seq)
        if key in store:
            _emit(self.on_event, {
                "type": "duplicate", "session": session, "seq": key,
                "count": len(store),
            })
            return
        store[key] = chunk
        self.stats["chunks"] += 1
        self._started_at.setdefault(session, time.monotonic())
        _emit(self.on_event, {
            "type": "chunk", "session": session, "seq": key, "length": len(chunk),
            "count": len(store), "addr": f"{addr[0]}:{addr[1]}", "qname": qname,
            "time": time.strftime("%H:%M:%S"),
        })

    def _finish(self, session: str) -> None:
        store = self._sessions.pop(session, None)
        if not store:
            raise ProtocolError(f"session {session} has no chunks")
        encoded = "".join(store[key] for key in sorted(store))
        encoded += "=" * (-len(encoded) % 8)
        try:
            raw = base64.b32decode(encoded.upper())
        except Exception as exc:  # binascii.Error and friends
            raise ProtocolError(f"Base32 decode failed: {exc}") from exc

        header_json, sep, payload = raw.partition(b"\n")
        if not sep:
            raise ProtocolError("stream has no header separator")
        try:
            header = json.loads(header_json)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"bad header JSON: {exc}") from exc
        if not isinstance(header, dict) or "filename" not in header:
            raise ProtocolError("header is missing filename")

        if header.get("encrypted"):
            if not self.password:
                raise ProtocolError(
                    "stream is encrypted: enter the password before starting "
                    "the receiver, then resend"
                )
            payload = decrypt_bytes(payload, self.password)
        if header.get("compressed"):
            payload = decompress_bytes(payload)

        expected_size = header.get("size")
        expected_sha = header.get("sha256")
        size_ok = isinstance(expected_size, int) and len(payload) == expected_size
        sha_ok = sha256_bytes(payload) == expected_sha

        filename = os.path.basename(str(header["filename"])) or "recovered.bin"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(self.out_dir, filename, self.prefix)
        target.write_bytes(payload)

        elapsed = time.monotonic() - self._started_at.pop(session, time.monotonic())
        result = {
            "type": "complete",
            "session": session,
            "filename": filename,
            "path": str(target),
            "size": len(payload),
            "expected_size": expected_size,
            "sha256": sha256_bytes(payload),
            "expected_sha256": expected_sha,
            "size_match": bool(size_ok),
            "sha256_match": bool(sha_ok),
            "chunks": len(store),
            "expected_chunks": header.get("chunks"),
            "compressed": bool(header.get("compressed")),
            "encrypted": bool(header.get("encrypted")),
            "elapsed": elapsed,
        }
        self.stats["sessions"] += 1
        _emit(self.on_event, result)


# --------------------------------------------------------------------------
# Debug helper
# --------------------------------------------------------------------------

def stream_info(stream: str, header: dict) -> str:
    """One-line human summary, used by the CLI and the GUI preview."""
    layers = []
    if header.get("compressed"):
        layers.append("zlib")
    if header.get("encrypted"):
        layers.append("fernet" if _using_fernet() else "xor+hmac")
    return (
        f"{header['chunks']} chunks, {len(stream)} base32 chars, "
        f"{header['size']} B original"
        + (f", layers: {' + '.join(layers)}" if layers else ", layers: none")
    )


def _using_fernet() -> bool:
    from . import crypto

    return crypto.HAVE_CRYPTOGRAPHY
