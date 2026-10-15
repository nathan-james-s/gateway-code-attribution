"""Algorithm versions and their frozen parameters (Constitution III; research R8–R10).

Any change that can alter a fingerprint or an attribution outcome MUST add a new ``ALG`` value with its own
``AlgParams`` entry and golden corpus (``lib/tests/golden/alg-<n>/``). Existing entries are never edited after
their first release.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

__all__ = [
    "ALG",
    "PARAMS",
    "SUPPORTED_ALGS",
    "AlgParams",
    "UnicodeVersionMismatch",
    "UnsupportedAlg",
    "params_for",
]


class UnsupportedAlg(ValueError):
    """Raised when an algorithm version is not in ``SUPPORTED_ALGS``."""


class UnicodeVersionMismatch(RuntimeError):
    """Raised when the interpreter's Unicode database differs from the version pinned for an algorithm."""


@dataclass(frozen=True)
class AlgParams:
    unicode_version: str
    anchored_threshold: float
    broad_threshold: float
    minhash_size: int
    lsh_bands: int
    lsh_rows: int
    common_lines_version: str


ALG = 1
SUPPORTED_ALGS: tuple[int, ...] = (1,)

PARAMS: dict[int, AlgParams] = {
    # Thresholds are provisional until T109 calibrates them against the scenario set and T113 freezes them.
    # "15.0.0" is unicodedata.unidata_version of CPython 3.12.
    1: AlgParams(
        unicode_version="15.0.0",
        anchored_threshold=0.50,
        broad_threshold=0.75,
        minhash_size=32,
        lsh_bands=8,
        lsh_rows=4,
        common_lines_version="1",
    ),
}


def params_for(alg: int) -> AlgParams:
    """Return the parameters for ``alg``, enforcing the pinned Unicode version (R8)."""
    if alg not in SUPPORTED_ALGS:
        raise UnsupportedAlg(f"algorithm version {alg} is not supported (supported: {SUPPORTED_ALGS})")
    params = PARAMS[alg]
    if unicodedata.unidata_version != params.unicode_version:
        raise UnicodeVersionMismatch(
            f"alg {alg} requires Unicode {params.unicode_version}, "
            f"but this interpreter has {unicodedata.unidata_version}"
        )
    return params
