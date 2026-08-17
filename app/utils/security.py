"""Şifre saklama yardımcıları.

Harici bağımlılık istemediğimiz için stdlib PBKDF2-HMAC-SHA256 kullanılıyor.
"""
from __future__ import annotations

import hashlib
import hmac
import os

ITERATIONS = 200_000
SALT_BYTES = 16


def make_salt() -> str:
    return os.urandom(SALT_BYTES).hex()


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    )
    return dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt), expected_hash)


def new_credentials(password: str) -> tuple[str, str]:
    """(salt, hash) çifti üretir."""
    salt = make_salt()
    return salt, hash_password(password, salt)
