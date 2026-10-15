"""Helm settings reach portal_settings without undoing what an admin set since (gca_core.bootstrap)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.bootstrap import apply_settings

HELM = {
    "per_developer_enabled": True,
    "visible_roles": ["admin", "team_lead"],
    "matching_window_days": 14,
    "retention_days": 90,
    "exclusion_rules": ["**/*.lock"],
}


@pytest.fixture
def settings(pg_engine: Engine) -> Iterator[None]:
    cols = "per_developer_enabled, visible_roles, matching_window_days, retention_days, exclusion_rules, helm_values"
    with pg_engine.connect() as conn:
        saved = conn.execute(text(f"SELECT {cols} FROM portal_settings WHERE id = 1")).mappings().one()
    yield
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE portal_settings SET per_developer_enabled = :per_developer_enabled, "
                "visible_roles = :visible_roles, matching_window_days = :matching_window_days, "
                "retention_days = :retention_days, exclusion_rules = :exclusion_rules, "
                "helm_values = CAST(:h AS jsonb) WHERE id = 1"
            ),
            {
                **saved,
                "h": None if saved["helm_values"] is None else json.dumps(saved["helm_values"]),
            },
        )


def _row(engine: Engine) -> dict[str, object]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT per_developer_enabled, visible_roles, matching_window_days, retention_days, "
                    "exclusion_rules FROM portal_settings WHERE id = 1"
                )
            )
            .mappings()
            .one()
        )


def test_changed_helm_values_apply_and_admin_edits_survive(pg_engine: Engine, settings: None) -> None:
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE portal_settings SET helm_values = NULL WHERE id = 1"))
        assert apply_settings(conn, HELM) == list(HELM)  # first install: everything
        assert apply_settings(conn, HELM) == []  # an upgrade with the same values changes nothing
        # An admin turns per-developer views off and lengthens the window on the settings page.
        conn.execute(
            text("UPDATE portal_settings SET per_developer_enabled = false, matching_window_days = 30")
        )
        # The adopter's next upgrade changes only retention in their Helm values.
        assert apply_settings(conn, {**HELM, "retention_days": 180}) == ["retention_days"]
    row = _row(pg_engine)
    assert row["per_developer_enabled"] is False and row["matching_window_days"] == 30  # admin edits kept
    assert row["retention_days"] == 180
    # Unknown keys are ignored, never written.
    with pg_engine.begin() as conn:
        assert apply_settings(conn, {**HELM, "retention_days": 180, "id": 2, "drop": "x"}) == []
