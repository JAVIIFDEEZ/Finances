"""Positioning in Binance's perpetual swaps, from its daily public dumps (ADR-0042).

Binance publishes, for every futures contract and day, a ``metrics`` file with a snapshot
every 5 minutes: the open interest and three long/short ratios, and the takers' buy/sell
volume ratio. They are read like the funding (ADR-0041): listed, verified against their
SHA-256 and only for the days of the range.

* **Linear swaps** (``BTC/USDT:USDT``, USDⓈ-M) give the open interest in the base asset and
  its value in the quote one.
* **Inverse swaps** (``BTC/USD:BTC``, COIN-M) give the open interest in contracts and its
  value in the base asset: the second is the open interest in base units, and its value in
  dollars, which needs each contract's size, is not computed.
* **Publication.** A day is published the next morning: today is not there.
* **A start date is needed**: one file a day since 2021 is too much to read at once.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.adapters.providers.binance import dumps
from investinglab.adapters.providers.binance.contracts import contract, swap_instrument
from investinglab.domain.errors import DomainError
from investinglab.domain.positioning import PositioningField, PositioningSeries
from investinglab.domain.series import DataSource
from investinglab.domain.time import Frequency
from investinglab.ports.errors import (
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)

if TYPE_CHECKING:
    from investinglab.adapters.http import HttpClient
    from investinglab.adapters.storage.published import PublishedFileCache
    from investinglab.ports.market_data import PositioningRequest

__all__ = ["FIELDS", "METRICS_DATASET", "fetch_positioning"]

METRICS_DATASET: Final = "metrics"

_LINEAR: Final = {
    "sum_open_interest": PositioningField.OPEN_INTEREST,
    "sum_open_interest_value": PositioningField.OPEN_INTEREST_VALUE,
    "count_long_short_ratio": PositioningField.LONG_SHORT_ACCOUNTS,
    "count_toptrader_long_short_ratio": PositioningField.TOP_LONG_SHORT_ACCOUNTS,
    "sum_toptrader_long_short_ratio": PositioningField.TOP_LONG_SHORT_POSITIONS,
    "sum_taker_long_short_vol_ratio": PositioningField.TAKER_BUY_SELL,
}
"""Columns of a USDⓈ-M file and what they are."""

_INVERSE: Final = {
    "sum_open_interest_value": PositioningField.OPEN_INTEREST,  # in the base asset
    "count_long_short_ratio": PositioningField.LONG_SHORT_ACCOUNTS,
    "count_toptrader_long_short_ratio": PositioningField.TOP_LONG_SHORT_ACCOUNTS,
    "sum_toptrader_long_short_ratio": PositioningField.TOP_LONG_SHORT_POSITIONS,
    "sum_taker_long_short_vol_ratio": PositioningField.TAKER_BUY_SELL,
}
"""Columns of a COIN-M file: its open interest is in contracts, its value in base units."""

FIELDS: Final = frozenset(_LINEAR.values())
"""Every field Binance's dumps can give."""

_DAY: Final = timedelta(days=1)
_TIME: Final = "create_time"


def _snapshots(
    provider: str, key: str, text: str, columns: dict[str, PositioningField]
) -> pd.DataFrame:
    """The snapshots of one daily file, by instant (UTC), with the fields it holds."""
    rows = csv.DictReader(text.splitlines())
    header = rows.fieldnames or []
    if _TIME not in header or not any(column in header for column in columns):
        raise ProviderDataError(provider, f"{key}: unexpected columns {header}")
    times: list[str] = []
    values: dict[str, list[float]] = {field.value: [] for field in columns.values()}
    for row in rows:
        times.append(row[_TIME])
        for column, field in columns.items():
            cell = (row.get(column) or "").strip()
            try:
                values[field.value].append(float(cell) if cell else np.nan)
            except ValueError:
                raise ProviderDataError(provider, f"{key}: unreadable {column} {cell!r}") from None
    try:
        index = pd.to_datetime(times, format="%Y-%m-%d %H:%M:%S", utc=True)
    except ValueError:
        raise ProviderDataError(provider, f"{key}: unreadable snapshot times") from None
    return pd.DataFrame(values, index=index)


def _day(key: str) -> str:
    return key.rsplit("-metrics-", 1)[-1].removesuffix(".zip")


async def fetch_positioning(
    provider: str,
    listing: HttpClient,
    files: HttpClient,
    request: PositioningRequest,
    *,
    now: datetime,
    cache: PublishedFileCache | None = None,
) -> PositioningSeries:
    """The positioning snapshots of a Binance perpetual swap, at ``request.frequency``.

    Each day is one file; with a ``cache``, a day already verified is read from disk.

    Raises:
        UnsupportedRequestError: If the symbol is not a swap Binance could list, no start
            is given, or the range spans more days than are read at once.
        SymbolNotFoundError: If Binance publishes no metrics of that contract.
        ProviderDataError: If nothing is published in the range (today is published
            tomorrow), or a file is damaged.
    """
    if request.start is None:
        raise UnsupportedRequestError(
            provider, f"{request.symbol}: give a start date (Binance publishes one file a day)"
        )
    market, name = contract(provider, request.symbol)
    instrument = swap_instrument(provider, request.symbol)
    prefix = f"data/futures/{market}/daily/{METRICS_DATASET}/{name}/"
    stem = f"{prefix}{name}-{METRICS_DATASET}-"
    after = f"{stem}{(request.start - _DAY).isoformat()}.zip.CHECKSUM"
    until = f"{stem}{request.end.isoformat()}.zip" if request.end else None
    keys = await dumps.published(provider, listing, prefix, after=after, until=until)
    if not keys:
        if not await dumps.published(provider, listing, prefix, limit=1, page_size=2):
            raise SymbolNotFoundError(
                provider, f"{request.symbol}: Binance publishes no positioning of {name}"
            )
        raise ProviderDataError(
            provider,
            f"{request.symbol}: no positioning published between {request.start} and "
            f"{request.end or 'now'}; Binance publishes each day the next morning",
        )
    columns = _LINEAR if market == "um" else _INVERSE
    texts = await dumps.read_all(provider, files, keys, cache=cache)
    frame = pd.concat(
        [
            _snapshots(provider, listed.key, text, columns)
            for listed, text in zip(keys, texts, strict=True)
        ]
    ).sort_index(kind="stable")
    frame = frame[~frame.index.duplicated(keep="last")].dropna(axis="columns", how="all")
    first = _midnight(request.start)
    stop = _midnight(request.end) + _DAY if request.end else pd.Timestamp(now)
    frame = frame.loc[first : stop - pd.Timedelta(1, "ns")]
    if frame.empty:
        raise ProviderDataError(
            provider,
            f"{request.symbol}: no positioning published between {request.start} and "
            f"{request.end or 'now'} (last day: {_day(keys[-1].key)})",
        )
    source = DataSource(provider, now, f"futures/{market}/daily/{METRICS_DATASET}")
    valued = PositioningField.OPEN_INTEREST_VALUE.value in frame.columns
    try:
        native = PositioningSeries(
            instrument,
            provider,
            source,
            Frequency.MINUTE_5,
            frame,
            value_currency=instrument.currency if valued else None,
        )
        return native.resample(request.frequency).finished(now)
    except DomainError as error:
        raise ProviderDataError(provider, f"{request.symbol}: {error}") from error


def _midnight(day: date) -> pd.Timestamp:
    return pd.Timestamp(datetime(day.year, day.month, day.day, tzinfo=UTC))
