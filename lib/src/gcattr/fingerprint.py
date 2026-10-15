"""Keyed exact fingerprints and path-suffix fingerprints (research R7, R8; Constitution II)."""

from __future__ import annotations

import hashlib
import hmac
from typing import NamedTuple

from .lexer import Token
from .trivial import token_key

__all__ = ["MIN_SECRET_BYTES", "FingerprintKey", "exact_fp", "keyed", "path_suffix_fps"]

MIN_SECRET_BYTES = 32
_FP_BYTES = 16


class FingerprintKey(NamedTuple):
    key_gen: int
    secret: bytes

    def check(self) -> FingerprintKey:
        if self.key_gen < 1:
            raise ValueError("key_gen must be >= 1")
        if len(self.secret) < MIN_SECRET_BYTES:
            raise ValueError(f"fingerprint secret must be at least {MIN_SECRET_BYTES} bytes")
        return self

    def __repr__(self) -> str:  # never print key material
        return f"FingerprintKey(key_gen={self.key_gen}, secret=<redacted>)"


def keyed(key: FingerprintKey, message: bytes) -> bytes:
    return hmac.new(key.secret, message, hashlib.sha256).digest()


def exact_fp(tokens: list[Token], key: FingerprintKey, alg: int) -> bytes:
    """HMAC-SHA256(secret, "v{alg}\\x1f" + space-joined tokens), truncated to 16 bytes."""
    msg = f"v{alg}\x1f".encode() + token_key(tokens).encode("utf-8")
    return keyed(key, msg)[:_FP_BYTES]


def _path_components(path: str) -> list[str]:
    return [c for c in path.replace("\\", "/").split("/") if c and c != "."]


def path_suffix_fps(path: str | None, key: FingerprintKey, alg: int) -> tuple[bytes, ...]:
    """Keyed fingerprints of the last 1, 2 and 3 path components (at most 3 values; empty if no path)."""
    if not path:
        return ()
    comps = _path_components(path)
    out = []
    for n in (1, 2, 3):
        if len(comps) >= n:
            suffix = "/".join(comps[-n:])
            out.append(keyed(key, b"path\x1f" + f"v{alg}\x1f".encode() + suffix.encode("utf-8"))[:_FP_BYTES])
    return tuple(out)
