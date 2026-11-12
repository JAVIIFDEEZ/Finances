"""Saved portfolios on PostgreSQL."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_, update
from sqlalchemy.exc import IntegrityError

from investinglab.domain.portfolio import RebalanceKind, RebalancePolicy
from investinglab.domain.time import Frequency
from investinglab.ports import (
    DuplicateNameError,
    Page,
    PortfolioSpec,
    RecordNotFoundError,
    Stored,
    VersionConflictError,
    decode_cursor,
    encode_cursor,
)
from investinglab_api.persistence.audit import append_entry
from investinglab_api.persistence.models import PortfolioRow

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from investinglab.ports import JsonValue
    from investinglab_api.persistence.database import Database

__all__ = [
    "PORTFOLIO_STREAM",
    "SqlPortfolioRepository",
    "definition_of",
    "name_taken",
    "spec_of",
]

PORTFOLIO_STREAM: Final = "portfolios"
DEFINITION_SCHEMA: Final = 1


def _now() -> datetime:
    return datetime.now(UTC)


def definition_of(spec: PortfolioSpec) -> dict[str, Any]:
    """The JSON document stored for a portfolio (its name has a column of its own)."""
    return {
        "schema": DEFINITION_SCHEMA,
        "holdings": [{"symbol": symbol, "weight": weight} for symbol, weight in spec.weights],
        "base_currency": spec.base_currency,
        "rebalance": {
            "kind": spec.rebalance.kind.value,
            "frequency": None
            if spec.rebalance.frequency is None
            else spec.rebalance.frequency.value,
            "band": spec.rebalance.band,
        },
        "allow_short": spec.allow_short,
        "start": None if spec.start is None else spec.start.isoformat(),
        "end": None if spec.end is None else spec.end.isoformat(),
        "frequency": spec.frequency.value,
    }


def spec_of(name: str, definition: dict[str, Any]) -> PortfolioSpec:
    """The portfolio a stored document describes."""
    rebalance = definition["rebalance"]
    frequency = rebalance["frequency"]
    return PortfolioSpec(
        name=name,
        weights=tuple((item["symbol"], float(item["weight"])) for item in definition["holdings"]),
        base_currency=definition["base_currency"],
        rebalance=RebalancePolicy(
            RebalanceKind(rebalance["kind"]),
            frequency=None if frequency is None else Frequency(frequency),
            band=rebalance["band"],
        ),
        allow_short=definition["allow_short"],
        start=None if definition["start"] is None else date.fromisoformat(definition["start"]),
        end=None if definition["end"] is None else date.fromisoformat(definition["end"]),
        frequency=Frequency(definition["frequency"]),
    )


def _stored(row: PortfolioRow) -> Stored[PortfolioSpec]:
    return Stored(
        id=row.id,
        owner_id=row.owner_id,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        value=spec_of(row.name, row.definition),
    )


class SqlPortfolioRepository:
    """:class:`investinglab.ports.PortfolioRepository` on the ``portfolios`` table.

    Every statement filters by owner, and every transaction also tells the database who the
    owner is, so its row-level security enforces the same rule a second time.
    """

    def __init__(self, database: Database, clock: Callable[[], datetime] = _now) -> None:
        self._database = database
        self._clock = clock

    async def _audit(self, session: AsyncSession, kind: str, row: PortfolioRow) -> None:
        payload: dict[str, JsonValue] = {
            "id": str(row.id),
            "name": row.name,
            "version": row.version,
        }
        await append_entry(
            session,
            PORTFOLIO_STREAM,
            f"portfolio.{kind}",
            payload,
            owner_id=row.owner_id,
            clock=self._clock,
        )

    async def _version(self, session: AsyncSession, owner: str, portfolio_id: UUID) -> int:
        version = await session.scalar(
            select(PortfolioRow.version).where(
                PortfolioRow.owner_id == owner, PortfolioRow.id == portfolio_id
            )
        )
        if version is None:
            raise RecordNotFoundError(f"No portfolio {portfolio_id}")
        return version

    async def add(self, owner: str, spec: PortfolioSpec) -> Stored[PortfolioSpec]:
        """Save a new portfolio."""
        now = self._clock()
        row = PortfolioRow(
            id=uuid4(),
            owner_id=owner,
            name=spec.name,
            definition=definition_of(spec),
            version=1,
            created_at=now,
            updated_at=now,
        )
        async with self._database.transaction(owner) as session:
            session.add(row)
            try:
                await session.flush()
            except IntegrityError as error:
                raise name_taken(spec.name, error) from error
            await self._audit(session, "created", row)
            return _stored(row)

    async def get(self, owner: str, portfolio_id: UUID) -> Stored[PortfolioSpec]:
        """One portfolio of the owner."""
        async with self._database.transaction(owner) as session:
            row = await session.scalar(
                select(PortfolioRow).where(
                    PortfolioRow.owner_id == owner, PortfolioRow.id == portfolio_id
                )
            )
            if row is None:
                raise RecordNotFoundError(f"No portfolio {portfolio_id}")
            return _stored(row)

    async def list(
        self, owner: str, *, limit: int = 50, cursor: str | None = None
    ) -> Page[Stored[PortfolioSpec]]:
        """The owner's portfolios, most recently updated first."""
        query = select(PortfolioRow).where(PortfolioRow.owner_id == owner)
        if cursor is not None:
            query = query.where(
                tuple_(PortfolioRow.updated_at, PortfolioRow.id) < decode_cursor(cursor)
            )
        query = query.order_by(PortfolioRow.updated_at.desc(), PortfolioRow.id.desc())
        async with self._database.transaction(owner) as session:
            rows = list(await session.scalars(query.limit(limit + 1)))
        page = rows[:limit]
        more = len(rows) > limit
        next_cursor = encode_cursor(page[-1].updated_at, page[-1].id) if more and page else None
        return Page(tuple(_stored(row) for row in page), next_cursor)

    async def replace(
        self, owner: str, portfolio_id: UUID, spec: PortfolioSpec, *, expected_version: int
    ) -> Stored[PortfolioSpec]:
        """Replace a portfolio the caller read at ``expected_version``."""
        statement = (
            update(PortfolioRow)
            .where(
                PortfolioRow.owner_id == owner,
                PortfolioRow.id == portfolio_id,
                PortfolioRow.version == expected_version,
            )
            .values(
                name=spec.name,
                definition=definition_of(spec),
                version=PortfolioRow.version + 1,
                updated_at=self._clock(),
            )
            .returning(PortfolioRow)
        )
        async with self._database.transaction(owner) as session:
            try:
                row = await session.scalar(statement)
            except IntegrityError as error:
                raise name_taken(spec.name, error) from error
            if row is None:
                raise VersionConflictError(await self._version(session, owner, portfolio_id))
            await self._audit(session, "replaced", row)
            return _stored(row)

    async def remove(self, owner: str, portfolio_id: UUID, *, expected_version: int) -> None:
        """Delete a portfolio the caller read at ``expected_version``."""
        async with self._database.transaction(owner) as session:
            row = await session.scalar(
                select(PortfolioRow)
                .where(PortfolioRow.owner_id == owner, PortfolioRow.id == portfolio_id)
                .with_for_update()
            )
            if row is None:
                raise RecordNotFoundError(f"No portfolio {portfolio_id}")
            if row.version != expected_version:
                raise VersionConflictError(row.version)
            await session.delete(row)
            await self._audit(session, "removed", row)


def name_taken(name: str, error: IntegrityError) -> Exception:
    """The error to raise for a failed write: a name conflict, or the error itself."""
    constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if constraint == "uq_portfolios_owner_id_name":
        return DuplicateNameError(f"A portfolio named {name!r} already exists")
    return error
