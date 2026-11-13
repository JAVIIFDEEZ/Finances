"""Binance spot market: price bars and trade flow from the public market-data API (ADR-0032).

Binance publishes its spot market data without an API key. The adapter reads it from
``data-api.binance.vision``, the mirror of the ``/api/v3`` market endpoints that answers
from every country (``api.binance.com`` refuses some of them with HTTP 451), through the
shared :class:`~investinglab.adapters.http.HttpClient`. One endpoint, ``/api/v3/klines``,
gives both the bars and their flow: units and value traded, number of trades and the
taker (aggressor) buying of every bar.

What the adapter guarantees, beyond the domain's validation:

* **Pairs.** Symbols are written ``BASE/QUOTE`` (``BTC/USDT``, ``ETH/BTC``). The quote
  asset is the currency of the prices, so it must be a currency the domain knows; any
  other pair is refused before asking Binance.
* **Times.** Bars open on UTC boundaries, as in any 24/7 market: daily bars are labelled
  with their UTC date and intraday bars keep their open time in UTC. Weekly and coarser
  bars are aggregated from daily bars by the domain.
* **Only finished bars, nothing invented.** The bar in progress is left out. Binance reports
  every bar of a listed pair, with zero volume when nothing traded; a bar it does not
  report (a maintenance window) stays absent.
* **Bounded downloads.** At most :data:`MAX_PAGES` pages of :data:`PAGE_SIZE` bars per
  request: a longer history must be asked for in shorter ranges.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Self

import numpy as np
import pandas as pd

from investinglab.adapters.http import HttpClient, retry_after
from investinglab.adapters.providers import venues
from investinglab.domain.errors import DomainError
from investinglab.domain.flow import FlowField
from investinglab.domain.instruments import AssetClass
from investinglab.domain.series import DataSource, PriceField
from investinglab.domain.time import Frequency
from investinglab.ports.errors import (
    BannedError,
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from investinglab.ports.market_data import Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.series import PriceSeries
    from investinglab.ports.errors import ProviderError
    from investinglab.ports.market_data import BarsRequest

__all__ = [
    "BASE_URL",
    "DATASET",
    "MAX_PAGES",
    "NAME",
    "PAGE_SIZE",
    "PAIR",
    "BinanceProvider",
    "explain_error",
    "http_client",
    "split_pair",
]

NAME: Final = "binance"
BASE_URL: Final = "https://data-api.binance.vision"
DATASET: Final = "api/v3/klines"

PAIR: Final = venues.PAIR
"""A spot pair: base and quote assets separated by a slash (``BTC/USDT``)."""

PAGE_SIZE: Final = 1_000
"""Most bars Binance returns per call."""

MAX_PAGES: Final = 50
"""Most calls per request (50,000 bars): a longer history is asked for in shorter ranges."""

RATE_LIMITS: Final = (RateLimit(10, 1.0), RateLimit(1_000, 60.0))
"""Self-imposed quotas: a klines call weighs 2 and an address may spend 6,000 a minute."""

INVALID_SYMBOL: Final = -1121
"""Binance's error code for a pair it does not list."""

INTERVALS: Final[dict[Frequency, str]] = {
    Frequency.MINUTE_1: "1m",
    Frequency.MINUTE_5: "5m",
    Frequency.MINUTE_15: "15m",
    Frequency.MINUTE_30: "30m",
    Frequency.HOUR_1: "1h",
    Frequency.HOUR_4: "4h",
    Frequency.DAY_1: "1d",
}
"""Frequencies downloaded natively; coarser ones are aggregated from daily bars."""

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

