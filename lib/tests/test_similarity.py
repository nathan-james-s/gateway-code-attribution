"""T016: keyed similarity signatures."""

from __future__ import annotations

import pytest

from gcattr.lexer import tokenize
from gcattr.similarity import jaccard, lsh_bands, minhash, shingles

from .conftest import TEST_KEY


def test_shingles_whole_list_for_short_lines() -> None:
    assert len(shingles(tokenize("a = b"))) == 1  # up to 3 tokens: one shingle
    assert len(shingles(tokenize("a = b + c"))) == 4  # token bigrams


def test_minhash_and_bands_shape_and_determinism() -> None:
    sig = minhash(tokenize("response = client.post(url, json=payload)"), TEST_KEY, 1)
    assert len(sig) == 32 and all(0 <= v < 2**32 for v in sig)
    assert sig == minhash(tokenize("response=client.post( url,json=payload )"), TEST_KEY, 1)
    bands = lsh_bands(sig, TEST_KEY, 1)
    assert len(bands) == 8 and all(len(b) == 8 for b in bands)


def test_similarity_ordering() -> None:
    base = "response = client.post(url, json=payload, headers=headers, timeout=30)"
    near = "response = client.post(url, json=payload, headers=headers, timeout=60)"
    far = "print('completely unrelated line of code here')"
    s_near = jaccard(minhash(tokenize(base), TEST_KEY, 1), minhash(tokenize(near), TEST_KEY, 1))
    s_far = jaccard(minhash(tokenize(base), TEST_KEY, 1), minhash(tokenize(far), TEST_KEY, 1))
    assert s_near > 0.6 > s_far


def test_jaccard_rejects_mismatched_signatures() -> None:
    with pytest.raises(ValueError):
        jaccard((1, 2), (1,))
