"""Rules every crypto venue adapter shares (ADR-0032).

Spot pairs are written ``BASE/QUOTE`` (``BTC/USDT``) whatever the venue calls them, the
quote asset is the currency of the prices, bars open on UTC boundaries and only finished bars
are kept. Each venue adapter (Binance, Kraken, Coinbase...) maps its own payload onto a
frame of UTC open times and hands it to :func:`price_series` and :func:`flow_series`, which
apply the same labels, resampling and validation for all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.domain.errors import DomainError
from investinglab.domain.flow import FlowField, FlowSeries
from investinglab.domain.instruments import EXCHANGES, AssetClass, Instrument
from investinglab.domain.money import Currency
from investinglab.domain.series import MIN_OBSERVATIONS, PriceAdjustment, PriceField, PriceSeries
from investinglab.domain.time import Frequency
from investinglab.ports.errors import ProviderDataError, UnsupportedRequestError

if TYPE_CHECKING:
    from collections.abc import Collection

    from investinglab.domain.series import DataSource
    from investinglab.ports.market_data import BarsRequest

__all__ = [
    "PAIR",
    "PRICE_COLUMNS",
    "VenueBars",
    "bar_length",
    "finished_bars",
    "flow_series",
    "midnight",
    "native_frequency",
    "pair_instrument",
    "price_series",
    "split_pair",
    "utc_bounds",
]

PAIR: Final = r"[A-Z0-9]{2,15}/[A-Z0-9]{2,10}"
"""A spot pair: base and quote assets separated by a slash (``BTC/USDT``)."""

PRICE_COLUMNS: Final = (
    PriceField.OPEN,
    PriceField.HIGH,
    PriceField.LOW,
    PriceField.CLOSE,
    PriceField.VOLUME,
)

_PAIR = re.compile(PAIR)
_DAY: Final = timedelta(days=1)


def split_pair(provider: str, symbol: str) -> tuple[str, str]:
    """Base and quote assets of a ``BASE/QUOTE`` symbol.

    Raises:
        UnsupportedRequestError: If the symbol is not written as a pair.
    """
    if not _PAIR.fullmatch(symbol):
        raise UnsupportedRequestError(
            provider, f"{symbol!r} is not a pair written BASE/QUOTE in capitals (e.g. BTC/USDT)"
        )
    base, quote = symbol.split("/")
    return base, quote


def pair_instrument(provider: str, symbol: str, venue: str) -> Instrument:
    """The instrument of a spot pair on ``venue``, priced in its quote asset.

    Raises:
        UnsupportedRequestError: If the symbol is not a pair or its quote asset is not a
            currency the domain knows.
    """
    base, quote = split_pair(provider, symbol)
    try:
        currency = Currency(quote)
    except DomainError as error:
        raise UnsupportedRequestError(
            provider, f"{symbol}: prices quoted in {quote} cannot be represented ({error})"
        ) from error
    return Instrument(
        symbol=symbol,
        name=f"{base}/{quote} ({venue} spot)",
        asset_class=AssetClass.CRYPTO,
        currency=currency,
        exchange=EXCHANGES["CRYPTO"],
    )


def native_frequency(
    provider: str, frequency: Frequency, natives: Collection[Frequency]
) -> Frequency:
    """The frequency to download for ``frequency`` from a venue that serves ``natives``.

    The frequency itself when served; daily bars for weekly and coarser ones; for an intraday
    frequency the venue lacks, the coarsest native one that divides it (15 minutes for 30).

    Raises:
        UnsupportedRequestError: If no native frequency can build it.
    """
    if frequency in natives:
        return frequency
    if not frequency.is_intraday:
        if Frequency.DAY_1 in natives:
            return Frequency.DAY_1
    else:
        minutes = frequency.minutes or 0
        finer = [f for f in natives if f.is_intraday and minutes % (f.minutes or minutes + 1) == 0]
        if finer:
            return max(finer, key=lambda f: f.minutes or 0)
    raise UnsupportedRequestError(provider, f"{frequency.value} bars cannot be built from its bars")


def midnight(day: date) -> datetime:
    """00:00 UTC of ``day``."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def utc_bounds(
    provider: str, request: BarsRequest, now: datetime
) -> tuple[datetime | None, datetime]:
    """UTC instants from the first requested day (``None``: from the listing) to the end.

    The end is exclusive: the midnight after the last requested day, or ``now``.

    Raises:
        UnsupportedRequestError: If no bar can have finished in the range.
    """
    first = midnight(request.start) if request.start else None
    last = min(midnight(request.end) + _DAY, now) if request.end else now
    if first is not None and first >= last:
        raise UnsupportedRequestError(
            provider, f"{request.symbol}: no bar can have finished between {first} and {last}"
        )
    return first, last


