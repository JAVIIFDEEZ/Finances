"""Builders of synthetic domain objects for tests (provider ``synthetic``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from investinglab.domain import (
    EUR,
    EXCHANGES,
    AssetClass,
    Currency,
    DataSource,
    EconomicSeries,
    Exchange,
    Frequency,
    Instrument,
    PriceSeries,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

SYNTHETIC_SOURCE = DataSource(
    provider="synthetic",
    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    dataset="unit-tests",
)


def make_instrument(
    symbol: str = "TEST.MC",
    *,
    currency: Currency = EUR,
    asset_class: AssetClass = AssetClass.EQUITY,
    exchange: Exchange | None = EXCHANGES["XMAD"],
) -> Instrument:
    """A synthetic instrument (defaults to a Madrid-listed equity in EUR)."""
    return Instrument(
        symbol=symbol,
        name=f"Synthetic {symbol}",
        asset_class=asset_class,
        currency=currency,
        exchange=exchange,
    )


def business_days(n: int, start: str = "2024-01-02") -> pd.DatetimeIndex:
    """``n`` consecutive business days as tz-naive session labels."""
    return pd.bdate_range(start=start, periods=n)


def make_bars(
    prices: Sequence[float] | np.ndarray,
    index: pd.DatetimeIndex | None = None,
    *,
    ohlc: bool = False,
    volume: Sequence[float] | None = None,
) -> pd.DataFrame:
    """Bars with a ``close`` column (and optionally coherent OHLC and volume)."""
    values = np.asarray(prices, dtype="float64")
    idx = index if index is not None else business_days(len(values))
    frame = pd.DataFrame({"close": values}, index=idx)
    if ohlc:
        frame.insert(0, "open", values * 0.995)
        frame.insert(1, "high", values * 1.01)
        frame.insert(2, "low", values * 0.99)
    if volume is not None:
        frame["volume"] = np.asarray(volume, dtype="float64")
    return frame


def make_series(
    prices: Sequence[float] | np.ndarray = (100.0, 101.0, 99.5, 102.0, 103.5),
    *,
    symbol: str = "TEST.MC",
    index: pd.DatetimeIndex | None = None,
    frequency: Frequency = Frequency.DAY_1,
    currency: Currency = EUR,
    asset_class: AssetClass = AssetClass.EQUITY,
    exchange: Exchange | None = EXCHANGES["XMAD"],
    ohlc: bool = False,
    volume: Sequence[float] | None = None,
) -> PriceSeries:
    """A validated synthetic price series."""
    return PriceSeries(
        instrument=make_instrument(
            symbol, currency=currency, asset_class=asset_class, exchange=exchange
        ),
        frequency=frequency,
        source=SYNTHETIC_SOURCE,
        data=make_bars(prices, index, ohlc=ohlc, volume=volume),
    )


def gbm_prices(
    n: int,
    *,
    mu: float = 0.05,
    sigma: float = 0.2,
    s0: float = 100.0,
    periods_per_year: float = 252.0,
    seed: int = 7,
) -> np.ndarray:
    """Synthetic geometric-Brownian-motion path with a fixed seed (``n`` prices)."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / periods_per_year
    shocks = rng.standard_normal(n - 1)
    log_steps = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks
    return s0 * np.exp(np.concatenate([[0.0], np.cumsum(log_steps)]))


def make_economic_series(
    series_id: str = "SYNTH_RATE",
    rows: Sequence[tuple[str, str, float]] = (
        ("2024-01-01", "2024-02-05", 3.5),
        ("2024-01-01", "2024-03-07", 3.6),
        ("2024-02-01", "2024-03-07", 3.8),
        ("2024-03-01", "2024-04-05", 3.9),
    ),
) -> EconomicSeries:
    """A synthetic monthly economic series with one revised observation."""
    data = pd.DataFrame(list(rows), columns=["observation_date", "published_at", "value"])
    data["observation_date"] = pd.to_datetime(data["observation_date"])
    data["published_at"] = pd.to_datetime(data["published_at"])
    return EconomicSeries(
        series_id=series_id,
        title=f"Synthetic {series_id}",
        units="Percent",
        frequency=Frequency.MONTH_1,
        source=SYNTHETIC_SOURCE,
        data=data,
        seasonal_adjustment="NSA",
    )


def make_fx_series(
    rates: Sequence[float] | np.ndarray,
    *,
    pair: str = "EURUSD",
    index: pd.DatetimeIndex | None = None,
) -> PriceSeries:
    """A synthetic FX series (``EURUSD=X`` quoted in USD by default)."""
    quote = Currency(pair[3:])
    return make_series(
        rates,
        symbol=f"{pair}=X",
        index=index,
        currency=quote,
        asset_class=AssetClass.FX,
        exchange=EXCHANGES["FX"],
    )
