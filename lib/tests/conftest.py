from __future__ import annotations

import pytest

from gcattr import Candidate, FingerprintKey, LineFingerprint

TEST_KEY = FingerprintKey(1, b"\x42" * 32)
TEST_KEY_2 = FingerprintKey(2, b"\x24" * 32)


@pytest.fixture
def key() -> FingerprintKey:
    return TEST_KEY


def to_candidates(fps: list[LineFingerprint], event: str = "ev1") -> list[Candidate]:
    return [
        Candidate(
            event,
            f.exact_fp,
            f.minhash,
            f.path_suffix_fps,
            f.tool_call_ordinal,
            f.line_ordinal,
            f.alg,
            f.key_gen,
            f.lsh_bands,
        )
        for f in fps
    ]
