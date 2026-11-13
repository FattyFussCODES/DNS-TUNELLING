"""Password encryption for the tunnel stream.

Primary backend: Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography`
package. The key is derived with PBKDF2-HMAC-SHA256 from the password and a
random 16-byte salt that travels with the ciphertext, so the receiver needs
nothing but the password.

Fallback, used only when `cryptography` is not installed: a SHA256-based
keystream XOR with an HMAC-SHA256 tag. It is not as strong as Fernet (no
audited implementation), so it is marked in the blob and documented rather
than silently substituted. Both blobs are self-describing: a 4-byte magic
prefix says which backend produced them.

Blob layout: MAGIC(4) || salt(16) || [Fernet token]        (DTC1)
             MAGIC(4) || salt(16) || nonce(16) || ct || tag(32)  (DTX1)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

try:  # pragma: no cover - depends on the environment
    from cryptography.fernet import Fernet, InvalidToken

    HAVE_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False

    class InvalidToken(Exception):
        """Stand-in so the except clause below works without cryptography."""


MAGIC_FERNET = b"DTC1"
MAGIC_XOR = b"DTX1"
SALT_LEN = 16
NONCE_LEN = 16
TAG_LEN = 32
PBKDF2_ITERATIONS = 200_000
KEY_LEN = 32


class DecryptionError(ValueError):
    """Wrong password or corrupted ciphertext."""


def key_from_password(
    password: str | bytes,
    salt: bytes,
    iterations: int = PBKDF2_ITERATIONS,
) -> bytes:
    """32-byte key from a password and a salt; same inputs, same key."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    if not password:
        raise ValueError("password must not be empty")
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=KEY_LEN)


def encrypt_bytes(data: bytes, password: str | bytes) -> bytes:
    salt = os.urandom(SALT_LEN)
    key = key_from_password(password, salt)
    if HAVE_CRYPTOGRAPHY:
        token = Fernet(base64.urlsafe_b64encode(key)).encrypt(data)
        return MAGIC_FERNET + salt + token
    nonce = os.urandom(NONCE_LEN)
    ciphertext = _xor_stream(data, key, nonce)
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    return MAGIC_XOR + salt + nonce + ciphertext + tag


def decrypt_bytes(blob: bytes, password: str | bytes) -> bytes:
    if len(blob) < 4 + SALT_LEN:
        raise DecryptionError("ciphertext is truncated")
    magic, rest = blob[:4], blob[4:]
    salt, body = rest[:SALT_LEN], rest[SALT_LEN:]
    key = key_from_password(password, salt)
    if magic == MAGIC_FERNET:
        if not HAVE_CRYPTOGRAPHY:
            raise DecryptionError(
                "this stream was encrypted with the cryptography package, "
                "which is not installed here (pip install cryptography)"
            )
        try:
            return Fernet(base64.urlsafe_b64encode(key)).decrypt(body)
        except (InvalidToken, ValueError) as exc:
            raise DecryptionError("wrong password or corrupted data") from exc
    if magic == MAGIC_XOR:
        if len(body) < NONCE_LEN + TAG_LEN:
            raise DecryptionError("ciphertext is truncated")
        nonce = body[:NONCE_LEN]
        ciphertext = body[NONCE_LEN:-TAG_LEN]
        tag = body[-TAG_LEN:]
        expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise DecryptionError("wrong password or corrupted data")
        return _xor_stream(ciphertext, key, nonce)
    raise DecryptionError(f"unknown ciphertext format {magic!r}")


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        take = min(len(block), len(data) - offset)
        for i in range(take):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += take
        counter += 1
    return bytes(out)


def encrypt_file(src: str, dst: str, password: str | bytes) -> int:
    """Encrypt a file on disk; returns the ciphertext length."""
    with open(src, "rb") as handle:
        blob = encrypt_bytes(handle.read(), password)
    with open(dst, "wb") as handle:
        handle.write(blob)
    return len(blob)


def decrypt_file(src: str, dst: str, password: str | bytes) -> int:
    """Decrypt a file on disk; returns the plaintext length."""
    with open(src, "rb") as handle:
        data = decrypt_bytes(handle.read(), password)
    with open(dst, "wb") as handle:
        handle.write(data)
    return len(data)
