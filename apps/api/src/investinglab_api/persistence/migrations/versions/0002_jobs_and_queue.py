"""Background jobs and the queue their workers take them from (ADR-0046).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from investinglab_api.persistence import ddl
from investinglab_api.persistence.queue import schema_sql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

QUEUE_SCHEMA = "03.11.00"
"""Procrastinate's schema this migration creates (a copy, so it never changes)."""

QUEUE_TABLES = (
    "procrastinate_jobs",
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_workers",
)
QUEUE_SEQUENCES = tuple(f"{table}_id_seq" for table in QUEUE_TABLES)

FINISHED = "('succeeded', 'failed', 'cancelled')"


def upgrade() -> None:
    """Create the jobs of each owner and the queue, both reachable by the application role."""
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("error", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("progress", sa.Double(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("queue_job_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.CheckConstraint("owner_id <> ''", name="ck_jobs_owner_not_empty"),
        sa.CheckConstraint("kind <> ''", name="ck_jobs_kind_not_empty"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_status_known",
        ),
        sa.CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 1)",
            name="ck_jobs_progress_fraction",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (result IS NOT NULL)", name="ck_jobs_result_when_succeeded"
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error IS NOT NULL)", name="ck_jobs_error_when_failed"
        ),
        sa.CheckConstraint(
            f"(status IN {FINISHED}) = (finished_at IS NOT NULL)",
            name="ck_jobs_finished_when_final",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_not_negative"),
    )
    op.create_index("ix_jobs_owner_created", "jobs", ["owner_id", "created_at", "id"])
    for statement in ddl.owner_isolation("jobs"):
        op.execute(statement)
    op.execute(ddl.grant_to_app("jobs", "SELECT, INSERT, UPDATE, DELETE"))

    # The queue: Procrastinate's own SQL, run as it is on the migration's connection (same
    # transaction). Without parameters psycopg sends it untouched: its plpgsql messages use
    # '%', which a parameterised statement would read as placeholders.
    driver = op.get_bind().connection.driver_connection
    if driver is None:  # pragma: no cover - an open migration always has its connection
        msg = "The migration has no database connection"
        raise RuntimeError(msg)
    driver.execute(schema_sql(QUEUE_SCHEMA))
    for table in QUEUE_TABLES:
        op.execute(ddl.grant_to_app(table, "SELECT, INSERT, UPDATE, DELETE"))
    for sequence in QUEUE_SEQUENCES:
        op.execute(ddl.grant_to_app(sequence, "USAGE, SELECT"))


def downgrade() -> None:
    """Drop the queue and the jobs (the jobs' audit entries stay: the log is append-only)."""
    for table in QUEUE_TABLES:
        op.execute(f"DROP TABLE {table} CASCADE")
    op.execute(
        """
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT oid::regprocedure AS signature FROM pg_proc
        WHERE proname LIKE 'procrastinate\\_%'
    LOOP
        EXECUTE 'DROP ROUTINE ' || item.signature;
    END LOOP;
END
$$;
"""
    )
    for kind in ("procrastinate_job_to_defer_v1", "procrastinate_job_event_type"):
        op.execute(f"DROP TYPE {kind}")
    op.execute("DROP TYPE procrastinate_job_status")
    op.drop_table("jobs")
