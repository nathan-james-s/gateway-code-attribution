"""Every dashboard query runs as the read-only reporting role (views only), with the broad toggle both ways."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

DASHBOARDS = Path(__file__).resolve().parents[3] / "charts" / "gateway-code-attribution" / "dashboards"


def _queries() -> list[tuple[str, str]]:
    out = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        board = json.loads(path.read_text())
        for var in board["templating"]["list"]:
            if var.get("type") == "query":
                out.append((f"{path.stem}:var:{var['name']}", var["query"]))
        for panel in board["panels"]:
            for target in panel.get("targets", []):  # text panels have none
                out.append((f"{path.stem}:{panel['title']}", target["rawSql"]))
    return out


def _render(sql: str, broad: str) -> str:
    sql = sql.replace("${broad}", broad)
    sql = re.sub(r"\$\{(repository|team|gateway):sqlstring\}", "'acme/none'", sql)
    return re.sub(r"\$__timeFilter\((\w+)\)", r"\1 > now() - interval '30 days'", sql)


@pytest.mark.parametrize(("name", "sql"), _queries(), ids=[n for n, _ in _queries()])
@pytest.mark.parametrize("broad", ["with_broad", "without_broad"])
def test_query_runs_as_reporting_role(pg_engine: Engine, name: str, sql: str, broad: str) -> None:
    with pg_engine.connect() as conn:
        conn.execute(text("SET ROLE gca_reporting"))
        try:
            conn.execute(text(_render(sql, broad).replace(":", r"\:"))).fetchall()
        finally:
            conn.rollback()


def test_every_attribution_dashboard_has_the_broad_toggle_and_shows_alg() -> None:
    for path in DASHBOARDS.glob("*.json"):
        if path.stem == "coverage":  # capture loss has no attribution figures, so no broad toggle
            assert "alg" in path.read_text()
            continue
        board: dict[str, Any] = json.loads(path.read_text())
        assert any(v["name"] == "broad" for v in board["templating"]["list"]), path.name
        assert "alg" in path.read_text(), path.name  # FR-028
