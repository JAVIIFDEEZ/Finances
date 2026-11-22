"""Port of the reference data of a whole market: its size, dominance and ranking (ADR-0045).

Not a series of one instrument but snapshots of a market (crypto): how big it is, the share
of the largest assets and which they are. A provider (CoinGecko) implements
:class:`ReferenceDataProvider` and declares ``Dataset.REFERENCE`` with the asset classes it
covers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import AssetClass
from investinglab.domain.money import USD, Currency

if TYPE_CHECKING:
    from investinglab.domain.market_reference import MarketCapRanking, MarketSnapshot
    from investinglab.ports.market_data import ProviderCapabilities

__all__ = ["MarketCapRequest", "MarketSnapshotRequest", "ReferenceDataProvider"]


@dataclass(frozen=True, slots=True)
class MarketSnapshotRequest:
    """A request for the snapshot of a whole market.

    Attributes:
        asset_class: The market (crypto).
        currency: Currency of the amounts.
    """

    asset_class: AssetClass = AssetClass.CRYPTO
    currency: Currency = field(default=USD)


@dataclass(frozen=True, slots=True)
class MarketCapRequest:
    """A request for the largest assets of a market by capitalisation.

    Attributes:
        asset_class: The market (crypto).
        currency: Currency of the prices and amounts.
        top: How many assets, from the largest.

    Raises:
        DomainError: If ``top`` is not positive.
    """

    asset_class: AssetClass = AssetClass.CRYPTO
    currency: Currency = field(default=USD)
    top: int = 100

    def __post_init__(self) -> None:
        if self.top < 1:
            raise DomainError(f"Ask for one asset or more, not {self.top}")


@runtime_checkable
class ReferenceDataProvider(Protocol):
    """Source of snapshots of whole markets."""

    @property
    def name(self) -> str:
        """Provider slug."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What the provider serves; reference data needs ``Dataset.REFERENCE``."""
        ...

    async def fetch_market_snapshot(self, request: MarketSnapshotRequest) -> MarketSnapshot:
        """The market as the source last computed it.

        Raises:
            ProviderError: With the same meaning as for price bars.
        """
        ...

    async def fetch_market_caps(self, request: MarketCapRequest) -> MarketCapRanking:
        """The ``request.top`` largest assets as the source last ranked them.

        Raises:
            ProviderError: With the same meaning as for price bars.
        """
        ...
