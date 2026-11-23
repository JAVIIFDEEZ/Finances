"""Deribit perpetual swaps: the funding each hour accrued, from the public API (ADR-0032).

Deribit publishes the funding of its perpetuals without an API key, at
``/api/v2/public/get_funding_rate_history``. The adapter reads it through the shared
:class:`~investinglab.adapters.http.HttpClient` and returns a
:class:`~investinglab.domain.RateSeries` of kind ``funding``.

* **Symbols** follow the unified notation of perpetual swaps, ``BASE/QUOTE:SETTLE``:
  ``BTC/USD:BTC`` is the inverse perpetual settled in bitcoin (Deribit's ``BTC-PERPETUAL``)
  and ``BTC/USDC:USDC`` the linear one settled in USDC (``BTC_USDC-PERPETUAL``). Deribit
  lists no other kind, so a swap settled in USDT, or an inverse one settled in another
  asset, is refused instead of read from another swap.
* **Funding accrues every hour.** Deribit charges funding continuously and reports, for
  each hour, what it accrued (``interest_1h``), stamped at the end of the hour in UTC: that
  is the rate of a one-hour accrual period. Its ``interest_8h`` is the same funding over
  the last eight hours, quoted for comparison with venues that settle every 8 hours; it is
  not used, since adding it up would count each hour eight times. An hour inside Deribit's
  dampener band accrues exactly zero, and that zero is a real payment, not a gap. The sign
  is Deribit's: positive, longs pay shorts.
* **Windows.** Deribit answers at most 744 hours per call, so a range is read in windows
  of :data:`WINDOW`: one call per month of history, up to :data:`MAX_WINDOWS` (more than
  the whole history of its oldest perpetual, listed in 2018), :data:`PARALLEL` at a time.
  Without a start, windows are read back to the listing.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investinglab.adapters.http import HttpClient
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
from investinglab.ports.market_data import Canary, Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.ports.errors import ProviderError
    from investinglab.ports.market_data import RatesRequest

__all__ = [
    "BASE_URL",
    "DATASET",
    "INTERVAL",
    "MAX_WINDOWS",
    "NAME",
    "PARALLEL",
    "PERPETUAL",
    "WINDOW",
    "DeribitProvider",
    "explain_error",
    "http_client",
    "swap_id",
    "swap_instrument",
]

NAME: Final = "deribit"
BASE_URL: Final = "https://www.deribit.com"
DATASET: Final = "api/v2/public/get_funding_rate_history"

PERPETUAL: Final = r"[A-Z0-9]{2,15}/USDC?:[A-Z0-9]{2,10}"
"""The perpetuals Deribit lists: quoted in US dollars (inverse) or in USDC (linear)."""

INTERVAL: Final = pd.Timedelta(hours=1)
"""Accrual period of each rate: Deribit reports the funding of every hour."""

WINDOW: Final = timedelta(days=30)
"""Hours asked for per call: 720, under the 744 Deribit answers at most."""

MAX_WINDOWS: Final = 125
"""Most calls per request: about ten years of hourly funding, all Deribit has."""

PARALLEL: Final = 6
"""Windows asked for at once; the quota still spaces the calls."""

RATE_LIMITS: Final = (RateLimit(10, 1.0),)
"""Self-imposed quota: half the 20 public calls a second Deribit allows."""

INVALID_PARAMS: Final = -32602
"""JSON-RPC code Deribit answers with for an instrument it does not list."""

_PERPETUAL = re.compile(PERPETUAL)
_INVERSE_QUOTE: Final = "USD"
_LINEAR_QUOTE: Final = "USDC"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def swap_id(symbol: str) -> str:
    """Deribit's name of the perpetual ``symbol`` (``BTC/USD:BTC`` → ``BTC-PERPETUAL``).

    Raises:
        UnsupportedRequestError: If the symbol is not a perpetual Deribit could list: quoted
            in US dollars and settled in its base asset, or quoted and settled in USDC.
    """
    if not _PERPETUAL.fullmatch(symbol):
        raise UnsupportedRequestError(
            NAME,
            f"{symbol!r} is not a Deribit perpetual: written BASE/USD:BASE (inverse) or "
            "BASE/USDC:USDC (linear), in capitals",
        )
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    expected = base if quote == _INVERSE_QUOTE else _LINEAR_QUOTE
    if settle != expected:
        raise UnsupportedRequestError(
            NAME, f"{symbol}: Deribit settles its {base}/{quote} perpetual in {expected}"
        )
    return f"{base}-PERPETUAL" if quote == _INVERSE_QUOTE else f"{base}_USDC-PERPETUAL"


def swap_instrument(symbol: str) -> Instrument:
    """The instrument of a Deribit perpetual, priced in its quote asset."""
    swap = swap_id(symbol)
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    return Instrument(
        symbol=symbol,
        name=f"{base}/{quote} perpetual swap settled in {settle} (Deribit {swap})",
        asset_class=AssetClass.CRYPTO,
        currency=Currency(quote),
        exchange=EXCHANGES["CRYPTO"],
    )


def explain_error(response: httpx.Response, path: str) -> ProviderError | None:
    """Translate Deribit's JSON-RPC errors on HTTP errors.

    Only an unknown instrument needs it (``Invalid params`` on ``instrument_name``, whether
    Deribit calls it a wrong format or not open); throttling keeps the generic translation.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict) or error.get("code") != INVALID_PARAMS:
        return None
    data = error.get("data")
    if not isinstance(data, dict) or data.get("param") != "instrument_name":
        return None
    return SymbolNotFoundError(NAME, f"{path}: {data.get('reason') or 'unknown instrument'}")


