"""Encryption layer: round trip, wrong password, tamper detection, backends."""

from __future__ import annotations

import pytest

from app import crypto


def test_roundtrip_with_correct_password():
    data = b"Meet at 5\n" * 100
    blob = crypto.encrypt_bytes(data, "correct horse")
    assert crypto.decrypt_bytes(blob, "correct horse") == data


def test_ciphertext_contains_no_plaintext():
    blob = crypto.encrypt_bytes(b"Meet at 5" * 50, "pw")
    assert b"Meet at 5" not in blob
    assert blob[:4] == crypto.MAGIC_FERNET  # fernet is installed in this env


def test_wrong_password_fails_loudly():
    blob = crypto.encrypt_bytes(b"secret", "right")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_bytes(blob, "wrong")


def test_same_plaintext_encrypts_differently():
    a = crypto.encrypt_bytes(b"same bytes", "pw")
    b = crypto.encrypt_bytes(b"same bytes", "pw")
    assert a != b  # random salt every time
    assert crypto.decrypt_bytes(a, "pw") == crypto.decrypt_bytes(b, "pw")


def test_tampering_is_detected():
    blob = bytearray(crypto.encrypt_bytes(b"integrity matters", "pw"))
    blob[-1] ^= 0x01
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_bytes(bytes(blob), "pw")


def test_key_from_password_is_deterministic():
    salt = b"\x00" * crypto.SALT_LEN
    assert crypto.key_from_password("pw", salt) == crypto.key_from_password(b"pw", salt)
    assert len(crypto.key_from_password("pw", salt)) == 32
    assert crypto.key_from_password("pw", salt) != crypto.key_from_password("pw", b"\x01" * 16)


def test_fallback_backend_roundtrip(monkeypatch):
    """Without the cryptography package the XOR+HMAC path must still work."""
    monkeypatch.setattr(crypto, "HAVE_CRYPTOGRAPHY", False)
    blob = crypto.encrypt_bytes(b"lab only", "pw")
    assert blob[:4] == crypto.MAGIC_XOR
    assert crypto.decrypt_bytes(blob, "pw") == b"lab only"
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_bytes(blob, "nope")
