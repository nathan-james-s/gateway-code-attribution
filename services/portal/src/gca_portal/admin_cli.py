"""Operator commands, run inside the portal pod (T065):

    kubectl -n <ns> exec deploy/<release>-gca-portal -- \\
        python -m gca_portal.admin_cli issue-credential --github-id <ID> --github-login <LOGIN>

Issues a personal gateway credential without a browser sign-in, for automation such as the end-to-end test.
Running it needs exec access to the portal pod, so it grants nothing an operator doesn't already have. The key
is printed to stdout once and nowhere else.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from gca_core.db import engine as make_engine
from gca_core.db.models_identity import Developer

from . import credentials
from .backends import make_backend
from .config import portal_config


def issue_credential(github_id: int, github_login: str) -> str:
    cfg = portal_config()
    engine = make_engine()
    with Session(engine) as s, s.begin():
        dev = s.scalar(select(Developer).where(Developer.github_id == github_id))
        if dev is None:
            dev = Developer(github_id=github_id, github_login=github_login)
            s.add(dev)
        dev.github_login = github_login
        dev.last_seen_at = datetime.now(UTC)
        s.flush()
        developer_id = dev.id
    _, key = credentials.issue(engine, make_backend(cfg), cfg.gateway_type, developer_id, github_id)
    return key


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gca_portal.admin_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("issue-credential", help="issue a gateway key for a GitHub account, printed once")
    p.add_argument("--github-id", type=int, required=True)
    p.add_argument("--github-login", required=True)
    args = parser.parse_args(argv)
    key = issue_credential(args.github_id, args.github_login)
    sys.stdout.write(key + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