def http_client(
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for Deribit: its base URL, quota and error documents."""
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=RATE_LIMITS,
        transport=transport,
        explain=explain_error,
    )


class _Accrual(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    timestamp: int
    interest_1h: float


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: list[_Accrual] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class DeribitProvider:
    """Funding of Deribit's perpetual swaps, hour by hour, without an API key.

    Args:
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); hours after it are left out.
        window: Time asked for per call, up to :data:`WINDOW` (shorter ones are for tests).

    Raises:
        DomainError: If ``window`` is not between an hour and :data:`WINDOW`.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
        window: timedelta = WINDOW,
    ) -> None:
        if not INTERVAL <= window <= WINDOW:
            raise DomainError(f"window must be between an hour and {WINDOW}, got {window}")
        self._client = client or http_client(timeout=timeout, retry=retry)
        self._clock = clock
        self._window = window

    @property
    def name(self) -> str:
        """Provider slug, also the venue of its rates."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Funding of perpetual swaps quoted in dollars or USDC (``BASE/QUOTE:SETTLE``)."""
        return ProviderCapabilities(
            canary=Canary(Dataset.HOLDING_RATES, "BTC/USD:BTC"),
            datasets=frozenset({Dataset.HOLDING_RATES}),
            asset_classes=frozenset({AssetClass.CRYPTO}),
            rate_limits=RATE_LIMITS,
            identifiers=PERPETUAL,
            rate_kinds=frozenset({RateKind.FUNDING}),
        )

    async def fetch_rates(self, request: RatesRequest) -> RateSeries:
        """Download the funding accrued each hour from ``request.start`` to ``end`` (UTC dates).

        Raises:
            UnsupportedRequestError: If the request is not for the funding of a perpetual
                Deribit lists, or needs more than :data:`MAX_WINDOWS` calls.
            SymbolNotFoundError: If Deribit does not list the perpetual.
            ProviderDataError: If the payload is malformed or nothing accrued in the range.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        if request.kind is not RateKind.FUNDING:
            raise UnsupportedRequestError(NAME, f"Deribit serves funding, not {request.kind.value}")
        if request.venue not in {None, NAME}:
            raise UnsupportedRequestError(
                NAME, f"Deribit serves its own rates, not {request.venue}'s"
            )
        instrument = swap_instrument(request.symbol)
        now = self._clock()
        first = _midnight(request.start) if request.start else None
        last = min(_midnight(request.end) + timedelta(days=1), now) if request.end else now
        if first is not None and first >= last:
            raise UnsupportedRequestError(NAME, f"{request.symbol}: the range has not started")
        rates = await self._accrued(swap_id(request.symbol), first, last)
        if rates.empty:
            raise ProviderDataError(
                NAME,
                f"{request.symbol}: no funding accrued between {request.start or 'the listing'} "
                f"and {request.end or 'now'} (before Deribit listed it?)",
            )
        try:
            return RateSeries(
                instrument,
                NAME,
                RateKind.FUNDING,
                DataSource(NAME, now, DATASET),
                rates,
                interval=INTERVAL,
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"{request.symbol}: {error}") from error

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

    async def _accrued(self, swap: str, first: datetime | None, last: datetime) -> pd.Series:
        """Funding of the hours stamped in ``[first, last)``, read in windows.

        With ``first`` every window is known beforehand, so they are counted before asking
        and read at once (:data:`PARALLEL` at a time, within the quota). Without it, they are
        read back in batches until one is empty: the hours before the listing.
        """
        if first is not None:
            bounds = self._bounds(first, last)
            if len(bounds) > MAX_WINDOWS:
                raise self._too_long(swap)
            return _series([a for w in await self._read(swap, bounds) for a in w], swap)
        accruals: list[_Accrual] = []
        cursor = last
        for _ in range(0, MAX_WINDOWS, PARALLEL):
            bounds = [
                (cursor - (step + 1) * self._window, cursor - step * self._window)
                for step in range(PARALLEL)
            ]
            for window in await self._read(swap, bounds):  # newest first
                if not window:
                    return _series(accruals, swap)
                accruals.extend(window)
            cursor = bounds[-1][0]
        raise self._too_long(swap)

    def _bounds(self, first: datetime, last: datetime) -> list[tuple[datetime, datetime]]:
        """The windows ``[floor, cursor)`` that tile ``[first, last)``, newest first.

        Counting stops one past :data:`MAX_WINDOWS`: enough to refuse a range too long.
        """
        bounds: list[tuple[datetime, datetime]] = []
        cursor = last
        while cursor > first and len(bounds) <= MAX_WINDOWS:
            floor = max(cursor - self._window, first)
            bounds.append((floor, cursor))
            cursor = floor
        return bounds

    async def _read(
        self, swap: str, bounds: list[tuple[datetime, datetime]]
    ) -> list[list[_Accrual]]:
        """The hours of each window, in the order given."""
        gate = asyncio.Semaphore(PARALLEL)

        async def one(floor: datetime, cursor: datetime) -> list[_Accrual]:
            # Deribit answers the hours stamped in (start, end]: one millisecond before each
            # bound asks for [floor, cursor), so every hour falls in exactly one window.
            params: dict[str, str | int] = {
                "instrument_name": swap,
                "start_timestamp": _milliseconds(floor) - 1,
                "end_timestamp": _milliseconds(cursor) - 1,
            }
            async with gate:
                return _window(await self._client.get_json(f"/{DATASET}", params), swap)

        return list(await asyncio.gather(*(one(floor, cursor) for floor, cursor in bounds)))

    def _too_long(self, swap: str) -> UnsupportedRequestError:
        return UnsupportedRequestError(
            NAME, f"{swap}: more than {MAX_WINDOWS} windows of {self._window}; ask for fewer days"
        )


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _milliseconds(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _window(raw: Any, swap: str) -> list[_Accrual]:  # noqa: ANN401 - decoded JSON
    try:
        response = _Response.model_validate(raw)
    except ValidationError as error:
        raise ProviderDataError(
            NAME, f"{swap}: unexpected funding payload ({error.error_count()} problems)"
        ) from None
    if response.error is not None:
        message = response.error.get("message") or "no detail"
        raise ProviderDataError(NAME, f"{swap}: Deribit error ({message})")
    return response.result


def _series(accruals: list[_Accrual], swap: str) -> pd.Series:
    """Rates by the end of their hour (UTC), oldest first, each hour once."""
    index = pd.to_datetime([accrual.timestamp for accrual in accruals], unit="ms", utc=True)
    rates = [accrual.interest_1h for accrual in accruals]
    series = pd.Series(rates, index=index, dtype="float64", name=swap).sort_index(kind="stable")
    return series[~series.index.duplicated(keep="last")]
