#!/usr/bin/env python3
"""
Decoder - DNS tunnelling receiver (lab / own-machine testing only)

Usage:
    sudo python3 decoder.py --host 0.0.0.0 --port 53
    python3 decoder.py --host 127.0.0.1 --port 5353

Listens for DNS queries ending in dnstunnel.cc.cd, stores the
Base32 chunks by sequence number, and on the END query rebuilds
the file as recovered_<filename>, checking size + SHA256.

Run this only on a server you own. Never use it to collect data
from someone else's machine or network.
"""

import argparse
import base64
import hashlib
import json
import socket
import struct

DOMAIN = "dnstunnel.cc.cd"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 53


def parse_dns_query(packet):
    qid, _flags, qdcount, _, _, _ = struct.unpack(">HHHHHH", packet[:12])
    if qdcount != 1:
        raise ValueError("expected exactly one question")
    labels, pos = [], 12
    while packet[pos] != 0:
        length = packet[pos]
        labels.append(packet[pos + 1:pos + 1 + length].decode())
        pos += 1 + length
    pos += 1
    question = packet[12:pos + 4]
    return qid, ".".join(labels), question


def build_dns_response(qid, question):
    header = struct.pack(">HHHHHH", qid, 0x8180, 1, 1, 0, 0)
    answer = struct.pack(">HHHIH", 0xC00C, 1, 1, 60, 4) + bytes([127, 0, 0, 1])
    return header + question + answer


def parse_qname(qname):
    labels = qname.rstrip(".").split(".")
    domain_labels = DOMAIN.split(".")
    if labels[-len(domain_labels):] != domain_labels:
        return None
    body = labels[:-len(domain_labels)]
    if not body:
        return None
    if body[0].upper() == "END":
        return ("END", None, body[1] if len(body) > 1 else "")
    if len(body) < 3:
        return None
    return (body[0], body[1], body[2])


def main():
    parser = argparse.ArgumentParser(description="Decode DNS-tunnelled data")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except PermissionError:
        print(f"Port {args.port} needs sudo (ports under 1024), or use --port 5353")
        raise SystemExit(1)
    print(f"Decoder listening on {args.host}:{args.port} for *.{DOMAIN}")
    print("Waiting for chunks... (Ctrl+C to stop)")

    sessions = {}
    try:
        while True:
            packet, addr = sock.recvfrom(2048)
            try:
                qid, qname, question = parse_dns_query(packet)
            except Exception as e:
                print(f"Ignoring bad packet: {e}")
                continue
            # ACK every query, so the encoder knows it arrived
            sock.sendto(build_dns_response(qid, question), addr)

            parsed = parse_qname(qname)
            if parsed is None:
                continue
            seq, chunk, session = parsed
            store = sessions.setdefault(session, {})
            if seq == "END":
                if not store:
                    print(f"Session {session}: END with no chunks")
                    continue
                ordered = [store[k] for k in sorted(store)]
                encoded = "".join(ordered).upper()
                encoded += "=" * (-len(encoded) % 8)
                try:
                    raw = base64.b32decode(encoded)
                except Exception as e:
                    print(f"Session {session}: Base32 decode failed: {e}")
                    continue
                header_json, _, file_bytes = raw.partition(b"\n")
                try:
                    header = json.loads(header_json)
                except Exception as e:
                    print(f"Session {session}: bad header: {e}")
                    continue
                out_name = "recovered_" + header["filename"]
                with open(out_name, "wb") as f:
                    f.write(file_bytes)
                size_ok = len(file_bytes) == header["size"]
                sha_ok = hashlib.sha256(file_bytes).hexdigest() == header["sha256"]
                print(f"Session {session}: rebuilt {out_name}")
                print(f"  size match: {size_ok} ({len(file_bytes)} / {header['size']})")
                print(f"  sha256 match: {sha_ok}")
                print(f"  Check with: diff {header['filename']} {out_name}")
                del sessions[session]
            else:
                store[seq] = chunk
                print(f"Session {session}: chunk {seq} ({len(store)} stored)", flush=True)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
