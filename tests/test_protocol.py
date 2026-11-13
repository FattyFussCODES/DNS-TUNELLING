"""Wire protocol: Base32, chunking, header, DNS packets, sequence ordering."""

from __future__ import annotations

import base64
import json
import os
import struct

from app import protocol
from app.utils import unique_path


def test_base32_roundtrip_preserves_bytes():
    data = b"Meet at 5\n"
    stream, header = protocol.build_stream(data, "secret.txt", compress=False)
    encoded = "".join(protocol.chunk_stream(stream))
    encoded += "=" * (-len(encoded) % 8)
    raw = base64.b32decode(encoded.upper())
    header_json, sep, payload = raw.partition(b"\n")
    assert sep == b"\n"
    assert payload == data
    parsed = json.loads(header_json)
    assert parsed["size"] == len(data)
    assert parsed["sha256"] == header["sha256"]
    assert parsed["filename"] == "secret.txt"
    assert parsed["compressed"] is False
    assert parsed["encrypted"] is False


def test_chunking_is_32_chars_and_count_matches_header():
    stream, header = protocol.build_stream(b"Meet at 5\n", "secret.txt", compress=False)
    chunks = protocol.chunk_stream(stream)
    assert len(chunks) == header["chunks"] == -(-len(stream) // 32)
    assert [len(c) for c in chunks[:-1]] == [32] * (len(chunks) - 1)
    assert 0 < len(chunks[-1]) <= 32
    assert all(set(c) <= set("abcdefghijklmnopqrstuvwxyz234567") for c in chunks)


def test_32_base32_chars_carry_20_bytes():
    assert len(base64.b32decode(("a" * 32).upper())) == protocol.CHUNK_PAYLOAD_BYTES == 20


def test_header_chunk_count_is_fixed_point():
    """The count lives in the header, whose length feeds the count."""
    for size in (0, 1, 14, 15, 16, 100, 1023, 1024, 1025, 4096):
        data = os.urandom(size)
        stream, header = protocol.build_stream(data, "f.bin", compress=False)
        assert header["chunks"] == -(-len(stream) // 32)
        # Rebuilding from the header's own count must not shift it again.
        assert protocol.chunk_count(stream) == header["chunks"]


def test_compress_and_encrypt_flags_match_reality():
    small = os.urandom(200)          # below the 1 KB threshold
    big = b"A" * 4096                # above it, compresses hard

    _, plain_small = protocol.build_stream(small, "s.bin", compress=True)
    assert plain_small["compressed"] is False

    _, plain_big = protocol.build_stream(big, "b.bin", compress=True)
    assert plain_big["compressed"] is True

    _, encrypted = protocol.build_stream(b"x" * 15, "e.bin", password="pw", compress=False)
    assert encrypted["encrypted"] is True
    assert encrypted["chunks"] > 10  # salt + IV + HMAC cost real chunks


def test_parse_qname_chunk_end_and_foreign():
    assert protocol.parse_qname("001.abc.482534.dnstunnel.cc.cd") == ("001", "abc", "482534")
    assert protocol.parse_qname("END.482534.dnstunnel.cc.cd") == ("END", None, "482534")
    assert protocol.parse_qname("end.482534.dnstunnel.cc.cd") == ("END", None, "482534")
    assert protocol.parse_qname("001.abc.482534.dnstunnel.cc.cd.") == ("001", "abc", "482534")
    assert protocol.parse_qname("www.google.com") is None
    assert protocol.parse_qname("dnstunnel.cc.cd") is None
    assert protocol.parse_qname("001.abc.dnstunnel.cc.cd") is None


def test_dns_query_roundtrip_and_ack():
    qname = "001." + "a" * 32 + ".482534.dnstunnel.cc.cd"
    qid = 0xBEEF
    packet = protocol.build_dns_query(qname, qid)

    assert struct.unpack(">HHHHHH", packet[:12]) == (qid, 0x0100, 1, 0, 0, 0)
    got_qid, got_name, question = protocol.parse_dns_query(packet)
    assert (got_qid, got_name) == (qid, qname)
    assert question == packet[12:]

    response = protocol.build_dns_response(qid, question)
    assert struct.unpack(">H", response[:2])[0] == qid
    assert struct.unpack(">HHHHHH", response[:12]) == (qid, 0x8180, 1, 1, 0, 0)
    assert response[-4:] == bytes([1, 1, 1, 1])


def test_oversized_label_is_rejected():
    try:
        protocol.build_dns_query("x" * 64 + ".dnstunnel.cc.cd", 1)
    except protocol.ProtocolError:
        return
    raise AssertionError("a 64-character label must be rejected")


def test_sequence_sort_is_numeric_not_lexicographic():
    """Regression: 1000+ chunks used to sort before 999 as strings."""
    labels = [f"{i:03d}" for i in (1, 999, 1000, 1001, 2)]
    assert sorted(labels) != ["001", "002", "999", "1000", "1001"]
    ordered = sorted(labels, key=protocol._seq_key)
    assert ordered == ["001", "002", "999", "1000", "1001"]


def test_unique_path_never_overwrites(tmp_path):
    first = unique_path(tmp_path, "secret.txt")
    assert first.name == "secret.txt"
    first.write_text("x")
    second = unique_path(tmp_path, "secret.txt")
    assert second.name == "secret (1).txt"
    second.write_text("x")
    assert unique_path(tmp_path, "secret.txt").name == "secret (2).txt"
    assert unique_path(tmp_path, "secret.txt", prefix="recovered_").name == "recovered_secret.txt"
