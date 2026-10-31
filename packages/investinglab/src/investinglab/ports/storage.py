"""Port for the market-data cache."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.series import PriceSeries
    from investinglab.ports.market_data import BarsRequest, EconomicRequest

__all__ = ["CachedBars", "CachedEconomicSeries", "SeriesStore"]


@dataclass(frozen=True, slots=True)
class CachedBars:
    """A cached price series and the request it was downloaded for.

    Attributes:
        series: The cached series.
        coverage: Request whose answer was stored; it determines which later requests
            the entry can answer (see :meth:`BarsRequest.covers`).
        stored_at: When the entry was written (timezone-aware).
    """

    series: PriceSeries
    coverage: BarsRequest
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class CachedEconomicSeries:
    """A cached economic series and the request it was downloaded for."""

    series: EconomicSeries
    coverage: EconomicRequest
    stored_at: datetime


@runtime_checkable
class SeriesStore(Protocol):
    """Persistent cache of downloaded series (one entry per symbol and frequency)."""

    def load_bars(self, request: BarsRequest) -> CachedBars | None:
        """Return the cached entry for the request's symbol and frequency, if any."""
        ...

    def save_bars(self, series: PriceSeries, coverage: BarsRequest) -> None:
        """Store a series downloaded for ``coverage``, replacing any previous entry."""
        ...

    def load_economic(self, request: EconomicRequest) -> CachedEconomicSeries | None:
        """Return the cached entry for the request's series id, if any."""
        ...

    def save_economic(self, series: EconomicSeries, coverage: EconomicRequest) -> None:
        """Store an economic series downloaded for ``coverage``."""
        ...
