"""Positioning in OKX's perpetual swaps, from its trading statistics (ADR-0042).

OKX publishes, without an API key, the history of the open interest of every swap and three
long/short ratios, each at its own endpoint and in the same shape: rows of
``[timestamp, value...]``, newest first, a hundred per call. :data:`ENDPOINTS` says what
each one gives; a new statistic is one more entry.

* **Granularity.** OKX keeps 5-minute rows for about three days, hourly rows for about a
  month and daily rows for longer. A request is read at the coarsest of those that is not
  coarser than asked (5 minutes up to 30, an hour up to 4, a day), and aggregated to its
  frequency by the domain.
* **Labels.** OKX stamps each row with the start of its period (today's daily row is the
  open interest now): the same convention as the domain's, so the period in progress is
  left out like an unfinished bar. OKX's days start at 16:00 UTC (midnight in Hong Kong):
  its daily rows are kept on its own days, not moved to UTC ones, so they are not the same
  periods as another venue's daily rows.
* **All or nothing.** A range that starts before what OKX keeps is not answered with its
  tail: OKX says so, and the router asks the next venue (Binance keeps 5-minute snapshots
  since 2021).
* **Value in dollars.** The open interest comes in the base asset and valued in US dollars
  (``oiUsd``), whatever the quote currency of the swap.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from investinglab.adapters.providers.okx.swaps import (
    NAME,
    OK,
    known_error,
    swap_id,
    swap_instrument,
)
from investinglab.domain.errors import DomainError
from investinglab.domain.money import USD
from investinglab.domain.positioning import PositioningField, PositioningSeries
from investinglab.domain.series import DataSource
from investinglab.domain.time import Frequency
from investinglab.ports.errors import ProviderDataError, UnsupportedRequestError

if TYPE_CHECKING:
    from investinglab.adapters.http import HttpClient
    from investinglab.ports.market_data import PositioningRequest

__all__ = ["ENDPOINTS", "FIELDS", "MAX_PAGES", "NATIVE", "Endpoint", "fetch_positioning"]

PAGE: Final = 100
"""Most rows OKX returns per call."""

MAX_PAGES: Final = 30
"""Most calls per endpoint and request: a year of daily rows, or 125 days of hourly ones."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A statistic of OKX: where it is and which field each column after the time is."""

    path: str
    columns: tuple[PositioningField | None, ...]


ENDPOINTS: Final = (  # the open interest first: it is read before the rest
    Endpoint(
        "api/v5/rubik/stat/contracts/open-interest-history",
        # contracts, base asset, US dollars: the contracts' size differs by swap
        (None, PositioningField.OPEN_INTEREST, PositioningField.OPEN_INTEREST_VALUE),
    ),
    Endpoint(
        "api/v5/rubik/stat/contracts/long-short-account-ratio-contract",
        (PositioningField.LONG_SHORT_ACCOUNTS,),
    ),
    Endpoint(
        "api/v5/rubik/stat/contracts/long-short-account-ratio-contract-top-trader",
        (PositioningField.TOP_LONG_SHORT_ACCOUNTS,),
    ),
    Endpoint(
        "api/v5/rubik/stat/contracts/long-short-position-ratio-contract-top-trader",
        (PositioningField.TOP_LONG_SHORT_POSITIONS,),
    ),
)
"""The statistics read, in order."""

FIELDS: Final = frozenset(
    field for endpoint in ENDPOINTS for field in endpoint.columns if field is not None
)
"""Every field OKX gives."""

NATIVE: Final = {
    Frequency.MINUTE_5: (Frequency.MINUTE_5, "5m"),
    Frequency.MINUTE_15: (Frequency.MINUTE_5, "5m"),
    Frequency.MINUTE_30: (Frequency.MINUTE_5, "5m"),
    Frequency.HOUR_1: (Frequency.HOUR_1, "1H"),
    Frequency.HOUR_4: (Frequency.HOUR_1, "1H"),
    Frequency.DAY_1: (Frequency.DAY_1, "1D"),
}
"""The granularity OKX is asked for at each frequency, and its name for it."""

_DAY: Final = timedelta(days=1)
_STEP: Final = {
    Frequency.MINUTE_5: pd.Timedelta(minutes=5),
    Frequency.HOUR_1: pd.Timedelta(hours=1),
    Frequency.DAY_1: pd.Timedelta(days=1),
}
"""Length of each granularity OKX is read at: a range may start mid-period."""


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    msg: str = ""
    data: list[list[str]] = []


def _rows(raw: Any, swap: str, endpoint: Endpoint) -> list[list[str]]:  # noqa: ANN401 - JSON
    try:
        response = _Response.model_validate(raw)
    except ValidationError as error:
        raise ProviderDataError(
            NAME, f"{swap}: unexpected {endpoint.path} payload ({error.error_count()} problems)"
        ) from None
    if response.code != OK:
        known = known_error(response.code, response.msg or "no detail", f"/{endpoint.path}")
        raise known or ProviderDataError(
            NAME, f"{swap}: OKX error {response.code} ({response.msg})"
        )
    width = len(endpoint.columns) + 1
    if any(len(row) < width for row in response.data):
        raise ProviderDataError(NAME, f"{swap}: rows of {endpoint.path} shorter than {width}")
    return response.data


