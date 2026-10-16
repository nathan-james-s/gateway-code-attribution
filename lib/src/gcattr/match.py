"""Tiered, author-scoped, multiset matching (spec FR-009-FR-015; research R11). Pure and deterministic.

Tiers, in order: not observed, indeterminate (trivial), exact, anchored, broad, wrapped, split, then human. The
last two are for a formatter splitting one AI line over several (a wrapped call, a dict literal, a method chain;
found by the eval, T109). Wrapped: runs of consecutive added lines still unmatched are joined and matched as one
line, exact or by similarity, and each non-trivial line of a matching run is AI modified. Split: an unmatched
fragment next to lines that matched a candidate by similarity joins them when that makes them more similar to it.
Both report the tier (anchored or broad) of what they matched; neither is a new outcome.
"""

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
from .types import AddedLine, Candidate, Confidence, LineOutcome, Tier

__all__ = ["LookupKeys", "attribute", "lookup_keys", "select_candidates"]

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
        self._joined = 0

    def joined_idx(self) -> int:
        """A fresh cache index for a joined line (added lines use their own, non-negative, indexes)."""
        self._joined -= 1
        return self._joined

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
    in_files: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )  # author -> path -> lines
    for i, line in enumerate(lines):
        if line.credited_github_id is None or line.credited_github_id not in candidates_by_author:
            results[i] = NOT_OBSERVED
            continue
        tokens = tokenize(normalize_line(line.text, alg))
        in_files[line.credited_github_id][line.file_path].append(i)
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
        matched: dict[int, int] = {}  # line -> the candidate it matched by similarity

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
                matched[i] = ci
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
                matched[i] = ci
                results[i] = LineOutcome("ai_modified", "broad", "lower", sim, m.cands[ci].capture_event_id)

        # 6: wrapped tier — a formatter split one AI line over several consecutive lines
        _wrapped(m, lines, results, in_files[author], anchors, matched)

        # 7: split fragments — the rest of a line whose main part already matched by similarity
        _split(m, lines, results, in_files[author], matched)

        # 8: everything else
        for i in idxs:
            if results[i] is None:
                results[i] = HUMAN

    return [r if r is not None else HUMAN for r in results]


WRAP_MAX_LINES = 8


def _runs(lines: Sequence[AddedLine], results: list[LineOutcome | None], idxs: list[int]) -> list[list[int]]:
    """Runs of consecutive line numbers that are unmatched or trivial (a wrapped line's fragments)."""
    runs: list[list[int]] = []
    current: list[int] = []
    for i in sorted(idxs, key=lambda i: lines[i].line_no):
        open_ = results[i] is None or results[i] is INDETERMINATE
        if open_ and current and lines[i].line_no == lines[current[-1]].line_no + 1:
            current.append(i)
            continue
        if current:
            runs.append(current)
        current = [i] if open_ else []  # a matched line ends the run
    if current:
        runs.append(current)
    return [r for r in runs if sum(results[i] is None for i in r) >= 1 and len(r) >= 2]


def _wrapped(
    m: _AuthorMatcher,
    lines: Sequence[AddedLine],
    results: list[LineOutcome | None],
    files: Mapping[str, list[int]],
    anchors: Mapping[str, set[str]],
    matched: dict[int, int],
) -> None:
    for path in sorted(files):
        for run in _runs(lines, results, files[path]):
            start = 0
            while start < len(run) - 1:
                found = 0
                for length in range(min(WRAP_MAX_LINES, len(run) - start), 1, -1):
                    window = run[start : start + length]
                    if results[window[0]] is not None or results[window[-1]] is not None:
                        continue  # a window starts and ends on an unmatched, non-trivial line
                    joined = AddedLine(
                        path, lines[window[0]].line_no, " ".join(lines[i].text for i in window), None
                    )
                    hit = _window_hit(m, m.joined_idx(), joined, anchors.get(path, set()))
                    if hit is None:
                        continue
                    ci, sim, tier = hit
                    m.used.add(ci)
                    conf: Confidence = "high" if tier == "anchored" else "lower"
                    for i in window:
                        if results[i] is None:
                            matched[i] = ci
                            results[i] = LineOutcome(
                                "ai_modified", tier, conf, sim, m.cands[ci].capture_event_id
                            )
                    found = length
                    break
                start += found or 1


