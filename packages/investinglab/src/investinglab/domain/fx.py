"""Exchange rates and as-of currency conversion of price series (ADR-0014).

Conversion never looks ahead and never invents rates:

* Each price uses the **latest fixing known at that time** (as-of join): a daily fixing
  dated *d* converts the session *d* (the ECB publishes its reference rates around
  16:00 CET, before the Madrid and New York closes), and only from the next day onwards
  when converting intraday bars.
* A price without a fixing within ``max_staleness`` is dropped, not filled.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field, replace
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics import simple_returns
from investinglab.domain.errors import DomainError, InvalidSeriesError
from investinglab.domain.series import TIME_INDEX_NAME, DataSource, PriceField, PriceSeries

if TYPE_CHECKING:
    from investinglab.domain.money import Currency, CurrencyPair

__all__ = ["DEFAULT_MAX_STALENESS", "FxRates", "currency_attribution"]

DEFAULT_MAX_STALENESS: Final = pd.Timedelta(days=7)
"""Oldest fixing accepted to convert a price (covers long holiday weekends)."""

_PRICE_COLUMNS: Final = tuple(f.value for f in PriceField if f is not PriceField.VOLUME)


def _validated_rates(data: object, subject: str) -> pd.Series:
    if not isinstance(data, pd.Series):
        raise InvalidSeriesError(subject, [f"rates must be a Series, got {type(data).__name__}"])
    problems: list[str] = []
    index = data.index
    if not isinstance(index, pd.DatetimeIndex):
        raise InvalidSeriesError(subject, ["rates need a DatetimeIndex"])
    if data.empty:
        problems.append("at least one fixing is required")
    if index.has_duplicates:
        problems.append("duplicated fixing dates")
    if not index.is_monotonic_increasing:
        problems.append("fixings must be sorted in time")
    if index.tz is None and not (index == index.normalize()).all():
        problems.append("daily fixings must be dates at midnight (or use UTC timestamps)")
    values = pd.to_numeric(data, errors="coerce").astype("float64")
    if not (np.isfinite(values) & (values > 0)).all():
        problems.append("rates must be finite and strictly positive (drop missing fixings)")
    if problems:
        raise InvalidSeriesError(subject, problems)
    if index.tz is not None:
        index = index.tz_convert("UTC")
    return pd.Series(values.to_numpy(), index=pd.DatetimeIndex(index).as_unit("ns"))


@dataclass(frozen=True, slots=True, eq=False)
class FxRates:
    """Validated exchange rates of a currency pair: the price of one ``base`` in ``quote``.

    Args:
        pair: Currency pair (``EURUSD`` at 1.08 means 1 EUR = 1.08 USD).
        source: Provenance of the fixings.
        data: Rates indexed by fixing date (timezone-naive dates) or UTC timestamps.
    """

    pair: CurrencyPair
    source: DataSource
    data: InitVar[pd.Series]
    _rates: pd.Series = field(init=False, repr=False)

    def __post_init__(self, data: pd.Series) -> None:
        object.__setattr__(self, "_rates", _validated_rates(data, self.pair.symbol))

    @classmethod
    def from_price_series(cls, series: PriceSeries, pair: CurrencyPair) -> FxRates:
        """Build rates from an FX price series (e.g. ``EURUSD=X``) quoted in ``pair.quote``.

        Raises:
            DomainError: If the series is not expressed in the pair's quote currency.
        """
        if series.currency != pair.quote:
            raise DomainError(
                f"{series.symbol} is quoted in {series.currency}, expected {pair.quote} "
                f"for {pair.symbol}"
            )
        return cls(pair=pair, source=series.source, data=series.prices)

    @property
    def rates(self) -> pd.Series:
        """The fixings, named after the pair."""
        return self._rates.rename(self.pair.symbol)

    @property
    def is_intraday(self) -> bool:
        """Whether the fixings are timestamps (UTC) rather than daily dates."""
        return pd.DatetimeIndex(self._rates.index).tz is not None

    def inverse(self) -> FxRates:
        """The same rates for the opposite pair (``USDEUR`` from ``EURUSD``)."""
        return FxRates(pair=self.pair.inverse(), source=self.source, data=1.0 / self._rates)

    def rates_at(
        self,
        timestamps: pd.DatetimeIndex,
        *,
        max_staleness: pd.Timedelta = DEFAULT_MAX_STALENESS,
    ) -> pd.Series:
        """Latest fixing usable at each timestamp (NaN when none within ``max_staleness``).

        Daily fixings convert daily prices of the same date. For intraday prices, a daily
        fixing dated *d* is only used from *d + 1* (00:00 UTC), so no bar uses a rate
        published after it.

        Raises:
            DomainError: When converting daily prices with intraday rates (ambiguous).
        """
        target = pd.DatetimeIndex(timestamps)
        source_index = pd.DatetimeIndex(self._rates.index)
        if target.tz is not None:
            target = target.tz_convert("UTC")
            if source_index.tz is None:
                source_index = (source_index + pd.Timedelta(days=1)).tz_localize("UTC")
        elif source_index.tz is not None:
            raise DomainError("Daily prices need daily fixings; resample the rates first")
        left = pd.DataFrame({"at": target.as_unit("ns")})
        right = pd.DataFrame({"at": source_index.as_unit("ns"), "rate": self._rates.to_numpy()})
        merged = pd.merge_asof(left, right, on="at", direction="backward", tolerance=max_staleness)
        return pd.Series(merged["rate"].to_numpy(), index=pd.DatetimeIndex(timestamps))

    def coverage(
        self, series: PriceSeries, *, max_staleness: pd.Timedelta = DEFAULT_MAX_STALENESS
    ) -> float:
        """Share of the series' timestamps that have a usable fixing."""
        rates = self.rates_at(pd.DatetimeIndex(series.bars.index), max_staleness=max_staleness)
        return float(rates.notna().mean())

    def convert(
        self,
        series: PriceSeries,
        *,
        max_staleness: pd.Timedelta = DEFAULT_MAX_STALENESS,
    ) -> PriceSeries:
        """Express ``series`` in the other currency of the pair.

        Prices in the base currency are multiplied by the rate; prices in the quote currency
        are divided by it. Volume is unchanged. Timestamps without a usable fixing are
        dropped.

        Raises:
            DomainError: If the series currency is not part of the pair.
            InvalidSeriesError: If too few prices remain after conversion.
        """
        if series.currency == self.pair.base:
            target: Currency = self.pair.quote
            invert = False
        elif series.currency == self.pair.quote:
            target = self.pair.base
            invert = True
        else:
            raise DomainError(
                f"Cannot convert {series.symbol} ({series.currency}) with {self.pair.symbol}"
            )
        bars = series.bars
        rates = self.rates_at(pd.DatetimeIndex(bars.index), max_staleness=max_staleness)
        factor = (1.0 / rates) if invert else rates
        usable = factor.notna().to_numpy()
        converted = bars.loc[usable].copy()
        columns = [c for c in _PRICE_COLUMNS if c in converted.columns]
        converted[columns] = converted[columns].mul(factor.to_numpy()[usable], axis=0)
        converted.index.name = TIME_INDEX_NAME
        origin = series.source.dataset or series.source.provider
        source = DataSource(
            provider=series.source.provider,
            retrieved_at=max(series.source.retrieved_at, self.source.retrieved_at),
            dataset=f"{origin} in {target} via {self.pair.symbol} ({self.source.provider})",
        )
        return series.with_bars(
            converted, instrument=replace(series.instrument, currency=target), source=source
        )


def currency_attribution(local: PriceSeries, converted: PriceSeries) -> pd.DataFrame:
    """Split the returns of a converted series into asset and currency components.

    ``(1 + total) = (1 + local) * (1 + currency)`` on every date both series share.

    Returns:
        Per-period ``local``, ``currency`` and ``total`` returns plus their cumulative
        counterparts (``cum_local``, ``cum_currency``, ``cum_total``).
    """
    if local.symbol != converted.symbol:
        raise DomainError(
            f"Attribution needs the same instrument, got {local.symbol} and {converted.symbol}"
        )
    common = local.prices.index.intersection(converted.prices.index)
    local_prices = local.prices.loc[common]
    total_prices = converted.prices.loc[common]
    frame = pd.DataFrame(
        {"local": simple_returns(local_prices), "total": simple_returns(total_prices)}
    )
    frame["currency"] = (1.0 + frame["total"]) / (1.0 + frame["local"]) - 1.0
    for column in ("local", "currency", "total"):
        frame[f"cum_{column}"] = (1.0 + frame[column]).cumprod() - 1.0
    return frame[["local", "currency", "total", "cum_local", "cum_currency", "cum_total"]]
