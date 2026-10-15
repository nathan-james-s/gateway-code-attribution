"""Keyed similarity fingerprints: shingles, MinHash and LSH bands (research R9; docs/privacy.md)."""

from __future__ import annotations

from functools import lru_cache

from .algorithm import params_for
from .fingerprint import FingerprintKey, keyed
from .lexer import Token

__all__ = ["jaccard", "lsh_bands", "minhash", "shingles"]

_MASK64 = (1 << 64) - 1
_MIX = 0x9E3779B97F4A7C15
_SHINGLE = 2


def shingles(tokens: list[Token]) -> list[str]:
    """Token 2-grams; the whole token list as one shingle for lines of up to 3 tokens. Bigrams, not trigrams: one
    changed token on a short line removes two shingles instead of three, so an edited 6-10 token line stays
    recognizably similar (measured on the scenario set, T109)."""
    texts = [t.text for t in tokens]
    if len(texts) <= _SHINGLE + 1:
        return ["\x1f".join(texts)] if texts else []
    return ["\x1f".join(texts[i : i + _SHINGLE]) for i in range(len(texts) - _SHINGLE + 1)]


@lru_cache(maxsize=64)
def _seeds(key: FingerprintKey, alg: int, size: int) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(keyed(key, b"mh\x1f" + f"v{alg}\x1f".encode() + i.to_bytes(2, "big"))[:8], "big")
        for i in range(size)
    )


def _shingle_hash(key: FingerprintKey, alg: int, shingle: str) -> int:
    return int.from_bytes(keyed(key, b"sh\x1f" + f"v{alg}\x1f".encode() + shingle.encode("utf-8"))[:8], "big")


def minhash(tokens: list[Token], key: FingerprintKey, alg: int) -> tuple[int, ...]:
    size = params_for(alg).minhash_size
    hashes = [_shingle_hash(key, alg, s) for s in set(shingles(tokens))]
    if not hashes:
        raise ValueError("cannot compute a signature for an empty token list")
    return tuple(
        min((((h ^ seed) * _MIX) & _MASK64) >> 32 for h in hashes) for seed in _seeds(key, alg, size)
    )


def lsh_bands(signature: tuple[int, ...], key: FingerprintKey, alg: int) -> tuple[bytes, ...]:
    p = params_for(alg)
    if len(signature) != p.lsh_bands * p.lsh_rows:
        raise ValueError("signature length does not match lsh_bands x lsh_rows")
    out = []
    for b in range(p.lsh_bands):
        rows = signature[b * p.lsh_rows : (b + 1) * p.lsh_rows]
        packed = b"".join(r.to_bytes(4, "big") for r in rows)
        out.append(keyed(key, b"lsh\x1f" + f"v{alg}\x1f".encode() + bytes([b]) + packed)[:8])
    return tuple(out)


def jaccard(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """Estimated Jaccard similarity: the fraction of equal signature positions."""
    if len(a) != len(b) or not a:
        raise ValueError("signatures must be non-empty and the same length")
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)
