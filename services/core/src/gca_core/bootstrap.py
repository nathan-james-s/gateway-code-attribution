"""Post-migration bootstrap run by the chart's migrations Job: lets the read-only reporting role log in."""

from __future__ import annotations

import os

from sqlalchemy import text

from .db import engine


def main() -> int:
    password = os.environ.get("GCA_REPORTING_PASSWORD")
    if not password:
        print("GCA_REPORTING_PASSWORD not set; reporting role left without login")
        return 0
    with engine().begin() as conn:
        # DDL cannot take bind parameters; quote_literal/quote_ident make the values safe to inline.
        quoted = conn.execute(text("SELECT quote_literal(:p)"), {"p": password}).scalar_one()
        conn.execute(text(f"ALTER ROLE gca_reporting LOGIN PASSWORD {quoted}"))
        db = conn.execute(text("SELECT quote_ident(current_database())")).scalar_one()
        conn.execute(text(f"GRANT CONNECT ON DATABASE {db} TO gca_reporting"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO gca_reporting"))
    print("reporting role ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
