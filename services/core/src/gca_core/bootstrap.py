"""Post-migration bootstrap run by the chart's migrations Job.

- Lets the read-only reporting role log in.
- Applies the chart's attribution and per-developer settings to `portal_settings`. A setting is written only when
  its Helm value differs from the one the chart applied last time, so an upgrade applies what the adopter changed
  in their values without undoing what an admin has since set on the portal's settings page.
"""

from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .db import engine

SETTINGS = (
    "per_developer_enabled",
    "visible_roles",
    "matching_window_days",
    "retention_days",
    "exclusion_rules",
)


def apply_settings(conn: Connection, values: dict[str, Any]) -> list[str]:
    """Write each Helm-supplied setting that changed since the chart last applied it. Returns what was written."""
    values = {k: v for k, v in values.items() if k in SETTINGS}
    previous = conn.execute(text("SELECT helm_values FROM portal_settings WHERE id = 1")).scalar() or {}
    changed = [k for k in SETTINGS if k in values and previous.get(k) != values[k]]
    for k in changed:  # k is one of SETTINGS, never input
        conn.execute(text(f"UPDATE portal_settings SET {k} = :v WHERE id = 1"), {"v": values[k]})  # noqa: S608
    conn.execute(
        text("UPDATE portal_settings SET helm_values = CAST(:h AS jsonb) WHERE id = 1"),
        {"h": json.dumps(values)},
    )
    return changed


def main() -> int:
    settings = os.environ.get("GCA_SETTINGS")
    if settings:
        with engine().begin() as conn:
            changed = apply_settings(conn, json.loads(settings))
        print(f"settings applied from the chart: {', '.join(changed) or 'none changed'}")
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