# Positions in a kline row: open time, OHLC, volume, close time, value traded, trades and
# taker buying (units and value). Later positions are ignored.
_COLUMNS: Final[dict[str, int]] = {
    "open_time": 0,
    PriceField.OPEN: 1,
    PriceField.HIGH: 2,
    PriceField.LOW: 3,
    PriceField.CLOSE: 4,
    FlowField.VOLUME: 5,
    FlowField.QUOTE_VOLUME: 7,
    FlowField.TRADES: 8,
    FlowField.BUY_VOLUME: 9,
    FlowField.BUY_QUOTE_VOLUME: 10,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def split_pair(symbol: str) -> tuple[str, str]:
    """Base and quote assets of a ``BASE/QUOTE`` symbol.

    Raises:
        UnsupportedRequestError: If the symbol is not written as a pair.
    """
    return venues.split_pair(NAME, symbol)


def explain_error(response: httpx.Response, path: str) -> ProviderError | None:
    """Translate the error documents Binance answers (``{"code": ..., "msg": ...}``).

    An unknown pair is HTTP 400 with code -1121, and HTTP 418 means the address is banned
    for having exceeded the limits. ``None`` leaves the generic translation by status.
    """
    status = response.status_code
    where = f"HTTP {status} on {path}"
    if status == 418:  # noqa: PLR2004 - Binance's ban status
        return BannedError(
            NAME,
            f"{where}: Binance banned this address for exceeding its limits",
            retry_after(response),
        )
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    code, message = body.get("code"), str(body.get("msg") or "no detail")
    if code == INVALID_SYMBOL:
        return SymbolNotFoundError(NAME, f"{where}: {message}")
    if status == 400:  # noqa: PLR2004
        return UnsupportedRequestError(NAME, f"{where}: {message} (code {code})")
    return None


def http_client(
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for Binance: its base URL, quotas and error documents."""
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=RATE_LIMITS,
        transport=transport,
        explain=explain_error,
    )


class BinanceProvider:
    """Price bars and trade flow of Binance's spot pairs, without an API key.

    Args:
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); decides which bars are finished.
        page_size: Bars per call, up to :data:`PAGE_SIZE` (smaller pages are for tests).

    Raises:
        DomainError: If ``page_size`` is out of range.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
        page_size: int = PAGE_SIZE,
    ) -> None:
        if not 1 <= page_size <= PAGE_SIZE:
            raise DomainError(f"page_size must be between 1 and {PAGE_SIZE}, got {page_size}")
        self._client = client or http_client(timeout=timeout, retry=retry)
        self._clock = clock
        self._page_size = page_size

    @property
    def name(self) -> str:
        """Provider slug."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Bars and flow of spot pairs (``BASE/QUOTE``) at every frequency."""
        return ProviderCapabilities(
            datasets=frozenset({Dataset.BARS, Dataset.FLOW}),
            asset_classes=frozenset({AssetClass.CRYPTO}),
            frequencies=frozenset(Frequency),
            rate_limits=RATE_LIMITS,
            identifiers=PAIR,
        )

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Download the bars of a pair between ``request.start`` and ``request.end`` (UTC dates).

        Prices are as traded (Binance adjusts nothing) and the volume is in units of the base
        asset.

        Raises:
            UnsupportedRequestError: If the symbol is not a pair, its quote asset is not a
                known currency or the range needs more than :data:`MAX_PAGES` calls.
            SymbolNotFoundError: If Binance does not list the pair.
            ProviderDataError: If the payload is malformed or fewer than three finished
                bars remain.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        return venues.price_series(NAME, request, await self._download(request))

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        """Download the flow of the same bars :meth:`fetch_bars` returns.

        Every bar carries the units and value traded, the number of trades and the taker
        buying, so delta and CVD are available.

        Raises:
            ProviderError: As :meth:`fetch_bars`.
        """
        return venues.flow_series(NAME, request, await self._download(request))

    async def aclose(self) -> None:
        """Close the HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ── Internals ────────────────────────────────────────────────────

    async def _download(self, request: BarsRequest) -> venues.VenueBars:
        instrument = venues.pair_instrument(NAME, request.symbol, "Binance")
        base, quote = split_pair(request.symbol)
        native = venues.native_frequency(NAME, request.frequency, INTERVALS)
        now = self._clock()
        first, last = venues.utc_bounds(NAME, request, now)
        rows = await self._klines(base + quote, native, first or _EPOCH, last)
        frame = venues.finished_bars(_frame(rows, request.symbol), native, now)
        return venues.VenueBars(instrument, native, frame, DataSource(NAME, now, DATASET), now)

    async def _klines(
        self, pair: str, native: Frequency, first: datetime, last: datetime
    ) -> list[np.ndarray]:
        """Rows of every page from ``first`` (inclusive) to ``last`` (exclusive)."""
        step = _step(native)
        end = _milliseconds(last) - 1
        cursor = _milliseconds(first)
        pages: list[np.ndarray] = []
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {
                "symbol": pair,
                "interval": INTERVALS[native],
                "startTime": cursor,
                "endTime": end,
                "limit": self._page_size,
            }
            page = _rows(await self._client.get_json(f"/{DATASET}", params), pair)
            pages.append(page)
            if len(page) < self._page_size:
                return pages
            cursor = int(page[-1, 0]) + step
            if cursor > end:
                return pages
        raise UnsupportedRequestError(
            NAME,
            f"{pair}: more than {MAX_PAGES * self._page_size} {INTERVALS[native]} bars; "
            "ask for a shorter range",
        )


def _milliseconds(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _step(native: Frequency) -> int:
    """Length of a bar in milliseconds."""
    return int(venues.bar_length(native) / pd.Timedelta(milliseconds=1))


# ──────────────────────────────────────────────────────────────────────
# Payload → bars and flow
# ──────────────────────────────────────────────────────────────────────


def _rows(raw: Any, pair: str) -> np.ndarray:  # noqa: ANN401 - decoded JSON
    """The numeric columns of one page of klines, one row per bar."""
    if not isinstance(raw, list):
        raise ProviderDataError(
            NAME, f"{pair}: expected a list of klines, got {type(raw).__name__}"
        )
    positions = list(_COLUMNS.values())
    try:
        table = np.array(
            [[float(row[position]) for position in positions] for row in raw], dtype="float64"
        )
    except (TypeError, ValueError, IndexError, KeyError) as error:
        raise ProviderDataError(NAME, f"{pair}: unexpected kline ({error})") from None
    return table.reshape(len(raw), len(positions))


def _frame(pages: list[np.ndarray], symbol: str) -> pd.DataFrame:
    """Bars indexed by their open time in UTC, sorted and without repeated bars."""
    table = np.concatenate(pages)
    columns = list(_COLUMNS)
    frame = pd.DataFrame(table[:, 1:], columns=columns[1:])
    frame.index = pd.to_datetime(table[:, 0].astype("int64"), unit="ms", utc=True)
    if not np.isfinite(table).all():
        raise ProviderDataError(NAME, f"{symbol}: Binance sent non-finite values")
    ordered = frame.sort_index(kind="stable")
    return ordered[~ordered.index.duplicated(keep="last")]
