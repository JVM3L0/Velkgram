"""Password hashing for the web login (scrypt, stdlib only)."""

import base64
import binascii
import hashlib
import hmac
import secrets

_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16
_DKLEN = 64


def _scrypt(pw: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        pw.encode(), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=128 * n * r * 2
    )


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(pw, salt, _N, _R, _P, _DKLEN)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(digest).decode()
    return f"scrypt${_N}${_R}${_P}${salt_b64}${hash_b64}"


def verify_password(stored: str, candidate: str) -> bool:
    """Constant-time check; returns False (never raises) on malformed input."""
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(hash_b64, validate=True)
        actual = _scrypt(candidate, salt, int(n), int(r), int(p), len(expected))
    except (ValueError, binascii.Error, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)
