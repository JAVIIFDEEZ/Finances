"""The append-only audit log on PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from investinglab.ports import ChainReport, LogEntry, verify_chain
from investinglab_api.persistence.models import AuditRow

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from investinglab.ports import JsonValue
    from investinglab_api.persistence.database import Database

__all__ = ["SqlAuditLog", "append_entry"]

BATCH = 1_000


def _now() -> datetime:
    return datetime.now(UTC)


def _entry(row: AuditRow) -> LogEntry:
    return LogEntry(
        stream=row.stream,
        sequence=row.sequence,
        recorded_at=row.recorded_at,
        owner_id=row.owner_id,
        kind=row.kind,
        payload=row.payload,
        previous_hash=row.previous_hash,
        hash=row.hash,
    )


async def append_entry(
    session: AsyncSession,
    stream: str,
    kind: str,
    payload: Mapping[str, JsonValue],
    *,
    owner_id: str | None = None,
    clock: Callable[[], datetime] = _now,
) -> LogEntry:
    """Add an entry to ``stream`` inside the caller's transaction.

    The change being audited and its entry commit together, or not at all. Writers of the
    same stream wait for each other (a transaction-scoped advisory lock), so the chain never
    forks.
    """
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(stream, 0))))
    last = await session.scalar(
        select(AuditRow)
        .where(AuditRow.stream == stream)
        .order_by(AuditRow.sequence.desc())
        .limit(1)
    )
    entry = LogEntry.chained(
        None if last is None else _entry(last),
        stream=stream,
        recorded_at=clock(),
        owner_id=owner_id,
        kind=kind,
        payload=payload,
    )
    session.add(
        AuditRow(
            stream=entry.stream,
            sequence=entry.sequence,
            recorded_at=entry.recorded_at,
            owner_id=entry.owner_id,
            kind=entry.kind,
            payload=entry.payload,
            previous_hash=entry.previous_hash,
            hash=entry.hash,
        )
    )
    await session.flush()
    return entry


class SqlAuditLog:
    """:class:`investinglab.ports.AuditLog` on the ``audit_log`` table."""

    def __init__(self, database: Database, clock: Callable[[], datetime] = _now) -> None:
        self._database = database
        self._clock = clock

    async def append(
        self,
        stream: str,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        owner_id: str | None = None,
    ) -> LogEntry:
        """Add an entry at the end of ``stream`` and return it."""
        async with self._database.transaction() as session:
            return await append_entry(
                session, stream, kind, payload, owner_id=owner_id, clock=self._clock
            )

    async def read(self, stream: str, *, after: int = 0, limit: int = BATCH) -> list[LogEntry]:
        """Entries of ``stream`` with a sequence above ``after``, in order."""
        async with self._database.transaction() as session:
            rows = await session.scalars(
                select(AuditRow)
                .where(AuditRow.stream == stream, AuditRow.sequence > after)
                .order_by(AuditRow.sequence)
                .limit(limit)
            )
            return [_entry(row) for row in rows]

    async def verify(self, stream: str) -> ChainReport:
        """Check the whole chain of ``stream``, reading it in batches."""
        entries: list[LogEntry] = []
        after = 0
        while batch := await self.read(stream, after=after):
            entries.extend(batch)
            after = batch[-1].sequence
        return verify_chain(stream, entries)
