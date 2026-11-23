"""The heartbeats of the data sources on PostgreSQL (ADR-0047): one row per source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert

from investinglab.domain.heartbeat import SourceHeartbeat, SourceStatus
from investinglab_api.persistence.models import SourceHeartbeatRow

if TYPE_CHECKING:
    from investinglab_api.persistence.database import Database

__all__ = ["SqlHeartbeatStore", "status_of"]


def status_of(row: SourceHeartbeatRow) -> SourceStatus:
    """The status a row holds."""
    heartbeat = SourceHeartbeat(
        provider=row.provider,
        checked_at=row.checked_at,
        ok=row.ok,
        latency=row.latency_seconds,
        latest=row.latest_at,
        error=row.error,
    )
    return SourceStatus(heartbeat, row.last_ok_at, row.failures)


class SqlHeartbeatStore:
    """:class:`investinglab.ports.HeartbeatStore` on the ``source_heartbeats`` table.

    Recording is one ``INSERT … ON CONFLICT`` that carries the history on in the database
    itself: an answer resets the failures and moves the last answer, a failure adds one.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def record(self, heartbeat: SourceHeartbeat) -> SourceStatus:
        """Keep a check and return the source's status after it."""
        first = SourceStatus.first(heartbeat)
        values = {
            "provider": heartbeat.provider,
            "checked_at": heartbeat.checked_at,
            "ok": heartbeat.ok,
            "latency_seconds": heartbeat.latency,
            "latest_at": heartbeat.latest,
            "error": heartbeat.error,
            "last_ok_at": first.last_ok_at,
            "failures": first.failures,
        }
        statement = insert(SourceHeartbeatRow).values(values)
        new = statement.excluded
        upsert = statement.on_conflict_do_update(
            index_elements=[SourceHeartbeatRow.provider],
            set_={
                "checked_at": new.checked_at,
                "ok": new.ok,
                "latency_seconds": new.latency_seconds,
                "latest_at": new.latest_at,
                "error": new.error,
                "last_ok_at": case((new.ok, new.checked_at), else_=SourceHeartbeatRow.last_ok_at),
                "failures": case((new.ok, 0), else_=SourceHeartbeatRow.failures + 1),
            },
        ).returning(SourceHeartbeatRow)
        async with self._database.transaction() as session:
            row = await session.scalar(upsert)
            if row is None:  # pragma: no cover - an upsert always returns its row
                msg = f"The heartbeat of {heartbeat.provider} was not kept"
                raise RuntimeError(msg)
            return status_of(row)

    async def statuses(self) -> tuple[SourceStatus, ...]:
        """The status of every source checked, by name."""
        async with self._database.transaction() as session:
            rows = await session.scalars(
                select(SourceHeartbeatRow).order_by(SourceHeartbeatRow.provider)
            )
            return tuple(status_of(row) for row in rows)
