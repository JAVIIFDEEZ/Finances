"""Depth of the book of Binance's perpetual swaps, from its daily public dumps (ADR-0044).

Binance publishes, for every futures contract and day since 2023, a ``bookDepth`` file with a
snapshot every 30 seconds: for each distance from the price (±0.2 %, ±1 % ... ±5 %; negative
for the bids, positive for the asks), the quantity resting within it and its value. They are
read like the funding and the positioning: listed, verified against their SHA-256, only for
the days of the range, and kept on disk when there is a dump cache (ADR-0043).

* **Cumulative.** What rests within ±2 % includes what rests within ±1 %: a file that says
  otherwise is refused (the domain checks it).
* **Linear swaps** (``BTC/USDT:USDT``, USDⓈ-M) give the quantity in the base asset and its
  value in the quote one.
* **Inverse swaps** (``BTC/USD:BTC``, COIN-M) give it in contracts and its value in the base
  asset, without ±0.2 %: the second is the quantity in base units, and a value in dollars,
  which needs each contract's size, is not computed.
* **Reference price.** Binance's documentation does not say from which price the
  distances are measured; the files are consistent with the mid price (the average price of
  each band falls inside it).
* **Publication.** A day is published the next morning: today is not there.
* **Bounded.** A start date is needed and at most :data:`MAX_DAYS` days are read at once: a
  day weighs about 560 kB compressed.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.adapters.providers.binance import dumps
from investinglab.adapters.providers.binance.contracts import contract, swap_instrument
from investinglab.domain.book_depth import BookDepthSeries, BookSide, DepthMeasure
from investinglab.domain.errors import DomainError
from investinglab.domain.series import DataSource
from investinglab.ports.errors import (
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)

if TYPE_CHECKING:
    from investinglab.adapters.http import HttpClient
    from investinglab.adapters.storage.published import PublishedFileCache
    from investinglab.ports.market_data import BookDepthRequest

__all__ = ["BANDS", "BOOK_DEPTH_DATASET", "MAX_DAYS", "fetch_book_depth"]

BOOK_DEPTH_DATASET: Final = "bookDepth"

BANDS: Final = frozenset({0.2, 1.0, 2.0, 3.0, 4.0, 5.0})
"""Distances from the price, in percent, a file can hold."""

MAX_DAYS: Final = 92
"""Most days read at once: a quarter, about 50 MB to download the first time."""

_COLUMNS: Final = ("timestamp", "percentage", "depth", "notional")
_LINEAR: Final = {"depth": DepthMeasure.QUANTITY, "notional": DepthMeasure.NOTIONAL}
"""What the columns of a USDⓈ-M file measure."""
_INVERSE: Final = {"notional": DepthMeasure.QUANTITY}
"""What the columns of a COIN-M file measure: its ``depth`` is in contracts."""
_DAY: Final = timedelta(days=1)


def _snapshots(
    provider: str, key: str, text: str, measures: dict[str, DepthMeasure]
) -> pd.DataFrame:
    """The snapshots of one daily file, by instant (UTC).

    One column per ``(measure, side, band)``.
    """
    try:
        rows = pd.read_csv(io.StringIO(text), dtype={"timestamp": str})
    except (ValueError, pd.errors.ParserError) as error:
        raise ProviderDataError(provider, f"{key}: unreadable file ({error})") from None
    if tuple(rows.columns) != _COLUMNS:
        raise ProviderDataError(provider, f"{key}: unexpected columns {list(rows.columns)}")
    try:
        times = pd.to_datetime(rows["timestamp"], format="%Y-%m-%d %H:%M:%S", utc=True)
        distance = pd.to_numeric(rows["percentage"])
        values = {column: pd.to_numeric(rows[column]) for column in measures}
    except ValueError:
        raise ProviderDataError(provider, f"{key}: unreadable row") from None
    if (distance == 0).any() or distance.isna().any():
        raise ProviderDataError(provider, f"{key}: a band without a distance from the price")
    sides = distance.lt(0).map({True: BookSide.BID.value, False: BookSide.ASK.value})
    long = pd.concat(
        [
            pd.DataFrame(
                {
                    "time": times,
                    "measure": measure.value,
                    "side": sides,
                    "band": distance.abs().round(4),
                    "value": series,
                }
            )
            for column, series in values.items()
            for measure in (measures[column],)
        ],
        ignore_index=True,
    )
    try:
        # pivot, never pivot_table: a snapshot given twice is refused, not averaged.
        return long.pivot(index="time", columns=["measure", "side", "band"], values="value")
    except ValueError:
        raise ProviderDataError(provider, f"{key}: a snapshot is given twice") from None


async def fetch_book_depth(
    provider: str,
    listing: HttpClient,
    files: HttpClient,
    request: BookDepthRequest,
    *,
    now: datetime,
    cache: PublishedFileCache | None = None,
) -> BookDepthSeries:
    """The depth of the book of a Binance perpetual swap, at ``request.frequency``.

    Raises:
        UnsupportedRequestError: If the symbol is not a swap Binance could list, no start
            is given, or the range spans more than :data:`MAX_DAYS` days.
        SymbolNotFoundError: If Binance publishes no book depth of that contract.
        ProviderDataError: If nothing is published in the range (today is published
            tomorrow), or a file is damaged.
    """
    if request.start is None:
        raise UnsupportedRequestError(
            provider, f"{request.symbol}: give a start date (Binance publishes one file a day)"
        )
    last_day = request.end or now.date()
    if (last_day - request.start).days + 1 > MAX_DAYS:
        raise UnsupportedRequestError(
            provider,
            f"{request.symbol}: {request.start} to {last_day} is more than {MAX_DAYS} days of "
            "book depth; ask for less",
        )
    market, name = contract(provider, request.symbol)
    instrument = swap_instrument(provider, request.symbol)
    prefix = f"data/futures/{market}/daily/{BOOK_DEPTH_DATASET}/{name}/"
    stem = f"{prefix}{name}-{BOOK_DEPTH_DATASET}-"
    after = f"{stem}{(request.start - _DAY).isoformat()}.zip.CHECKSUM"
    until = f"{stem}{request.end.isoformat()}.zip" if request.end else None
    listed = await dumps.published(provider, listing, prefix, after=after, until=until)
    if not listed:
        if not await dumps.published(provider, listing, prefix, limit=1, page_size=2):
            raise SymbolNotFoundError(
                provider, f"{request.symbol}: Binance publishes no book depth of {name}"
            )
        raise ProviderDataError(
            provider,
            f"{request.symbol}: no book depth published between {request.start} and "
            f"{request.end or 'now'}; Binance publishes each day the next morning",
        )
    measures = _LINEAR if market == "um" else _INVERSE
    texts = await dumps.read_all(provider, files, listed, cache=cache)
    frame = pd.concat(
        [
            _snapshots(provider, item.key, text, measures)
            for item, text in zip(listed, texts, strict=True)
        ]
    ).sort_index(kind="stable")
    frame = frame[~frame.index.duplicated(keep="last")]
    first = _midnight(request.start)
    stop = _midnight(request.end) + _DAY if request.end else pd.Timestamp(now)
    frame = frame.loc[first : stop - pd.Timedelta(1, "ns")]
    if frame.empty:
        raise ProviderDataError(
            provider,
            f"{request.symbol}: no book depth published between {request.start} and "
            f"{request.end or 'now'} (last day: {_day(listed[-1].key)})",
        )
    source = DataSource(provider, now, f"futures/{market}/daily/{BOOK_DEPTH_DATASET}")
    noted = DepthMeasure.NOTIONAL.value in frame.columns.get_level_values("measure")
    try:
        series = BookDepthSeries.from_snapshots(
            instrument,
            provider,
            source,
            request.frequency,
            frame,
            notional_currency=instrument.currency if noted else None,
        )
        return series.finished(now)
    except DomainError as error:
        raise ProviderDataError(provider, f"{request.symbol}: {error}") from error


def _midnight(day: date) -> pd.Timestamp:
    return pd.Timestamp(datetime(day.year, day.month, day.day, tzinfo=UTC))


def _day(key: str) -> str:
    return key.rsplit(f"-{BOOK_DEPTH_DATASET}-", 1)[-1].removesuffix(".zip")
