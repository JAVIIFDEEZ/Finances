"""In-memory repositories: the reference behaviour the relational ones must match.

They hold everything in dictionaries, so they are for tests and for trying the use cases
without a database. Both pass the same contract tests as the SQL implementations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from investinglab.ports import (
    ChainReport,
    DuplicateNameError,
    LogEntry,
    Page,
    PortfolioSpec,
    RecordNotFoundError,
    Stored,
    VersionConflictError,
    decode_cursor,
    encode_cursor,
    verify_chain,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from investinglab.ports import JsonValue

__all__ = ["PORTFOLIO_STREAM", "InMemoryAuditLog", "InMemoryPortfolioRepository"]

PORTFOLIO_STREAM = "portfolios"


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryAuditLog:
    """Hash-chained streams kept in memory."""

    def __init__(self, clock: Callable[[], datetime] = _now) -> None:
        self._clock = clock
        self.streams: dict[str, list[LogEntry]] = {}

    async def append(
        self,
        stream: str,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        owner_id: str | None = None,
    ) -> LogEntry:
        entries = self.streams.setdefault(stream, [])
        entry = LogEntry.chained(
            entries[-1] if entries else None,
            stream=stream,
            recorded_at=self._clock(),
            owner_id=owner_id,
            kind=kind,
            payload=payload,
        )
        entries.append(entry)
        return entry

    async def read(self, stream: str, *, after: int = 0, limit: int = 1_000) -> list[LogEntry]:
        entries = [e for e in self.streams.get(stream, []) if e.sequence > after]
        return entries[:limit]

    async def verify(self, stream: str) -> ChainReport:
        return verify_chain(stream, self.streams.get(stream, []))


class InMemoryPortfolioRepository:
    """Saved portfolios kept in memory, with the audit trail of every change."""

    def __init__(
        self, audit: InMemoryAuditLog | None = None, clock: Callable[[], datetime] = _now
    ) -> None:
        self._clock = clock
        self.audit = audit or InMemoryAuditLog(clock)
        self._records: dict[UUID, Stored[PortfolioSpec]] = {}

    def _owned(self, owner: str, portfolio_id: UUID) -> Stored[PortfolioSpec]:
        record = self._records.get(portfolio_id)
        if record is None or record.owner_id != owner:
            raise RecordNotFoundError(f"No portfolio {portfolio_id}")
        return record

    def _check_name(self, owner: str, name: str, *, ignore: UUID | None = None) -> None:
        for record in self._records.values():
            if record.owner_id == owner and record.value.name == name and record.id != ignore:
                raise DuplicateNameError(f"A portfolio named {name!r} already exists")

    async def _log(self, kind: str, record: Stored[PortfolioSpec]) -> None:
        payload: dict[str, JsonValue] = {
            "id": str(record.id),
            "name": record.value.name,
            "version": record.version,
        }
        await self.audit.append(
            PORTFOLIO_STREAM, f"portfolio.{kind}", payload, owner_id=record.owner_id
        )

    async def add(self, owner: str, spec: PortfolioSpec) -> Stored[PortfolioSpec]:
        self._check_name(owner, spec.name)
        now = self._clock()
        record = Stored(uuid4(), owner, 1, now, now, spec)
        self._records[record.id] = record
        await self._log("created", record)
        return record

    async def get(self, owner: str, portfolio_id: UUID) -> Stored[PortfolioSpec]:
        return self._owned(owner, portfolio_id)

    async def list(
        self, owner: str, *, limit: int = 50, cursor: str | None = None
    ) -> Page[Stored[PortfolioSpec]]:
        records = sorted(
            (r for r in self._records.values() if r.owner_id == owner),
            key=lambda r: (r.updated_at, r.id),
            reverse=True,
        )
        if cursor is not None:
            position = decode_cursor(cursor)
            records = [r for r in records if (r.updated_at, r.id) < position]
        page = records[:limit]
        more = len(records) > limit
        last = page[-1] if page else None
        next_cursor = encode_cursor(last.updated_at, last.id) if more and last else None
        return Page(tuple(page), next_cursor)

    async def replace(
        self, owner: str, portfolio_id: UUID, spec: PortfolioSpec, *, expected_version: int
    ) -> Stored[PortfolioSpec]:
        current = self._owned(owner, portfolio_id)
        if current.version != expected_version:
            raise VersionConflictError(current.version)
        self._check_name(owner, spec.name, ignore=portfolio_id)
        record = Stored(
            current.id, owner, current.version + 1, current.created_at, self._clock(), spec
        )
        self._records[record.id] = record
        await self._log("replaced", record)
        return record

    async def remove(self, owner: str, portfolio_id: UUID, *, expected_version: int) -> None:
        current = self._owned(owner, portfolio_id)
        if current.version != expected_version:
            raise VersionConflictError(current.version)
        del self._records[portfolio_id]
        await self._log("removed", current)
