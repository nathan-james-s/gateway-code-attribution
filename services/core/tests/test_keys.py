from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import pytest

from gca_core.keys import KeyRing, KeyRingError, load_keys


def _write(d: Path, gen: int, secret: bytes) -> None:
    (d / str(gen)).write_text(base64.b64encode(secret).decode())


def test_load_and_reload(tmp_path: Path) -> None:
    _write(tmp_path, 1, b"\x01" * 32)
    (tmp_path / "active").write_text("1")
    (tmp_path / "..data").mkdir()  # Kubernetes mount noise is ignored
    keys, active = load_keys(tmp_path)
    assert active == 1 and keys[1].secret == b"\x01" * 32
    ring = KeyRing(tmp_path)
    assert "\\x01" not in repr(ring)
    time.sleep(0.01)
    _write(tmp_path, 2, b"\x02" * 32)
    (tmp_path / "active").write_text("2")
    os.utime(tmp_path / "active")
    assert ring.reload() and ring.active.key_gen == 2 and set(ring.all) == {1, 2}


def test_rejects_short_or_missing(tmp_path: Path) -> None:
    _write(tmp_path, 1, b"short")
    (tmp_path / "active").write_text("1")
    with pytest.raises(KeyRingError):
        load_keys(tmp_path)
    (tmp_path / "active").write_text("9")
    with pytest.raises(KeyRingError):
        load_keys(tmp_path)
