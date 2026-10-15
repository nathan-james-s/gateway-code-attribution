"""Webhook delivery dedupe (T069; FR-020): each X-GitHub-Delivery id is handled once.

Revision ID: 0003_webhook_delivery
Revises: 0002_reporting_views
"""

from alembic import op

revision = "0003_webhook_delivery"
down_revision = "0002_reporting_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE webhook_delivery (
            id TEXT PRIMARY KEY,
            event TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_webhook_delivery_received_at ON webhook_delivery (received_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_delivery")
