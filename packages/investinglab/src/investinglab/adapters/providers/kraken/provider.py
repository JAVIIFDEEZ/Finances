"""Kraken spot market: recent bars and their volume from the public OHLC endpoint (ADR-0032).

Kraken publishes OHLC bars without an API key at ``/0/public/OHLC``, but only the last 720
bars of each interval: two years of daily bars, a month of hourly ones. The adapter declares
that look-back, so the router asks Kraken only for ranges it can answer, typically as the
fallback of Binance or for pairs Binance does not list (``BTC/USD``, ``ETH/EUR``).

* **Pairs** are written ``BASE/QUOTE`` as everywhere (Kraken accepts ``BTC`` for its ``XBT``).
* **Flow** is the volume in units of the base asset, the number of trades and the value
  traded (Kraken's VWAP times the volume, which is what the VWAP is made of). Kraken does not
  report the aggressor side, so there is no delta.
* UTC bars, only finished ones, nothing invented (:mod:`~investinglab.adapters.providers.venues`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Self

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investinglab.adapters.http import HttpClient
from investinglab.adapters.providers import venues
from investinglab.domain.flow import FlowField
from investinglab.domain.instruments import AssetClass
from investinglab.domain.series import DataSource, PriceField
from investinglab.domain.time import Frequency
from investinglab.ports.errors import ProviderDataError, RateLimitedError, SymbolNotFoundError
from investinglab.ports.market_data import Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.series import PriceSeries
    from investinglab.ports.market_data import BarsRequest

__all__ = ["BASE_URL", "DATASET", "LOOKBACK_BARS", "NAME", "KrakenProvider", "http_client"]

NAME: Final = "kraken"
BASE_URL: Final = "https://api.kraken.com"
DATASET: Final = "0/public/OHLC"

LOOKBACK_BARS: Final = 720
"""Kraken answers the last 720 bars of each interval, never older ones."""

RATE_LIMITS: Final = (RateLimit(1, 1.0),)
"""Kraken's public endpoints allow about one call per second."""

INTERVALS: Final[dict[Frequency, int]] = {
    Frequency.MINUTE_1: 1,
    Frequency.MINUTE_5: 5,
    Frequency.MINUTE_15: 15,
    Frequency.MINUTE_30: 30,
    Frequency.HOUR_1: 60,
    Frequency.HOUR_4: 240,
    Frequency.DAY_1: 1440,
}
"""Frequencies downloaded natively, in Kraken's minutes; coarser ones come from daily bars."""

UNKNOWN_PAIR: Final = "EQuery:Unknown asset pair"
_THROTTLED: Final = ("EAPI:Rate limit exceeded", "EGeneral:Too many requests")
_MARGIN: Final = timedelta(days=1)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def http_client(
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for Kraken: its base URL and quota."""
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=RATE_LIMITS,
        transport=transport,
    )


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: list[str] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)


class KrakenProvider:
    """Recent price bars and volume of Kraken's spot pairs, without an API key.

    Args:
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); decides which bars are finished.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client or http_client(timeout=timeout, retry=retry)
        self._clock = clock

    @property
    def name(self) -> str:
        """Provider slug."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Bars and flow of spot pairs within Kraken's look-back of 720 bars."""
        lookback = {
            frequency: LOOKBACK_BARS * venues.bar_length(frequency).to_pytimedelta() - _MARGIN
            for frequency in INTERVALS
        }
        daily = lookback[Frequency.DAY_1]
        coarser = {f: daily for f in Frequency if not f.is_intraday and f not in INTERVALS}
        return ProviderCapabilities(
            datasets=frozenset({Dataset.BARS, Dataset.FLOW}),
            asset_classes=frozenset({AssetClass.CRYPTO}),
            frequencies=frozenset(Frequency),
            max_history={**lookback, **coarser},
            rate_limits=RATE_LIMITS,
            identifiers=venues.PAIR,
        )

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Download the recent bars of a pair (raw prices in the quote asset).

        Raises:
            UnsupportedRequestError: If the symbol is not a pair or its quote asset is not a
                known currency.
            SymbolNotFoundError: If Kraken does not list the pair.
            ProviderDataError: If the payload is malformed or fewer than three finished bars
                remain in the range.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        return venues.price_series(NAME, request, await self._download(request))

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        """Volume, trades and value traded of the same bars :meth:`fetch_bars` returns.

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
        instrument = venues.pair_instrument(NAME, request.symbol, "Kraken")
        base, quote = venues.split_pair(NAME, request.symbol)
        native = venues.native_frequency(NAME, request.frequency, INTERVALS)
        now = self._clock()
        first, last = venues.utc_bounds(NAME, request, now)
        params: dict[str, str | int] = {"pair": base + quote, "interval": INTERVALS[native]}
        if first is not None:
            params["since"] = int(first.timestamp())
        frame = _frame(await self._client.get_json(f"/{DATASET}", params), request.symbol)
        opens = pd.DatetimeIndex(frame.index)
        inside = opens < pd.Timestamp(last)
        if first is not None:
            inside &= opens >= pd.Timestamp(first)
        bars = venues.finished_bars(frame[inside], native, now)
        return venues.VenueBars(instrument, native, bars, DataSource(NAME, now, DATASET), now)


def _frame(raw: Any, symbol: str) -> pd.DataFrame:  # noqa: ANN401 - decoded JSON
    """Bars by UTC open time: OHLC, volume, trades and value traded."""
    try:
        response = _Response.model_validate(raw)
    except ValidationError as error:
        raise ProviderDataError(
            NAME, f"{symbol}: unexpected OHLC payload ({error.error_count()} problems)"
        ) from None
    if response.error:
        detail = f"{symbol}: {'; '.join(response.error)}"
        if UNKNOWN_PAIR in response.error:
            raise SymbolNotFoundError(NAME, detail)
        if any(message in _THROTTLED for message in response.error):
            raise RateLimitedError(NAME, detail)
        raise ProviderDataError(NAME, detail)
    series = [rows for key, rows in response.result.items() if key != "last"]
    if len(series) != 1 or not isinstance(series[0], list):
        raise ProviderDataError(NAME, f"{symbol}: expected the bars of one pair")
    try:
        table = np.array([[float(value) for value in row[:8]] for row in series[0]], dtype=float)
        table = table.reshape(len(series[0]), 8)
    except (TypeError, ValueError, IndexError) as error:
        raise ProviderDataError(NAME, f"{symbol}: unexpected OHLC row ({error})") from None
    if not np.isfinite(table).all():
        raise ProviderDataError(NAME, f"{symbol}: Kraken sent non-finite values")
    time, open_, high, low, close, vwap, volume, count = table.T
    return pd.DataFrame(
        {
            PriceField.OPEN: open_,
            PriceField.HIGH: high,
            PriceField.LOW: low,
            PriceField.CLOSE: close,
            FlowField.VOLUME.value: volume,
            FlowField.QUOTE_VOLUME.value: vwap * volume,
            FlowField.TRADES.value: count,
        },
        index=pd.to_datetime(time.astype("int64"), unit="s", utc=True),
    )
