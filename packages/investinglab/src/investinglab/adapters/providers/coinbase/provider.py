"""Coinbase Exchange: price bars and volume of its spot pairs from the public API (ADR-0032).

Coinbase publishes candles without an API key at ``/products/{BASE-QUOTE}/candles``, up to
300 per call, with the whole history of each pair. It serves pairs Binance does not list
(``BTC/USD``, ``ETH/EUR``) and is the second fallback of the crypto pairs after Kraken.

* **Pairs** are written ``BASE/QUOTE`` (``BTC/USD`` is Coinbase's ``BTC-USD``).
* **Frequencies**: 1 minute, 5, 15, 1 hour and 1 day natively; 30 minutes and 4 hours are
  built from the finer bars (only bins whose bars have all closed), weekly and coarser from
  daily ones.
* **Flow** is the volume in units of the base asset; Coinbase reports neither trades nor the
  aggressor side.
* UTC bars, only finished ones, nothing invented (:mod:`~investinglab.adapters.providers.venues`);
  at most :data:`MAX_PAGES` calls per request.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Self

import numpy as np
import pandas as pd

from investinglab.adapters.http import HttpClient
from investinglab.adapters.providers import venues
from investinglab.domain.errors import DomainError
from investinglab.domain.flow import FlowField
from investinglab.domain.instruments import AssetClass
from investinglab.domain.series import DataSource, PriceField
from investinglab.domain.time import Frequency
from investinglab.ports.errors import ProviderDataError, UnsupportedRequestError
from investinglab.ports.market_data import Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.series import PriceSeries
    from investinglab.ports.market_data import BarsRequest

__all__ = [
    "BASE_URL",
    "DATASET",
    "MAX_PAGES",
    "NAME",
    "PAGE_SIZE",
    "CoinbaseProvider",
    "http_client",
]

NAME: Final = "coinbase"
BASE_URL: Final = "https://api.exchange.coinbase.com"
DATASET: Final = "products/candles"

PAGE_SIZE: Final = 300
"""Most candles Coinbase returns per call."""

MAX_PAGES: Final = 50
"""Most calls per request: 15,000 bars (41 years of days, 10 days of minutes)."""

RATE_LIMITS: Final = (RateLimit(5, 1.0),)
"""Self-imposed: Coinbase allows 10 public calls per second."""

LISTING: Final = datetime(2015, 1, 1, tzinfo=UTC)
"""Start of a request for the whole history (Coinbase Exchange opened in 2015)."""

GRANULARITIES: Final[dict[Frequency, int]] = {
    Frequency.MINUTE_1: 60,
    Frequency.MINUTE_5: 300,
    Frequency.MINUTE_15: 900,
    Frequency.HOUR_1: 3_600,
    Frequency.DAY_1: 86_400,
}
"""Frequencies downloaded natively, in seconds."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def http_client(
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for Coinbase Exchange: its base URL and quota."""
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=RATE_LIMITS,
        transport=transport,
    )


class CoinbaseProvider:
    """Price bars and volume of Coinbase Exchange's spot pairs, without an API key.

    Args:
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); decides which bars are finished.
        page_size: Candles per call, up to :data:`PAGE_SIZE` (smaller pages are for tests).

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
        """Bars and volume of spot pairs (``BASE/QUOTE``) at every frequency."""
        return ProviderCapabilities(
            datasets=frozenset({Dataset.BARS, Dataset.FLOW}),
            asset_classes=frozenset({AssetClass.CRYPTO}),
            frequencies=frozenset(Frequency),
            rate_limits=RATE_LIMITS,
            identifiers=venues.PAIR,
        )

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Download the bars of a pair between ``request.start`` and ``request.end`` (UTC days).

        Raises:
            UnsupportedRequestError: If the symbol is not a pair, its quote asset is not a
                known currency or the range needs more than :data:`MAX_PAGES` calls.
            SymbolNotFoundError: If Coinbase does not list the pair (HTTP 404).
            ProviderDataError: If the payload is malformed or fewer than three finished bars
                remain.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        return venues.price_series(NAME, request, await self._download(request))

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        """The volume of the same bars :meth:`fetch_bars` returns.

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

    async def _download(self, request: BarsRequest) -> venues.VenueBars:
        instrument = venues.pair_instrument(NAME, request.symbol, "Coinbase")
        base, quote = venues.split_pair(NAME, request.symbol)
        native = venues.native_frequency(NAME, request.frequency, GRANULARITIES)
        now = self._clock()
        first, last = venues.utc_bounds(NAME, request, now)
        seconds = GRANULARITIES[native]
        windows = self._windows(first or LISTING, last, seconds)
        if len(windows) > MAX_PAGES:
            raise UnsupportedRequestError(
                NAME,
                f"{request.symbol}: more than {MAX_PAGES * self._page_size} {native.value} bars; "
                "ask for a shorter range",
            )
        path = f"/products/{base}-{quote}/candles"
        pages = []
        for start, end in windows:
            params: dict[str, str | int] = {
                "granularity": seconds,
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": end.isoformat().replace("+00:00", "Z"),
            }
            pages.append(_rows(await self._client.get_json(path, params), request.symbol))
        frame = venues.finished_bars(_frame(pages), native, now)
        return venues.VenueBars(instrument, native, frame, DataSource(NAME, now, DATASET), now)

    def _windows(
        self, first: datetime, last: datetime, seconds: int
    ) -> list[tuple[datetime, datetime]]:
        """Consecutive windows of at most one page each, covering ``[first, last)``.

        Coinbase includes both ends of a window, so each ends one bar before the next starts.
        """
        span = timedelta(seconds=seconds * self._page_size)
        count = math.ceil((last - first) / span)
        bar = timedelta(seconds=seconds)
        return [
            (first + i * span, min(first + (i + 1) * span, last) - bar)
            for i in range(count)
            if first + i * span < last
        ]


def _rows(raw: Any, symbol: str) -> np.ndarray:  # noqa: ANN401 - decoded JSON
    """One page of candles: time, low, high, open, close, volume (newest first)."""
    if not isinstance(raw, list):
        raise ProviderDataError(
            NAME, f"{symbol}: expected a list of candles, got {type(raw).__name__}"
        )
    try:
        table = np.array([[float(value) for value in row[:6]] for row in raw], dtype=float)
        table = table.reshape(len(raw), 6)  # a short row leaves a ragged table
    except (TypeError, ValueError, IndexError, KeyError) as error:
        raise ProviderDataError(NAME, f"{symbol}: unexpected candle ({error})") from None
    if not np.isfinite(table).all():
        raise ProviderDataError(NAME, f"{symbol}: Coinbase sent non-finite values")
    return table


def _frame(pages: list[np.ndarray]) -> pd.DataFrame:
    table = np.concatenate(pages) if pages else np.empty((0, 6))
    time, low, high, open_, close, volume = table.T
    return pd.DataFrame(
        {
            PriceField.OPEN: open_,
            PriceField.HIGH: high,
            PriceField.LOW: low,
            PriceField.CLOSE: close,
            FlowField.VOLUME.value: volume,
        },
        index=pd.to_datetime(time.astype("int64"), unit="s", utc=True),
    )
