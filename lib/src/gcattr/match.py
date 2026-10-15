"""Tiered, author-scoped, multiset matching (spec FR-009-FR-015; research R11). Pure and deterministic."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from .algorithm import ALG, params_for
from .fingerprint import FingerprintKey, exact_fp, path_suffix_fps
from .lexer import Token, tokenize
from .normalize import normalize_line
from .similarity import jaccard, lsh_bands, minhash
from .trivial import is_trivial
from .types import AddedLine, Candidate, LineOutcome

__all__ = ["attribute"]

NOT_OBSERVED = LineOutcome("not_observed", "none", None, None, None)
INDETERMINATE = LineOutcome("indeterminate", "none", None, None, None)
HUMAN = LineOutcome("human", "none", None, None, None)


class _LineFp(NamedTuple):
    exact: bytes
    sig: tuple[int, ...]
    bands: tuple[bytes, ...]
    paths: frozenset[bytes]


def _tie(c: Candidate) -> tuple[str, int, int]:
    return (c.capture_event_id, c.tool_call_ordinal, c.line_ordinal)


class _AuthorMatcher:
    """Matching state for one credited author: candidates by (alg, key_gen), and which are used."""

    def __init__(self, candidates: Sequence[Candidate], keys: Mapping[int, FingerprintKey]) -> None:
        self.keys = keys
        self.cands = sorted(candidates, key=_tie)
        self.groups = sorted({(c.alg, c.key_gen) for c in self.cands if c.key_gen in keys})
        self.used: set[int] = set()
        self.by_exact: dict[tuple[int, int, bytes], list[int]] = defaultdict(list)
        self.by_event: dict[str, list[int]] = defaultdict(list)
        self.by_band: dict[tuple[int, int, int, bytes], list[int]] = defaultdict(list)
        for i, c in enumerate(self.cands):
            self.by_exact[(c.alg, c.key_gen, c.exact_fp)].append(i)
            self.by_event[c.capture_event_id].append(i)
            for b, h in enumerate(c.lsh_bands):
                self.by_band[(c.alg, c.key_gen, b, h)].append(i)
        self._fp_cache: dict[tuple[int, int, int], _LineFp] = {}

    def line_fp(self, idx: int, line: AddedLine, alg: int, key_gen: int) -> _LineFp:
        ck = (idx, alg, key_gen)
        if ck not in self._fp_cache:
            key = self.keys[key_gen]
            tokens = tokenize(normalize_line(line.text, alg))
            sig = minhash(tokens, key, alg)
            self._fp_cache[ck] = _LineFp(
                exact_fp(tokens, key, alg),
                sig,
                lsh_bands(sig, key, alg),
                frozenset(path_suffix_fps(line.file_path, key, alg)),
            )
        return self._fp_cache[ck]


def attribute(
    lines: Sequence[AddedLine],
    candidates_by_author: Mapping[int, Sequence[Candidate]],
    keys: Mapping[int, FingerprintKey],
    alg: int = ALG,
) -> list[LineOutcome]:
    params_for(alg)
    results: list[LineOutcome | None] = [None] * len(lines)
    tokens_by_line: dict[int, list[Token]] = {}

    # 1-2: not observed / indeterminate
    by_author: dict[int, list[int]] = defaultdict(list)
    for i, line in enumerate(lines):
        if line.credited_github_id is None or line.credited_github_id not in candidates_by_author:
            results[i] = NOT_OBSERVED
            continue
        tokens = tokenize(normalize_line(line.text, alg))
        if is_trivial(tokens, alg):
            results[i] = INDETERMINATE
            continue
        tokens_by_line[i] = tokens
        by_author[line.credited_github_id].append(i)

    for author in sorted(by_author):
        m = _AuthorMatcher(candidates_by_author[author], keys)
        idxs = sorted(by_author[author], key=lambda i: (lines[i].file_path, lines[i].line_no, i))
        anchors: dict[str, set[str]] = defaultdict(
            set
        )  # file path -> capture events with an exact match there

        # 3: exact tier (multiset)
        for i in idxs:
            best: int | None = None
            for g_alg, g_gen in m.groups:
                fp = m.line_fp(i, lines[i], g_alg, g_gen)
                for ci in m.by_exact.get((g_alg, g_gen, fp.exact), ()):
                    if ci not in m.used and (best is None or _tie(m.cands[ci]) < _tie(m.cands[best])):
                        best = ci
                        break
            if best is not None:
                m.used.add(best)
                c = m.cands[best]
                anchors[lines[i].file_path].add(c.capture_event_id)
                results[i] = LineOutcome("ai_unmodified", "exact", None, None, c.capture_event_id)

        # 4: anchored tier — candidates from capture events with >=1 exact match in this file (FR-010).
        for i in idxs:
            if results[i] is not None:
                continue
            pool: list[int] = []
            for ev in sorted(anchors.get(lines[i].file_path, ())):
                pool.extend(m.by_event[ev])
            hit = _best(m, i, lines[i], pool, anchored=True)
            if hit is not None:
                ci, sim = hit
                m.used.add(ci)
                results[i] = LineOutcome("ai_modified", "anchored", "high", sim, m.cands[ci].capture_event_id)

        # 5: broad tier — the author's candidates sharing at least one LSH band (path-only matches land here).
        for i in idxs:
            if results[i] is not None:
                continue
            pool_set: set[int] = set()
            for g_alg, g_gen in m.groups:
                fp = m.line_fp(i, lines[i], g_alg, g_gen)
                for b, h in enumerate(fp.bands):
                    pool_set.update(m.by_band.get((g_alg, g_gen, b, h), ()))
            hit = _best(m, i, lines[i], sorted(pool_set), anchored=False)
            if hit is not None:
                ci, sim = hit
                m.used.add(ci)
                results[i] = LineOutcome("ai_modified", "broad", "lower", sim, m.cands[ci].capture_event_id)

        # 6: everything else
        for i in idxs:
            if results[i] is None:
                results[i] = HUMAN

    return [r if r is not None else HUMAN for r in results]


def _best(
    m: _AuthorMatcher, i: int, line: AddedLine, pool: list[int], *, anchored: bool
) -> tuple[int, float] | None:
    best: tuple[float, tuple[str, int, int], int] | None = None
    for ci in pool:
        if ci in m.used:
            continue
        c = m.cands[ci]
        if c.key_gen not in m.keys:
            continue
        fp = m.line_fp(i, line, c.alg, c.key_gen)
        if anchored and c.path_suffix_fps and not (fp.paths & set(c.path_suffix_fps)):
            continue  # the capture named a different file: no cross-file anchoring
        p = params_for(c.alg)
        sim = jaccard(fp.sig, c.minhash)
        threshold = p.anchored_threshold if anchored else p.broad_threshold
        if sim < threshold:
            continue
        rank = (-sim, _tie(c), ci)
        if best is None or rank < (best[0], best[1], best[2]):
            best = (-sim, _tie(c), ci)
    if best is None:
        return None
    return best[2], -best[0]