def _split(
    m: _AuthorMatcher,
    lines: Sequence[AddedLine],
    results: list[LineOutcome | None],
    files: Mapping[str, list[int]],
    matched: dict[int, int],
) -> None:
    """A formatter splitting one AI line can leave a short fragment (``if missing:`` above its ``raise``, one link of
    a method chain) next to the part that matched. A fragment joins the lines that matched candidate ``c`` when the
    joined text is more similar to ``c`` than they are alone. Only the joined text's shingles that are in ``c`` can
    raise the estimate, so an unrelated line next to a match never joins it."""
    for path in sorted(files):
        order = sorted(files[path], key=lambda i: lines[i].line_no)
        at = {lines[i].line_no: i for i in order}
        for j in order:
            ci = matched.get(j)
            if ci is None or (lines[j].line_no - 1 in at and matched.get(at[lines[j].line_no - 1]) == ci):
                continue  # not a similarity match, or not the first line of its group
            core = [j]
            while (n := lines[core[-1]].line_no + 1) in at and matched.get(at[n]) == ci:
                core.append(at[n])
            c = m.cands[ci]
            if c.key_gen not in m.keys:
                continue

            # the open lines (unmatched or trivial) directly above and below the group
            room = WRAP_MAX_LINES - len(core)
            before: list[int] = []
            no = lines[core[0]].line_no - 1
            while len(before) < room and _open(results, at, no):
                before.insert(0, at[no])
                no -= 1
            after: list[int] = []
            no = lines[core[-1]].line_no + 1
            while len(after) < room and _open(results, at, no):
                after.append(at[no])
                no += 1
            base = _joined_sim(m, lines, core, c)
            best: tuple[float, int, list[int]] | None = None
            for lo in range(len(before) + 1):
                for hi in range(len(after) + 1):
                    window = before[len(before) - lo :] + core + after[:hi]
                    if len(window) > WRAP_MAX_LINES or not any(results[i] is None for i in window):
                        continue
                    s = _joined_sim(m, lines, window, c)
                    if s > base and (best is None or (s, -len(window)) > (best[0], best[1])):
                        best = (s, -len(window), window)
            if best is None:
                continue
            first = results[j]
            assert first is not None
            for i in best[2]:
                if results[i] is None:
                    matched[i] = ci
                    results[i] = LineOutcome(
                        "ai_modified", first.tier, first.confidence, best[0], c.capture_event_id
                    )


def _open(results: list[LineOutcome | None], at: Mapping[int, int], line_no: int) -> bool:
    return line_no in at and (results[at[line_no]] is None or results[at[line_no]] is INDETERMINATE)


def _joined_sim(m: _AuthorMatcher, lines: Sequence[AddedLine], window: list[int], c: Candidate) -> float:
    first = lines[window[0]]
    joined = AddedLine(first.file_path, first.line_no, " ".join(lines[i].text for i in window), None)
    return jaccard(m.line_fp(m.joined_idx(), joined, c.alg, c.key_gen).sig, c.minhash)


def _window_hit(
    m: _AuthorMatcher, idx: int, joined: AddedLine, anchor_events: set[str]
) -> tuple[int, float, Tier] | None:
    for g_alg, g_gen in m.groups:  # the joined text equals a captured line: the formatter only re-wrapped it
        fp = m.line_fp(idx, joined, g_alg, g_gen)
        for ci in m.by_exact.get((g_alg, g_gen, fp.exact), ()):
            if ci not in m.used:
                tier: Tier = "anchored" if m.cands[ci].capture_event_id in anchor_events else "broad"
                return ci, 1.0, tier
    pool = sorted(ci for ev in sorted(anchor_events) for ci in m.by_event[ev])
    hit = _best(m, idx, joined, pool, anchored=True)
    if hit is not None:
        return hit[0], hit[1], "anchored"
    pool_set: set[int] = set()
    for g_alg, g_gen in m.groups:
        fp = m.line_fp(idx, joined, g_alg, g_gen)
        for b, h in enumerate(fp.bands):
            pool_set.update(m.by_band.get((g_alg, g_gen, b, h), ()))
    hit = _best(m, idx, joined, sorted(pool_set), anchored=False)
    return (hit[0], hit[1], "broad") if hit is not None else None


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


