#!/usr/bin/env python3
"""
Decoder - DNS tunnelling receiver (lab / own-machine testing only)

Thin CLI wrapper around app.protocol.Receiver.

Usage:
    sudo python3 decoder.py --host 0.0.0.0 --port 53
    python decoder.py --host 127.0.0.1 --port 5353 --out-dir received

Listens for DNS queries ending in dnstunnel.cc.cd, stores the Base32 chunks
by sequence number, and on the END query rebuilds the file, checking size
and SHA256. Files land as recovered_<filename> (or in --out-dir).

Run this only on a server you own.
"""

from __future__ import annotations

import argparse
import sys
import time

from app import config, protocol


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decode DNS-tunnelled data")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT,
                        help="UDP port, 53 needs Admin/sudo (default: %(default)s)")
    parser.add_argument("--out-dir", default=".",
                        help="where rebuilt files go (default: current folder)")
    parser.add_argument("--prefix", default="recovered_",
                        help="filename prefix (default: %(default)s)")
    parser.add_argument("--password", default=None,
                        help="decrypt streams sent with this password")
    parser.add_argument("--domain", default=protocol.DOMAIN,
                        help="tunnel suffix (default: %(default)s)")
    args = parser.parse_args(argv)

    def on_event(event: dict) -> None:
        kind = event["type"]
        if kind == "chunk":
            print(f"Session {event['session']}: chunk {event['seq']:>3} "
                  f"({event['count']} stored)", flush=True)
        elif kind == "duplicate":
            print(f"Session {event['session']}: chunk {event['seq']:>3} duplicate "
                  f"({event['count']} stored)", flush=True)
        elif kind == "complete":
            print(f"Session {event['session']}: rebuilt {event['path']}")
            print(f"  size: {event['size']} / {event['expected_size']}")
            print(f"  size match: {event['size_match']}")
            print(f"  sha256: {event['sha256'][:16]}...")
            print(f"  sha256 match: {event['sha256_match']}")
            print(f"  time: {event['elapsed']:.2f}s")
            diff = "fc" if sys.platform.startswith("win") else "diff"
            print(f"  Check with: {diff} {event['filename']} {event['path']}", flush=True)
        elif kind == "end_empty":
            print(event["message"])
        elif kind == "error":
            print(f"Error: {event['message']}")
        elif kind == "foreign":
            print(f"Ignoring foreign query ({event['ignored']} so far): "
                  f"{event['qname'][:80]}")
        elif kind == "ignored":
            print(f"Ignoring bad packet: {event['reason']}")

    receiver = protocol.Receiver(
        args.host,
        args.port,
        out_dir=args.out_dir,
        prefix=args.prefix,
        password=args.password,
        domain=args.domain,
        on_event=on_event,
    )
    try:
        receiver.start()
    except PermissionError:
        if args.port < 1024:
            print(f"Port {args.port} needs sudo/Admin (ports under 1024).")
        else:
            print(f"Port {args.port} refused: it is already in use by another "
                  "process (Windows reports that as permission denied). "
                  "Pick a free port with --port.")
        return 1
    except OSError as exc:
        print(f"Cannot listen on {args.host}:{args.port}: {exc}")
        return 1

    print(f"Decoder listening on {args.host}:{args.port} for *.{args.domain}")
    print("Waiting for chunks... (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        receiver.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
