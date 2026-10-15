"""The ``gca`` command-line tool (contracts/library-api.md; T096). Other packages add subcommands via the
``gca.commands`` entry-point group: each entry point is a callable ``register(subparsers) -> None``.

- ``gca version``: library version, ``ALG``, ``SUPPORTED_ALGS`` and the Unicode pin.
- ``gca fingerprint``: fingerprints (JSON lines, no content) for a recorded response stream on stdin.
- ``gca attribute``: attribute a local branch range against exported captures, as the PR check would.

Exit codes: 0 ok; 2 input error; 3 Unicode version mismatch; 4 unsupported algorithm version.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections.abc import Sequence
from importlib import metadata

from . import ALG, PARAMS, SUPPORTED_ALGS, UnicodeVersionMismatch, UnsupportedAlg, __version__
from .classify import summarize
from .diff import DEFAULT_EXCLUSIONS, ExclusionRules
from .gitlocal import GitError, read_change
from .io import KeyFileError, fingerprint_outputs, fingerprint_to_json, iter_jsonl, load_keys, read_candidates
from .match import attribute
from .streams import parse_stream
from .types import API_FORMATS

EXIT_INPUT, EXIT_UNICODE, EXIT_ALG = 2, 3, 4

__all__ = ["main"]


def _cmd_version(args: argparse.Namespace) -> int:
    info = {
        "library_version": __version__,
        "alg": ALG,
        "supported_algs": list(SUPPORTED_ALGS),
        "pinned_unicode_version": PARAMS[ALG].unicode_version,
        "interpreter_unicode_version": unicodedata.unidata_version,
    }
    if args.json:
        print(json.dumps(info))
    else:
        for k, v in info.items():
            print(f"{k}: {v}")
    return 0


def _fail(code: int, message: str) -> int:
    print(f"gca: {message}", file=sys.stderr)
    return code


def _cmd_fingerprint(args: argparse.Namespace) -> int:
    """Fingerprints for one recorded response (SSE or JSON body) read from stdin. No content is printed."""
    try:
        keys, active = load_keys(args.key_file, args.key_gen)
    except (KeyFileError, OSError) as exc:
        return _fail(EXIT_INPUT, str(exc))
    data = sys.stdin.buffer.read()
    result = fingerprint_outputs(parse_stream(args.format, [data]), keys[active], args.alg)
    rows = [fingerprint_to_json(fp) for fp in result.lines]
    if args.json:
        print(
            json.dumps(
                {"lines": rows, "failures": result.failures, "tool_call_count": result.tool_call_count}
            )
        )
    else:
        for line in iter_jsonl([*rows, *({"failure": cause} for cause in result.failures)]):
            print(line)
    return 0


def _parse_authors(pairs: Sequence[str]) -> dict[str, int]:
    out = {}
    for pair in pairs:
        email, _, gid = pair.rpartition("=")
        if not email or not gid.isdigit():
            raise ValueError(f"--author takes EMAIL=GITHUB_ID, got {pair!r}")
        out[email] = int(gid)
    return out


def _cmd_attribute(args: argparse.Namespace) -> int:
    """Attribute ``base...head`` of a local repository against a captures file, as the PR check would."""
    try:
        keys, _ = load_keys(args.key_file, args.key_gen)
        with open(args.captures, encoding="utf-8") as fh:
            candidates = read_candidates(fh)
        authors = _parse_authors(args.author)
        rules = ExclusionRules(args.exclude if args.exclude is not None else DEFAULT_EXCLUSIONS)
        change = read_change(args.repo, args.base, args.head, rules=rules, authors=authors)
    except (KeyFileError, OSError, ValueError, GitError) as exc:
        return _fail(EXIT_INPUT, str(exc))
    outcomes = attribute(change.lines, candidates, keys, args.alg)
    summary = summarize(outcomes)
    rows = []
    for ln, o in zip(change.lines, outcomes, strict=True):
        row = {
            "file_path": ln.file_path,
            "line_no": ln.line_no,
            "outcome": o.outcome,
            "tier": o.tier,
            "confidence": o.confidence,
            "similarity": o.similarity,
            "credited_github_id": ln.credited_github_id,
            "matched_capture_event_id": o.matched_capture_event_id,
        }
        if args.explain:  # the line is already in the user's own checkout
            row["text"] = ln.text
        rows.append(row)
    report = {
        "alg": args.alg,
        "merge_base": change.merge_base,
        "head": change.head,
        "lines": rows,
        "excluded": change.excluded,
        "summary": summary,
    }
    if args.json:
        print(json.dumps(report))
        return 0
    for r in rows:
        tail = f"  {r['text']}" if args.explain else ""
        print(f"{r['file_path']}:{r['line_no']}\t{r['outcome']}\t{r['tier']}{tail}")
    for e in change.excluded:
        print(f"{e['path']}\texcluded ({e['reason']})")
    print(json.dumps({"summary": summary}))
    return 0


def _add_key_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--key-file",
        required=True,
        help="base64 fingerprint key, or a directory in the stack's Secret layout (one file per generation)",
    )
    p.add_argument("--key-gen", type=int, default=1, help="generation of a single --key-file (default 1)")
    p.add_argument("--alg", type=int, default=ALG, help=f"algorithm version (default {ALG})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gca", description="Gateway Code Attribution tools")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("version", help="print library version, algorithm version and Unicode pin")
    p.set_defaults(func=_cmd_version)

    f = sub.add_parser("fingerprint", help="fingerprint a recorded response stream read from stdin")
    _add_key_args(f)
    f.add_argument("--format", required=True, choices=API_FORMATS, help="the stream's API format")
    f.set_defaults(func=_cmd_fingerprint)

    a = sub.add_parser("attribute", help="attribute a local branch range against exported captures")
    a.add_argument("--repo", default=".", help="path to the local repository (default: .)")
    a.add_argument("--base", required=True, help="base ref; lines are read from merge-base(base, head)")
    a.add_argument("--head", required=True, help="head ref")
    a.add_argument("--captures", required=True, help="captures file: JSON lines, one captured line each")
    _add_key_args(a)
    a.add_argument(
        "--author",
        action="append",
        default=[],
        metavar="EMAIL=GITHUB_ID",
        help="map a commit email to a GitHub account id (no-reply addresses map themselves)",
    )
    a.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        help="exclusion rule (repeatable; default: the stack's default rules)",
    )
    a.add_argument("--explain", action="store_true", help="also print each line's text (from your checkout)")
    a.set_defaults(func=_cmd_attribute)
    for ep in metadata.entry_points(group="gca.commands"):
        try:
            ep.load()(sub)
        except Exception as exc:  # a broken plugin must not break the core CLI
            print(f"warning: could not load gca command plugin {ep.name!r}: {exc}", file=sys.stderr)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except UnicodeVersionMismatch as exc:
        return _fail(EXIT_UNICODE, str(exc))
    except UnsupportedAlg as exc:
        return _fail(EXIT_ALG, str(exc))
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
