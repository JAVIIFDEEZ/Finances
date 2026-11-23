"""The queue the workers take jobs from: Procrastinate on the same PostgreSQL (ADR-0046).

The ``jobs`` table is what each owner sees; Procrastinate's tables are how a worker learns
that there is something to run. Both live in the same database, so a job and its place in
the queue are written in one transaction
(:class:`~investinglab_api.persistence.jobs.SqlJobRepository`).

**Upgrading Procrastinate.** Its schema is created by migration 0002 from a copy of its SQL
(:data:`SCHEMA_VERSION`). A release whose ``sql/migrations`` folder has files after that
version needs a new Alembic migration that runs them, in order; a test fails until then.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import make_url

from investinglab_api.persistence.models import QUEUE_PREFIX, is_queue_object

if TYPE_CHECKING:
    from procrastinate import App

__all__ = [
    "QUEUE",
    "QUEUE_PREFIX",
    "RUN_JOB",
    "SCHEMA_VERSION",
    "conninfo",
    "is_queue_object",
    "pending_schema_migrations",
    "queue_app",
    "schema_sql",
]

QUEUE: Final = "jobs"
"""Queue of the jobs owners submit."""

RUN_JOB: Final = "investinglab.run_job"
"""Task every job is run through; its arguments are the job and its owner, nothing else."""

SCHEMA_VERSION: Final = "03.11.00"
"""Last schema migration of Procrastinate that our migrations have applied."""

_SQL = Path(__file__).parent / "migrations" / "sql"


def conninfo(url: str) -> str:
    """The libpq form of a SQLAlchemy URL (``postgresql+psycopg://`` → ``postgresql://``)."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def queue_app(url: str) -> App:
    """Procrastinate's application on the database at ``url``.

    Building it opens nothing: the API only defers jobs on its own transaction's connection,
    and the worker opens the connection pool when it starts. Procrastinate is imported here,
    not with the module, so that migrating the database does not load it.
    """
    from procrastinate import App, PsycopgConnector  # noqa: PLC0415 - see above

    return App(connector=PsycopgConnector(conninfo=conninfo(url)))


def schema_sql(version: str = SCHEMA_VERSION) -> str:
    """The SQL that creates Procrastinate's schema at ``version`` (copied, never edited)."""
    return (_SQL / f"procrastinate_{version}.sql").read_text(encoding="utf-8")


def pending_schema_migrations() -> list[str]:
    """Schema migrations of the installed Procrastinate newer than :data:`SCHEMA_VERSION`."""
    folder = resources.files("procrastinate.sql") / "migrations"
    return sorted(
        entry.name
        for entry in folder.iterdir()
        if entry.name.endswith(".sql") and entry.name[:8] > SCHEMA_VERSION
    )