# ------------------------------------------------------------------------------------- candidate lookup
class LookupKeys(NamedTuple):
    """Everything ``attribute`` can look candidates up by, for one author: exact fingerprints and LSH band hashes
    of each added line and of each window of consecutive lines the wrapped tier may join, per (alg, key_gen)."""

    exact: frozenset[tuple[int, int, bytes]]  # (alg, key_gen, exact_fp)
    bands: frozenset[tuple[int, int, int, bytes]]  # (alg, key_gen, band, band_hash)


def lookup_keys(
    lines: Sequence[AddedLine], keys: Mapping[int, FingerprintKey], alg: int = ALG
) -> dict[int, LookupKeys]:
    """Per credited author, the keys to fetch that author's candidates by, so a store need not load every capture
    in the matching window. Passing ``attribute`` only the candidates that ``select_candidates`` would keep (in a
    store: rows whose exact fingerprint or a band is in these keys, plus every line of the capture events among
    the exact hits) gives exactly the outcomes it gives with all of them."""
    params_for(alg)
    files: dict[int, dict[str, list[AddedLine]]] = defaultdict(lambda: defaultdict(list))
    for line in lines:
        if line.credited_github_id is not None:
            files[line.credited_github_id][line.file_path].append(line)
    out: dict[int, LookupKeys] = {}
    for author, by_path in files.items():
        texts: list[str] = []
        for path_lines in by_path.values():
            ordered = sorted(path_lines, key=lambda ln: ln.line_no)
            trivial = [is_trivial(tokenize(normalize_line(ln.text, alg)), alg) for ln in ordered]
            for i, ln in enumerate(ordered):
                if not trivial[i]:
                    texts.append(ln.text)  # the line itself (exact, anchored and broad tiers)
                # windows the wrapped tier may join: consecutive lines, starting and ending on non-trivial ones
                for j in range(i + 1, min(i + WRAP_MAX_LINES, len(ordered))):
                    if ordered[j].line_no != ordered[j - 1].line_no + 1:
                        break
                    if not trivial[i] and not trivial[j]:
                        texts.append(" ".join(x.text for x in ordered[i : j + 1]))
        exact: set[tuple[int, int, bytes]] = set()
        bands: set[tuple[int, int, int, bytes]] = set()
        for text in dict.fromkeys(texts):
            tokens = tokenize(normalize_line(text, alg))
            if not tokens:
                continue
            for gen, key in keys.items():
                exact.add((alg, gen, exact_fp(tokens, key, alg)))
                for b, h in enumerate(lsh_bands(minhash(tokens, key, alg), key, alg)):
                    bands.add((alg, gen, b, h))
        out[author] = LookupKeys(frozenset(exact), frozenset(bands))
    return out


def select_candidates(candidates: Sequence[Candidate], lk: LookupKeys) -> list[Candidate]:
    """The candidates a store returns for ``lk``: exact or band hits, and every line of an event with an exact hit."""
    exact = [c for c in candidates if (c.alg, c.key_gen, c.exact_fp) in lk.exact]
    events = {c.capture_event_id for c in exact}
    return [
        c
        for c in candidates
        if c.capture_event_id in events
        or (c.alg, c.key_gen, c.exact_fp) in lk.exact
        or any((c.alg, c.key_gen, b, h) in lk.bands for b, h in enumerate(c.lsh_bands))
    ]
