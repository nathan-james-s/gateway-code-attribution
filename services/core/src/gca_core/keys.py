"""Fingerprint keys from a mounted Secret directory (FR-035, FR-036; data-model.md KeyGeneration).

Layout: one file per key generation, named ``<key_gen>``, holding at least 32 raw bytes base64-encoded, plus a
file ``active`` holding the active generation number. Key material is never logged or returned in reprs.
"""

from __future__ import annotations

import base64
import binascii
import os
import threading
from pathlib import Path

from gcattr import FingerprintKey

__all__ = ["KeyRing", "KeyRingError", "load_keys"]


class KeyRingError(RuntimeError):
    pass


def load_keys(directory: str | os.PathLike[str]) -> tuple[dict[int, FingerprintKey], int]:
    """Return ``(keys_by_generation, active_generation)``."""
    root = Path(directory)
    active_file = root / "active"
    if not active_file.is_file():
        raise KeyRingError(f"no 'active' file in key directory {root}")
    try:
        active = int(active_file.read_text().strip())
    except ValueError as exc:
        raise KeyRingError("'active' must contain a key generation number") from exc
    keys: dict[int, FingerprintKey] = {}
    for entry in root.iterdir():
        # Kubernetes Secret mounts add ..data symlinks and dot-directories; only numeric names are keys.
        if not entry.name.isdigit() or not entry.is_file():
            continue
        gen = int(entry.name)
        try:
            secret = base64.b64decode(entry.read_text().strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise KeyRingError(f"key generation {gen} is not valid base64") from exc
        try:
            keys[gen] = FingerprintKey(gen, secret).check()
        except ValueError as exc:
            raise KeyRingError(f"key generation {gen}: {exc}") from exc
    if active not in keys:
        raise KeyRingError(f"active key generation {active} has no key file")
    return keys, active


class KeyRing:
    """Thread-safe holder that reloads when the mounted directory changes (key rotation, T076)."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._dir = Path(directory)
        self._lock = threading.Lock()
        self._mtime = -1.0
        self._keys: dict[int, FingerprintKey] = {}
        self._active = 0
        self.reload(force=True)

    def _stamp(self) -> float:
        stamps = [p.stat().st_mtime for p in self._dir.iterdir() if p.name == "active" or p.name.isdigit()]
        return max(stamps, default=0.0)

    def reload(self, force: bool = False) -> bool:
        stamp = self._stamp()
        if not force and stamp == self._mtime:
            return False
        keys, active = load_keys(self._dir)
        with self._lock:
            self._keys, self._active, self._mtime = keys, active, stamp
        return True

    @property
    def active(self) -> FingerprintKey:
        with self._lock:
            return self._keys[self._active]

    @property
    def all(self) -> dict[int, FingerprintKey]:
        with self._lock:
            return dict(self._keys)

    def __repr__(self) -> str:
        return f"KeyRing(dir={self._dir!s}, generations={sorted(self._keys)}, active={self._active})"
