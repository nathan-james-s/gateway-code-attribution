"""The ``gca`` command-line tool (contracts/library-api.md). Other packages add subcommands via the
``gca.commands`` entry-point group: each entry point is a callable ``register(subparsers) -> None``.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections.abc import Sequence
from importlib import metadata

from . import ALG, PARAMS, SUPPORTED_ALGS, __version__

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gca", description="Gateway Code Attribution tools")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("version", help="print library version, algorithm version and Unicode pin")
    p.set_defaults(func=_cmd_version)
    for ep in metadata.entry_points(group="gca.commands"):
        try:
            ep.load()(sub)
        except Exception as exc:  # a broken plugin must not break the core CLI
            print(f"warning: could not load gca command plugin {ep.name!r}: {exc}", file=sys.stderr)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
