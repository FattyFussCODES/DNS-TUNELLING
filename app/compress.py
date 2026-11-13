"""zlib layer applied inside the tunnel stream, before Base32."""

from __future__ import annotations

import zlib

COMPRESS_THRESHOLD = 1024  # only bother above 1 KB
COMPRESS_LEVEL = 6


def should_compress(data: bytes) -> bool:
    return len(data) > COMPRESS_THRESHOLD


def compress_bytes(data: bytes, level: int = COMPRESS_LEVEL) -> bytes:
    return zlib.compress(data, level)


def decompress_bytes(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error as exc:  # truncated stream, or the flag lied
        raise ValueError(f"zlib decompress failed: {exc}") from exc
