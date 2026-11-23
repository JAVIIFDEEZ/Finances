"""The heartbeats of the data sources (ADR-0047).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from investinglab_api.persistence import ddl

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """One row per source: its latest check, its last answer and its failures in a row.

    Global (no owner): it describes the platform, not anybody's data.
    """
    op.create_table(
        "source_heartbeats",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("checked_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_seconds", sa.Double(), nullable=False),
        sa.Column("latest_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_ok_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("provider", name="pk_source_heartbeats"),
        sa.CheckConstraint("provider <> ''", name="ck_source_heartbeats_provider_not_empty"),
        sa.CheckConstraint(
            "latency_seconds >= 0", name="ck_source_heartbeats_latency_not_negative"
        ),
        sa.CheckConstraint("failures >= 0", name="ck_source_heartbeats_failures_not_negative"),
        sa.CheckConstraint("ok = (error IS NULL)", name="ck_source_heartbeats_error_when_failed"),
        sa.CheckConstraint(
            "ok OR latest_at IS NULL", name="ck_source_heartbeats_no_latest_when_failed"
        ),
        sa.CheckConstraint(
            "NOT ok OR (failures = 0 AND last_ok_at IS NOT DISTINCT FROM checked_at)",
            name="ck_source_heartbeats_ok_resets",
        ),
    )
    op.execute(ddl.grant_to_app("source_heartbeats", "SELECT, INSERT, UPDATE"))


def downgrade() -> None:
    """Drop the heartbeats: the next checks write them again."""
    op.drop_table("source_heartbeats")