@dataclass(frozen=True, slots=True)
class _Window:
    """What is read of every statistic: one swap, at one granularity, between two instants."""

    swap: str
    period: str
    begin: int
    end: int
    """Milliseconds since the epoch, both inclusive."""


async def _read(client: HttpClient, endpoint: Endpoint, window: _Window) -> pd.DataFrame:
    """Every row of one statistic in ``window``."""
    swap, begin = window.swap, window.begin
    rows: list[list[str]] = []
    cursor = window.end
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {
            "instId": swap,
            "period": window.period,
            "begin": begin,
            "end": cursor,
            "limit": PAGE,
        }
        page = _rows(await client.get_json(f"/{endpoint.path}", params), swap, endpoint)
        rows.extend(page)
        oldest = min((int(row[0]) for row in page), default=begin)
        if len(page) < PAGE or oldest <= begin:
            break
        cursor = oldest - 1
    else:
        raise UnsupportedRequestError(
            NAME,
            f"{swap}: more than {MAX_PAGES * PAGE} rows of {endpoint.path}; ask for fewer days",
        )
    try:
        index = pd.to_datetime([int(row[0]) for row in rows], unit="ms", utc=True)
        data = {
            field.value: [float(row[position + 1]) for row in rows]
            for position, field in enumerate(endpoint.columns)
            if field is not None
        }
    except ValueError:
        raise ProviderDataError(
            NAME, f"{swap}: a value of {endpoint.path} is not a number"
        ) from None
    frame = pd.DataFrame(data, index=index).sort_index(kind="stable")
    return frame[~frame.index.duplicated(keep="last")]


def _milliseconds(moment: pd.Timestamp) -> int:
    return int(moment.timestamp() * 1000)


def _midnight(day: date) -> pd.Timestamp:
    return pd.Timestamp(datetime(day.year, day.month, day.day, tzinfo=UTC))


async def fetch_positioning(
    client: HttpClient, request: PositioningRequest, *, now: datetime
) -> PositioningSeries:
    """The positioning snapshots of an OKX perpetual swap, at ``request.frequency``.

    Raises:
        UnsupportedRequestError: If the symbol is not a swap OKX settles that way, the
            frequency is not one positioning is read at, or the range needs too many calls.
        SymbolNotFoundError: If OKX does not list the swap.
        ProviderDataError: If OKX keeps nothing in the range, or a payload is malformed.
    """
    if request.frequency not in NATIVE:
        raise UnsupportedRequestError(
            NAME, f"OKX's positioning is not read at {request.frequency.value}"
        )
    swap = swap_id(request.symbol)
    instrument = swap_instrument(request.symbol)
    native, period = NATIVE[request.frequency]
    moment = pd.Timestamp(now)
    begin = _midnight(request.start) if request.start else moment - timedelta(days=30)
    stop = min(_midnight(request.end) + _DAY, moment) if request.end else moment
    window = _Window(swap, period, _milliseconds(begin), _milliseconds(stop) - 1)
    # The open interest first: an unknown swap is told by one call, not by four at once.
    first_frame = await _read(client, ENDPOINTS[0], window)
    others = await asyncio.gather(*(_read(client, endpoint, window) for endpoint in ENDPOINTS[1:]))
    frames = [first_frame, *others]
    frame = pd.concat(frames, axis=1, sort=True).dropna(axis="columns", how="all")
    frame = frame.loc[begin : stop - pd.Timedelta(1, "ns")]
    if frame.empty:
        raise ProviderDataError(
            NAME,
            f"{request.symbol}: OKX keeps no {period} positioning between "
            f"{request.start or begin.date()} and {request.end or 'now'} (5-minute rows for "
            "about three days, hourly ones for about a month)",
        )
    first = pd.Timestamp(frame.index[0])
    if request.start is not None and first > begin + _STEP[native]:
        # Less than was asked: the venue with the older history must answer, not this one.
        raise ProviderDataError(
            NAME,
            f"{request.symbol}: OKX keeps {period} positioning from {first.isoformat()}, "
            f"after the {request.start} asked for",
        )
    source = DataSource(NAME, now, "api/v5/rubik/stat")
    valued = PositioningField.OPEN_INTEREST_VALUE.value in frame.columns
    try:
        series = PositioningSeries(
            instrument, NAME, source, native, frame, value_currency=USD if valued else None
        )
        return series.resample(request.frequency).finished(now)
    except DomainError as error:
        raise ProviderDataError(NAME, f"{request.symbol}: {error}") from error