def bar_length(native: Frequency) -> pd.Timedelta:
    """Length of one bar of an intraday or daily frequency."""
    return pd.Timedelta(minutes=native.minutes) if native.minutes else pd.Timedelta(days=1)


def finished_bars(frame: pd.DataFrame, native: Frequency, now: datetime) -> pd.DataFrame:
    """Bars closed at ``now``, each open time once, labelled as the domain expects.

    ``frame`` is indexed by bar open times in UTC (any order). Daily bars come out labelled
    with their UTC date (no timezone); intraday ones keep their open time in UTC.
    """
    ordered = frame.sort_index(kind="stable")
    ordered = ordered[~ordered.index.duplicated(keep="last")]
    opens = pd.DatetimeIndex(ordered.index)
    finished = ordered[opens + bar_length(native) <= pd.Timestamp(now)]
    if native.is_intraday:
        return finished
    return finished.set_axis(pd.DatetimeIndex(finished.index).tz_localize(None).normalize())


@dataclass(frozen=True, slots=True)
class VenueBars:
    """Finished bars a venue downloaded for one request, before they become domain series.

    Attributes:
        instrument: The pair on that venue.
        native: Frequency downloaded.
        frame: Bars from :func:`finished_bars`, with price and flow columns.
        source: Provenance.
        now: When they were downloaded (decides which aggregated bins are closed).
    """

    instrument: Instrument
    native: Frequency
    frame: pd.DataFrame
    source: DataSource
    now: datetime


def _enough(provider: str, request: BarsRequest, bars: VenueBars) -> None:
    if len(bars.frame) < MIN_OBSERVATIONS:
        raise ProviderDataError(
            provider,
            f"{request.symbol}: only {len(bars.frame)} finished {bars.native.value} bars between "
            f"{request.start or 'the listing'} and {request.end or 'now'}",
        )


def _closed_bins(index: pd.Index, frequency: Frequency, now: datetime) -> pd.Index:
    """Intraday bins already closed at ``now`` (a bin built from part of its bars is not)."""
    opens = pd.DatetimeIndex(index)
    return index[opens + bar_length(frequency) <= pd.Timestamp(now)]


def price_series(provider: str, request: BarsRequest, bars: VenueBars) -> PriceSeries:
    """The finished bars as the requested series (raw prices), aggregated when needed.

    Raises:
        ProviderDataError: Fewer than three finished bars, or bars that break the domain rules.
    """
    _enough(provider, request, bars)
    columns = [c for c in PRICE_COLUMNS if c in bars.frame.columns]
    target = request.frequency
    try:
        series = PriceSeries(
            instrument=bars.instrument,
            frequency=bars.native,
            source=bars.source,
            data=bars.frame[columns],
            adjustment=PriceAdjustment.RAW,
        )
        if bars.native is not target:
            series = series.resample(target)
            if target.is_intraday:
                closed = _closed_bins(series.bars.index, target, bars.now)
                series = series.with_bars(series.bars.loc[closed])
    except DomainError as error:
        raise ProviderDataError(provider, f"{request.symbol}: {error}") from error
    return series


def flow_series(provider: str, request: BarsRequest, bars: VenueBars) -> FlowSeries:
    """The flow of the same bars as :func:`price_series`, aggregated the same way.

    Raises:
        ProviderDataError: Fewer than three finished bars, or flow that breaks the domain rules.
    """
    _enough(provider, request, bars)
    columns = [field.value for field in FlowField if field.value in bars.frame.columns]
    target = request.frequency
    try:
        flow = FlowSeries(bars.instrument, bars.native, bars.source, bars.frame[columns])
        if bars.native is not target:
            flow = flow.resample(target)
            if target.is_intraday:
                closed = _closed_bins(flow.flow.index, target, bars.now)
                flow = FlowSeries(bars.instrument, target, bars.source, flow.flow.loc[closed])
    except DomainError as error:
        raise ProviderDataError(provider, f"{request.symbol}: {error}") from error
    return flow
