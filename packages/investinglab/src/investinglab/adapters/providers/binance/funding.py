"""Funding of Binance's perpetual swaps, from its monthly public dumps (ADR-0041).

Binance's futures API refuses some countries, but its dumps answer everywhere: one file per
contract and month, with the rate of every settlement and the accrual interval. They give
the whole history since the contract was listed, verified against its SHA-256.

* **Symbols** follow the unified notation of perpetual swaps, ``BASE/QUOTE:SETTLE``:
  ``BTC/USDT:USDT`` is the linear swap settled in USDT (``BTCUSDT`` on USDⓈ-M futures) and
  ``BTC/USD:BTC`` the inverse one settled in bitcoin (``BTCUSD_PERP`` on COIN-M futures).
* **The rate settled** (``last_funding_rate``) at each settlement, indexed by the second it
  was computed in UTC (Binance stamps it a few milliseconds after the hour). Positive,
  longs pay shorts.
* **Publication.** A month is published once it ends: the current month is not there, and
  Binance has stopped publishing some markets. A range with nothing published says which is
  the last month there is, instead of returning an empty series.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.adapters.providers.binance import dumps
from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import EXCHANGES, AssetClass, Instrument
from investinglab.domain.money import Currency
from investinglab.domain.rate_series import RateKind, RateSeries
from investinglab.domain.series import DataSource
from investinglab.ports.errors import (
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)

if TYPE_CHECKING:
    from investinglab.adapters.http import HttpClient

__all__ = ["FUNDING_DATASET", "PERPETUAL", "contract", "fetch_funding"]

PERPETUAL: Final = r"[A-Z0-9]{2,15}/[A-Z0-9]{2,10}:[A-Z0-9]{2,10}"
"""A perpetual swap: ``BASE/QUOTE:SETTLE`` (``BTC/USDT:USDT``)."""

FUNDING_DATASET: Final = "fundingRate"

_PERPETUAL = re.compile(PERPETUAL)
_LINEAR_SETTLEMENTS: Final = frozenset({"USDT", "USDC"})
_INVERSE_QUOTE: Final = "USD"
_COLUMNS: Final = ("calc_time", "last_funding_rate")
_DAY: Final = timedelta(days=1)
_NANOSECOND: Final = pd.Timedelta(1, "ns")
_MONTH = re.compile(r"(\d{4}-\d{2})\.zip$")


def contract(provider: str, symbol: str) -> tuple[str, str]:
    """The futures market and contract of a perpetual swap.

    ``BTC/USDT:USDT`` is ``("um", "BTCUSDT")``; ``BTC/USD:BTC`` is ``("cm", "BTCUSD_PERP")``.

    Raises:
        UnsupportedRequestError: If the symbol is not a perpetual swap Binance could list.
    """
    if not _PERPETUAL.fullmatch(symbol):
        raise UnsupportedRequestError(
            provider,
            f"{symbol!r} is not a perpetual swap written BASE/QUOTE:SETTLE in capitals "
            "(e.g. BTC/USDT:USDT)",
        )
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    if quote in _LINEAR_SETTLEMENTS and settle == quote:
        return "um", f"{base}{quote}"
    if quote == _INVERSE_QUOTE and settle == base:
        return "cm", f"{base}{quote}_PERP"
    raise UnsupportedRequestError(
        provider,
        f"{symbol}: Binance's perpetual swaps settle in the quote asset (USDT or USDC) or, "
        f"quoted in USD, in the base asset; not {base}/{quote} in {settle}",
    )


def _instrument(provider: str, symbol: str, name: str) -> Instrument:
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    try:
        currency = Currency(quote)
    except DomainError as error:
        raise UnsupportedRequestError(
            provider, f"{symbol}: prices quoted in {quote} cannot be represented ({error})"
        ) from error
    return Instrument(
        symbol=symbol,
        name=f"{base}/{quote} perpetual swap settled in {settle} (Binance {name})",
        asset_class=AssetClass.CRYPTO,
        currency=currency,
        exchange=EXCHANGES["CRYPTO"],
    )


def _midnight(day: date) -> pd.Timestamp:
    return pd.Timestamp(datetime(day.year, day.month, day.day, tzinfo=UTC))


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _previous_month(day: date) -> date:
    return (day.replace(day=1) - _DAY).replace(day=1)


def _payments(provider: str, key: str, text: str) -> pd.Series:
    """The rates of one monthly file, by settlement second in UTC."""
    rows = csv.reader(text.splitlines())
    header = next(rows, [])
    try:
        positions = [header.index(column) for column in _COLUMNS]
    except ValueError:
        raise ProviderDataError(provider, f"{key}: unexpected columns {header}") from None
    times: list[int] = []
    rates: list[float] = []
    for row in rows:
        if not row:
            continue
        try:
            times.append(int(row[positions[0]]))
            rates.append(float(row[positions[1]]))
        except (ValueError, IndexError):
            raise ProviderDataError(provider, f"{key}: unreadable row {row}") from None
    index = pd.to_datetime(times, unit="ms", utc=True).floor("s")
    return pd.Series(rates, index=index, dtype="float64")


async def fetch_funding(
    provider: str,
    listing: HttpClient,
    files: HttpClient,
    symbol: str,
    *,
    start: date | None,
    end: date | None,
    now: datetime,
) -> RateSeries:
    """The funding settled on a Binance perpetual swap between two UTC dates (inclusive).

    Raises:
        UnsupportedRequestError: If the symbol is not a perpetual swap Binance could list, or
            the range spans more than :data:`~dumps.MAX_FILES` months.
        SymbolNotFoundError: If Binance publishes no funding of that contract.
        ProviderDataError: If nothing is published in the range, or a file is damaged.
    """
    market, name = contract(provider, symbol)
    instrument = _instrument(provider, symbol, name)
    prefix = f"data/futures/{market}/monthly/{FUNDING_DATASET}/{name}/"
    stem = f"{prefix}{name}-{FUNDING_DATASET}-"
    # From the month before the range: the interval is inferred even from a single payment.
    after = f"{stem}{_month(_previous_month(start))}" if start else None
    until = f"{stem}{_month(end)}.zip" if end else None
    keys = await dumps.published(provider, listing, prefix, after=after, until=until)
    if not keys:
        # A file and its checksum come in pairs: two keys hold the first file, if any.
        if not await dumps.published(provider, listing, prefix, limit=1, page_size=2):
            raise SymbolNotFoundError(provider, f"{symbol}: Binance publishes no funding of {name}")
        latest = await _last_month(provider, listing, prefix)
        raise ProviderDataError(
            provider,
            f"{symbol}: no funding published between {start or 'the listing'} and "
            f"{end or 'now'}; Binance publishes each month once it ends (last: {latest})",
        )
    texts = await dumps.read_all(provider, files, keys)
    payments = pd.concat(
        [_payments(provider, key, text) for key, text in zip(keys, texts, strict=True)]
    ).sort_index(kind="stable")
    payments = payments[~payments.index.duplicated(keep="last")]
    first = _midnight(start) if start else None
    stop = min(_midnight(end) + _DAY, pd.Timestamp(now)) if end else pd.Timestamp(now)
    last = stop - _NANOSECOND
    inside = payments.loc[first:last]
    if inside.empty:
        raise ProviderDataError(
            provider,
            f"{symbol}: no funding published between {start or 'the listing'} and "
            f"{end or 'now'}; Binance publishes each month once it ends "
            f"(last: {payments.index[-1].date()})",
        )
    source = DataSource(provider, now, f"futures/{market}/monthly/{FUNDING_DATASET}")
    try:
        # The payments before the range give the interval; those after it are left out.
        rates = RateSeries(instrument, provider, RateKind.FUNDING, source, payments.loc[:last])
        return rates.between(first, last)
    except DomainError as error:
        raise ProviderDataError(provider, f"{symbol}: {error}") from error


async def _last_month(provider: str, listing: HttpClient, prefix: str) -> str:
    """The last month published under ``prefix`` (the listing is sorted)."""
    keys = await dumps.published(provider, listing, prefix)
    found = _MONTH.search(keys[-1]) if keys else None
    return found.group(1) if found else "none"
