"""Repositories: where the state that belongs to a user lives.

The core only knows these contracts. A relational implementation lives in the API
(``investinglab_api.persistence``) and an in-memory one in the tests; both pass the same
contract tests.

Two rules hold for every repository:

* **Everything has an owner.** Every method takes the owner first, and a record of another
  owner does not exist for the caller: it is not found, never forbidden.
* **Writes are optimistic.** A record carries a version; replacing or removing it needs the
  version the caller saw, and fails with :class:`VersionConflictError` if it has changed.
"""

from __future__ import annotations

import base64
import binascii
import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from investinglab.domain.errors import DomainError
from investinglab.domain.portfolio import RebalancePolicy
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from datetime import date

__all__ = [
    "DuplicateNameError",
    "Page",
    "PortfolioRepository",
    "PortfolioSpec",
    "RecordNotFoundError",
    "RepositoryError",
    "RepositoryUnavailableError",
    "Stored",
    "VersionConflictError",
    "decode_cursor",
    "encode_cursor",
]

MAX_NAME_LENGTH = 80


class RepositoryError(Exception):
    """Base of the failures of a repository."""


class RecordNotFoundError(RepositoryError):
    """The owner has no such record (or it belongs to someone else)."""


class VersionConflictError(RepositoryError):
    """The record changed since the caller read it.

    Attributes:
        current_version: Version the record has now.
    """

    def __init__(self, current_version: int) -> None:
        super().__init__(f"The record is now at version {current_version}")
        self.current_version = current_version


class DuplicateNameError(RepositoryError):
    """The owner already has a record with that name."""


class RepositoryUnavailableError(RepositoryError):
    """The store cannot be reached right now."""


@dataclass(frozen=True, slots=True)
class PortfolioSpec:
    """A portfolio as its owner defines it: what to hold, not what it is worth.

    It is everything needed to build the portfolio again from market data.

    Attributes:
        name: Name the owner gives it (unique among their portfolios).
        weights: Target weight of each symbol, in the owner's order.
        base_currency: Valuation currency (ISO 4217), or ``None`` for the holdings' own.
        rebalance: Rebalancing rule.
        allow_short: Whether negative weights are intended.
        start: First session of the history to analyse, if bounded.
        end: Last session of the history to analyse, if bounded.
        frequency: Frequency of the bars to analyse.
    """

    name: str
    weights: tuple[tuple[str, float], ...]
    base_currency: str | None = None
    rebalance: RebalancePolicy = RebalancePolicy.periodic()  # noqa: RUF009 - frozen value
    allow_short: bool = False
    start: date | None = None
    end: date | None = None
    frequency: Frequency = Frequency.DAY_1

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise DomainError(f"A portfolio name takes 1 to {MAX_NAME_LENGTH} characters")
        object.__setattr__(self, "name", name)
        if not self.weights:
            raise DomainError("A portfolio needs at least one holding")
        symbols = [symbol for symbol, _ in self.weights]
        if len(set(symbols)) != len(symbols) or not all(symbols):
            raise DomainError("Holdings need distinct, non-empty symbols")
        if not all(math.isfinite(weight) for _, weight in self.weights):
            raise DomainError("Weights must be finite")
        if self.start and self.end and self.start > self.end:
            raise DomainError(f"start {self.start} is after end {self.end}")


@dataclass(frozen=True, slots=True)
class Stored[T]:
    """A record of a repository: a value with its identity, owner and version.

    Attributes:
        id: Identifier, assigned when the record is added.
        owner_id: Owner of the record.
        version: 1 when added; one more after every replacement.
        created_at: Instant the record was added.
        updated_at: Instant of its last replacement.
        value: The value stored.
    """

    id: UUID
    owner_id: str
    version: int
    created_at: datetime
    updated_at: datetime
    value: T


@dataclass(frozen=True, slots=True)
class Page[T]:
    """A page of a listing.

    Attributes:
        items: Records of the page.
        next_cursor: Pass it back to get the next page; ``None`` on the last one.
    """

    items: tuple[T, ...]
    next_cursor: str | None = None


def encode_cursor(updated_at: datetime, record_id: UUID) -> str:
    """Opaque cursor of the record a page ends at (listings go newest first)."""
    raw = f"{updated_at.isoformat()}|{record_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """The position a cursor of :func:`encode_cursor` points at.

    Raises:
        DomainError: The text is not a cursor.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        moment, _, record_id = raw.partition("|")
        position = datetime.fromisoformat(moment), UUID(record_id)
    except (ValueError, binascii.Error) as error:
        raise DomainError("The cursor does not come from a previous page") from error
    if position[0].tzinfo is None:
        raise DomainError("The cursor does not come from a previous page")
    return position


@runtime_checkable
class PortfolioRepository(Protocol):
    """The portfolios each owner has saved."""

    async def add(self, owner: str, spec: PortfolioSpec) -> Stored[PortfolioSpec]:
        """Save a new portfolio.

        Raises:
            DuplicateNameError: The owner already has a portfolio with that name.
        """
        ...

    async def get(self, owner: str, portfolio_id: UUID) -> Stored[PortfolioSpec]:
        """One portfolio of the owner.

        Raises:
            RecordNotFoundError: The owner has no such portfolio.
        """
        ...

    async def list(
        self, owner: str, *, limit: int = 50, cursor: str | None = None
    ) -> Page[Stored[PortfolioSpec]]:
        """The owner's portfolios, most recently updated first.

        Raises:
            DomainError: ``cursor`` does not come from a previous page.
        """
        ...

    async def replace(
        self, owner: str, portfolio_id: UUID, spec: PortfolioSpec, *, expected_version: int
    ) -> Stored[PortfolioSpec]:
        """Replace a portfolio the caller read at ``expected_version``.

        Raises:
            RecordNotFoundError: The owner has no such portfolio.
            VersionConflictError: It has changed since.
            DuplicateNameError: The owner has another portfolio with the new name.
        """
        ...

    async def remove(self, owner: str, portfolio_id: UUID, *, expected_version: int) -> None:
        """Delete a portfolio the caller read at ``expected_version``.

        Raises:
            RecordNotFoundError: The owner has no such portfolio.
            VersionConflictError: It has changed since.
        """
        ...
