"""Reference data of a whole market: its size, who dominates it and its ranking (ADR-0045).

How big the crypto market is, how much of it is bitcoin and which assets are the largest
are *snapshots*: the state at one instant, as the source computed it. Sources that publish
them for free (CoinGecko) keep no history of them, so they are never stretched back into a
series: a snapshot carries the instant it describes, and a study that needs them over time
has to collect them as they come (G0b, G8).

* :class:`MarketSnapshot`: total capitalisation and volume of an asset class, its 24-hour
  change, how many assets it counts and the share of the largest ones.
* :class:`MarketCapRanking`: the largest assets by capitalisation, with their price, supply
  and when each figure was last updated.

Nothing is filled in: a figure the source does not give is ``None``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from investinglab.domain.instruments import AssetClass
    from investinglab.domain.money import Currency
    from investinglab.domain.series import DataSource

__all__ = ["MarketCapRanking", "MarketShare", "MarketSnapshot", "RankedAsset"]

_SHARE_TOLERANCE: Final = 1e-6
"""Rounding the source may leave in shares that add up to the whole."""


def _aware(moment: datetime, what: str) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise DomainError(f"{what} is an instant: it needs a timezone")


def _amount(value: float | None, what: str, *, positive: bool = False) -> None:
    if value is None:
        return
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        bound = "positive" if positive else "zero or more"
        raise DomainError(f"{what} must be a finite amount, {bound}; got {value}")


@dataclass(frozen=True, slots=True)
class MarketShare:
    """The share of a market's capitalisation one asset holds.

    Attributes:
        symbol: The asset's ticker, in capitals (``BTC``).
        share: Its share of the total, from 0 to 1.
    """

    symbol: str
    share: float

    def __post_init__(self) -> None:
        if not self.symbol.strip() or self.symbol != self.symbol.upper():
            raise DomainError(f"A share needs a ticker in capitals, got {self.symbol!r}")
        if not math.isfinite(self.share) or not 0 <= self.share <= 1:
            raise DomainError(f"{self.symbol}: a share is between 0 and 1, got {self.share}")


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """The whole market of an asset class at one instant.

    Attributes:
        asset_class: The market described (crypto).
        currency: Currency of the amounts.
        as_of: The instant the source computed it.
        source: Provenance (provider and download time).
        total_market_cap: Capitalisation of every asset the source tracks.
        total_volume_24h: Volume traded in the last 24 hours, if given.
        market_cap_change_24h: Relative change of the capitalisation in 24 hours, if given.
        assets: How many assets the source tracks, if given.
        dominance: The share of the largest assets the source publishes, largest first.

    Raises:
        DomainError: If an amount is not finite and non-negative, a share is outside [0, 1],
            the shares add up to more than the whole or ``as_of`` has no timezone.
    """

    asset_class: AssetClass
    currency: Currency
    as_of: datetime
    source: DataSource
    total_market_cap: float
    total_volume_24h: float | None = None
    market_cap_change_24h: float | None = None
    assets: int | None = None
    dominance: tuple[MarketShare, ...] = field(default=())

    def __post_init__(self) -> None:
        _aware(self.as_of, "A snapshot's time")
        _amount(self.total_market_cap, "The total capitalisation", positive=True)
        _amount(self.total_volume_24h, "The volume")
        change = self.market_cap_change_24h
        if change is not None and (not math.isfinite(change) or change <= -1):
            raise DomainError(f"A 24-hour change is above -100 %, got {change}")
        if self.assets is not None and self.assets < 0:
            raise DomainError(f"A count of assets cannot be negative, got {self.assets}")
        symbols = [item.symbol for item in self.dominance]
        if len(set(symbols)) != len(symbols):
            raise DomainError(f"An asset appears twice in the dominance: {symbols}")
        if sum(item.share for item in self.dominance) > 1 + _SHARE_TOLERANCE:
            raise DomainError("The shares of the largest assets add up to more than the whole")
        ordered = tuple(sorted(self.dominance, key=lambda item: -item.share))
        object.__setattr__(self, "dominance", ordered)

    def share_of(self, symbol: str) -> float | None:
        """The share of ``symbol`` (``BTC``), or ``None`` if the source does not give it."""
        return next((item.share for item in self.dominance if item.symbol == symbol), None)

    @property
    def others(self) -> float:
        """The share of every asset outside :attr:`dominance`."""
        return max(0.0, 1.0 - sum(item.share for item in self.dominance))


@dataclass(frozen=True, slots=True)
class RankedAsset:
    """One asset of a ranking by capitalisation.

    Attributes:
        rank: Its position in the ranking, from 1.
        id: The source's identifier (``bitcoin``).
        symbol: Its ticker, in capitals (``BTC``).
        name: Its name.
        price: Its price, if given.
        market_cap: Its capitalisation, if given.
        volume_24h: Volume traded in the last 24 hours, if given.
        circulating_supply: Units in circulation, if given.
        max_supply: Most units there will ever be, if capped and given.
        updated: When the source last updated these figures, if given.
    """

    rank: int
    id: str
    symbol: str
    name: str
    price: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    circulating_supply: float | None = None
    max_supply: float | None = None
    updated: datetime | None = None

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise DomainError(f"A rank starts at 1, got {self.rank}")
        for text, what in ((self.id, "an id"), (self.symbol, "a ticker"), (self.name, "a name")):
            if not text.strip():
                raise DomainError(f"A ranked asset needs {what}")
        if self.symbol != self.symbol.upper():
            raise DomainError(f"Tickers are in capitals, got {self.symbol!r}")
        for value, what in (
            (self.price, "price"),
            (self.market_cap, "capitalisation"),
            (self.volume_24h, "volume"),
            (self.circulating_supply, "circulating supply"),
            (self.max_supply, "maximum supply"),
        ):
            _amount(value, f"{self.symbol}'s {what}")
        if self.updated is not None:
            _aware(self.updated, f"{self.symbol}'s update time")


@dataclass(frozen=True, slots=True)
class MarketCapRanking:
    """The largest assets of a market by capitalisation, at one instant.

    Attributes:
        asset_class: The market ranked (crypto).
        currency: Currency of the prices and amounts.
        as_of: When the ranking was read.
        source: Provenance (provider and download time).
        assets: The assets, by rank.

    Raises:
        DomainError: If it is empty, ranks repeat or are out of order, an asset appears
            twice or ``as_of`` has no timezone.
    """

    asset_class: AssetClass
    currency: Currency
    as_of: datetime
    source: DataSource
    assets: tuple[RankedAsset, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, "A ranking's time")
        if not self.assets:
            raise DomainError("A ranking needs at least one asset")
        ranks = [asset.rank for asset in self.assets]
        if any(later <= earlier for earlier, later in pairwise(ranks)):
            raise DomainError(f"Ranks must increase without repeating, got {ranks}")
        ids = [asset.id for asset in self.assets]
        if len(set(ids)) != len(ids):
            raise DomainError("An asset appears twice in the ranking")

    def __len__(self) -> int:
        return len(self.assets)

    def top(self, count: int) -> MarketCapRanking:
        """The first ``count`` assets.

        Raises:
            DomainError: If ``count`` is not positive.
        """
        if count < 1:
            raise DomainError(f"Ask for one asset or more, not {count}")
        return MarketCapRanking(
            self.asset_class, self.currency, self.as_of, self.source, self.assets[:count]
        )

    def find(self, symbol: str) -> RankedAsset | None:
        """The asset with ticker ``symbol`` (the best ranked, if several share it)."""
        return next((asset for asset in self.assets if asset.symbol == symbol.upper()), None)

    def frame(self) -> pd.DataFrame:
        """The ranking as a table indexed by rank; missing figures are ``NaN``."""
        rows: Iterable[dict[str, object]] = (
            {
                "rank": asset.rank,
                "id": asset.id,
                "symbol": asset.symbol,
                "name": asset.name,
                "price": asset.price,
                "market_cap": asset.market_cap,
                "volume_24h": asset.volume_24h,
                "circulating_supply": asset.circulating_supply,
                "max_supply": asset.max_supply,
                "updated": asset.updated,
            }
            for asset in self.assets
        )
        return pd.DataFrame(list(rows)).set_index("rank")
