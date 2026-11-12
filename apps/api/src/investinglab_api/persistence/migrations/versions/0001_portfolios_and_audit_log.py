"""Saved portfolios and the append-only audit log.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from investinglab_api.persistence import ddl

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tables with their database-level guarantees."""
    op.execute(ddl.CREATE_APP_ROLE)
    op.execute(ddl.CREATE_FORBID_CHANGES)
    # The application reads the schema revision to report whether it is up to date.
    op.execute(ddl.grant_to_app("alembic_version", "SELECT"))

    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_portfolios"),
        sa.UniqueConstraint("owner_id", "name", name="uq_portfolios_owner_id_name"),
        sa.CheckConstraint("owner_id <> ''", name="ck_portfolios_owner_not_empty"),
        sa.CheckConstraint("name <> ''", name="ck_portfolios_name_not_empty"),
        sa.CheckConstraint("version >= 1", name="ck_portfolios_version_positive"),
    )
    op.create_index("ix_portfolios_owner_updated", "portfolios", ["owner_id", "updated_at", "id"])
    for statement in ddl.owner_isolation("portfolios"):
        op.execute(statement)
    op.execute(ddl.grant_to_app("portfolios", "SELECT, INSERT, UPDATE, DELETE"))

    op.create_table(
        "audit_log",
        sa.Column("stream", sa.Text(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("recorded_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("stream", "sequence", name="pk_audit_log"),
        sa.CheckConstraint("sequence >= 1", name="ck_audit_log_sequence_positive"),
    )
    for statement in ddl.append_only("audit_log"):
        op.execute(statement)
    op.execute(ddl.grant_to_app("audit_log", "SELECT, INSERT"))


def downgrade() -> None:
    """Drop the tables (the application role stays: other databases may use it)."""
    op.drop_table("audit_log")
    op.drop_table("portfolios")
    op.execute(f"DROP FUNCTION {ddl.FORBID_CHANGES_FUNCTION}()")
