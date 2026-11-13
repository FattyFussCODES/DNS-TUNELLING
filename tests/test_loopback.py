"""End-to-end loopback: 127.0.0.1, real UDP, real ACKs, real rebuild."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from app import protocol

TIMEOUT = 1.0
WAIT = 20.0


def _pick_port() -> int:
    """Prefer 5353 (the documented lab port); fall back to an ephemeral one."""
    for port in (5353, 0):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("127.0.0.1", port))
            return sock.getsockname()[1]
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError("no free UDP port")


def _wait_for(events: list[dict], kind: str, timeout: float = WAIT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for event in events:
            if event.get("type") == kind:
                return event
        time.sleep(0.02)
    raise AssertionError(f"no {kind!r} event; got {[e.get('type') for e in events]}")


def _send_via_loopback(
    tmp_path: Path,
    data: bytes,
    filename: str = "secret.txt",
    *,
    password: str | None = None,
    receiver_password: str | None = None,
    compress: bool = True,
    chunk_size: int = protocol.CHUNK_SIZE,
) -> tuple[dict, list[dict], Path, Path]:
    port = _pick_port()
    out_dir = tmp_path / "received"
    events: list[dict] = []
    receiver = protocol.Receiver(
        "127.0.0.1", port,
        out_dir=out_dir,
        password=receiver_password if receiver_password is not None else password,
        on_event=events.append,
    )
    receiver.start()
    source = tmp_path / filename
    source.write_bytes(data)
    try:
        result = protocol.send_file(
            source, "127.0.0.1", port,
            delay=0.0,
            password=password,
            compress=compress,
            timeout=TIMEOUT,
            chunk_size=chunk_size,
            on_event=events.append,
        )
        complete = _wait_for(events, "complete")
    finally:
        receiver.stop()
    assert result["ok"], f"send failed: {result}"
    return complete, events, source, out_dir


def test_loopback_small_file_is_byte_identical(tmp_path):
    data = b"Meet at 5\n"
    complete, events, source, _ = _send_via_loopback(tmp_path, data)

    assert complete["size_match"] is True
    assert complete["sha256_match"] is True
    assert complete["size"] == len(data)
    assert complete["filename"] == "secret.txt"
    assert Path(complete["path"]).read_bytes() == data
    assert complete["path"].endswith("secret.txt")
    assert complete["encrypted"] is False and complete["compressed"] is False


def test_loopback_25_chunks_in_three_windows(tmp_path):
    filename = "window.bin"
    data = next(
        b"x" * size for size in range(1000)
        if protocol.build_stream(b"x" * size, filename, compress=False)[1]["chunks"] == 25
    )
    complete, events, _, _ = _send_via_loopback(
        tmp_path, data, filename, compress=False,
    )
    received = [event["seq"] for event in events
                if event["type"] == "chunk" and "length" in event]
    assert received == list(range(1, 26))
    assert [event["acked"] for event in events if event["type"] == "window"] == [10, 20, 25]
    assert complete["size_match"] is True
    assert complete["sha256_match"] is True
    assert Path(complete["path"]).read_bytes() == data


def test_loopback_maximum_chunk_size(tmp_path):
    data = os.urandom(2048)
    complete, events, _, _ = _send_via_loopback(
        tmp_path, data, compress=False, chunk_size=63,
    )
    assert Path(complete["path"]).read_bytes() == data
    assert complete["chunks"] == complete["expected_chunks"]
    received = [event for event in events if event["type"] == "chunk" and "length" in event]
    assert len(received) == complete["chunks"]
    assert all(event["length"] == 63 for event in received[:-1])
    assert 0 < received[-1]["length"] <= 63


def test_loopback_compressed_and_encrypted_roundtrip(tmp_path):
    data = b"DNS tunnelling lab test line\n" * 400  # 11.2 KB, compresses hard
    complete, _, _, _ = _send_via_loopback(tmp_path, data, "notes.txt", password="lab-password")

    assert complete["encrypted"] is True
    assert complete["compressed"] is True
    assert complete["size_match"] is True
    assert complete["sha256_match"] is True
    assert Path(complete["path"]).read_bytes() == data
    # Compression must actually have shrunk the wire stream.
    assert complete["chunks"] < len(data) // protocol.CHUNK_PAYLOAD_BYTES


def test_loopback_crosses_the_999_chunk_boundary(tmp_path):
    """30 KB of random bytes needs >999 chunks: the numeric-sort regression."""
    data = os.urandom(30_000)
    complete, _, _, _ = _send_via_loopback(tmp_path, data, "big.bin", compress=False)

    assert complete["chunks"] > 999
    assert complete["size_match"] is True
    assert complete["sha256_match"] is True
    assert Path(complete["path"]).read_bytes() == data


def test_loopback_wrong_password_is_reported(tmp_path):
    port = _pick_port()
    out_dir = tmp_path / "received"
    events: list[dict] = []
    receiver = protocol.Receiver("127.0.0.1", port, out_dir=out_dir,
                                 password="wrong-one", on_event=events.append)
    receiver.start()
    source = tmp_path / "secret.txt"
    source.write_bytes(b"Meet at 5\n")
    try:
        protocol.send_file(source, "127.0.0.1", port, delay=0.0,
                           password="right-one", timeout=TIMEOUT,
                           on_event=events.append)
        error = _wait_for(events, "error")
    finally:
        receiver.stop()

    assert "wrong password" in error["message"].lower() or "corrupt" in error["message"].lower()
    assert not any(event.get("type") == "complete" for event in events)
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_loopback_second_file_does_not_overwrite(tmp_path):
    port = _pick_port()
    out_dir = tmp_path / "received"
    events: list[dict] = []
    receiver = protocol.Receiver("127.0.0.1", port, out_dir=out_dir, on_event=events.append)
    receiver.start()
    source = tmp_path / "secret.txt"
    try:
        paths = []
        for payload in (b"first\n", b"second\n"):
            source.write_bytes(payload)
            protocol.send_file(source, "127.0.0.1", port, delay=0.0,
                               compress=False, timeout=TIMEOUT, on_event=events.append)
            deadline = time.time() + WAIT
            while time.time() < deadline:
                done = [e for e in events if e.get("type") == "complete"]
                if len(done) > len(paths):
                    paths.append(done[-1]["path"])
                    break
                time.sleep(0.02)
            else:
                raise AssertionError(f"no complete event: {[e.get('type') for e in events]}")
    finally:
        receiver.stop()

    assert paths[0].endswith("secret.txt")
    assert paths[1].endswith("secret (1).txt")
    assert Path(paths[0]).read_bytes() == b"first\n"
    assert Path(paths[1]).read_bytes() == b"second\n"
