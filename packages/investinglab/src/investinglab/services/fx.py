"""Currency use cases: obtain FX fixings and convert series to a base currency (ADR-0014)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from investinglab.domain.fx import DEFAULT_MAX_STALENESS, FxRates
from investinglab.domain.instruments import AssetClass
from investinglab.domain.money import CurrencyPair
from investinglab.domain.time import Frequency
from investinglab.ports.market_data import BarsRequest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import date

    import pandas as pd

    from investinglab.domain.money import Currency
    from investinglab.domain.series import PriceSeries
    from investinglab.services.market_data import MarketDataService

__all__ = ["CurrencyService", "yahoo_style_fx_symbol"]

_LOOKBACK = timedelta(days=10)
"""Fixings fetched before a series' first date so its first prices can be converted."""


def yahoo_style_fx_symbol(pair: CurrencyPair) -> str:
    """Canonical InvestingLab symbol of an FX pair (``EURUSD=X``)."""
    return f"{pair.symbol}=X"


class CurrencyService:
    """Fetches FX fixings through the market-data service and converts series.

    Args:
        market_data: Source of FX price series (any registered provider serving FX).
        symbol_for: Maps a currency pair to its canonical symbol.
        max_staleness: Oldest fixing accepted to convert a price.
    """

    def __init__(
        self,
        market_data: MarketDataService,
        *,
        symbol_for: Callable[[CurrencyPair], str] = yahoo_style_fx_symbol,
        max_staleness: pd.Timedelta = DEFAULT_MAX_STALENESS,
    ) -> None:
        self._market_data = market_data
        self._symbol_for = symbol_for
        self._max_staleness = max_staleness

    async def get_rates(
        self, pair: CurrencyPair, *, start: date | None = None, end: date | None = None
    ) -> FxRates:
        """Daily fixings of ``pair`` between ``start`` and ``end``.

        Raises:
            DataUnavailableError: If no provider can deliver the pair.
        """
        request = BarsRequest(
            self._symbol_for(pair), Frequency.DAY_1, start, end, asset_class=AssetClass.FX
        )
        series = await self._market_data.get_bars(request)
        return FxRates.from_price_series(series, pair)

    async def convert(self, series: PriceSeries, to: Currency) -> PriceSeries:
        """``series`` expressed in ``to`` (unchanged if it already is)."""
        converted = await self.convert_all([series], to)
        return converted[0]

    async def convert_all(self, series: Iterable[PriceSeries], to: Currency) -> list[PriceSeries]:
        """Convert several series to ``to``, fetching each needed pair only once."""
        items = list(series)
        needed: dict[Currency, tuple[date, date]] = {}
        for item in items:
            if item.currency == to:
                continue
            start, end = item.start.date() - _LOOKBACK, item.end.date()
            if item.currency in needed:
                known_start, known_end = needed[item.currency]
                start, end = min(start, known_start), max(end, known_end)
            needed[item.currency] = (start, end)
        currencies = list(needed)
        fetched = await asyncio.gather(
            *(
                self.get_rates(
                    CurrencyPair(currency, to), start=needed[currency][0], end=needed[currency][1]
                )
                for currency in currencies
            )
        )
        rates = dict(zip(currencies, fetched, strict=True))
        return [
            item
            if item.currency == to
            else rates[item.currency].convert(item, max_staleness=self._max_staleness)
            for item in items
        ]
