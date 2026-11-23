"""OKX perpetual swaps: funding (ADR-0032) and positioning (ADR-0042) from the public API.

OKX publishes the funding settled on each perpetual swap without an API key, at
``/api/v5/public/funding-rate-history``. The adapter reads it through the shared
:class:`~investinglab.adapters.http.HttpClient` and returns a
:class:`~investinglab.domain.RateSeries` of kind ``funding``.

* **Symbols** follow the unified notation of perpetual swaps, ``BASE/QUOTE:SETTLE``:
  ``BTC/USDT:USDT`` is the linear swap settled in USDT (OKX's ``BTC-USDT-SWAP``) and
  ``BTC/USD:BTC`` the inverse one settled in bitcoin (``BTC-USD-SWAP``). A settlement
  currency OKX does not use for that pair is refused instead of read from another swap.
* **The rate actually settled** (``realizedRate``) is used, indexed by the settlement
  instant in UTC; ``fundingRate`` only when OKX does not report the former. The sign is
  OKX's: positive, longs pay shorts.
* **History.** OKX keeps about three months of funding; a request for older days has no
  payments, and says so instead of returning an empty series.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investinglab.adapters.http import HttpClient
from investinglab.adapters.providers.okx import positioning
from investinglab.adapters.providers.okx.swaps import (
    INSTRUMENT_NOT_FOUND,
    NAME,
    OK,
    PERPETUAL,
    known_error,
    swap_id,
    swap_instrument,
)
from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import AssetClass
from investinglab.domain.rate_series import RateKind, RateSeries
from investinglab.domain.series import DataSource
from investinglab.ports.errors import (
    ProviderDataError,
    UnsupportedRequestError,
)
from investinglab.ports.market_data import Canary, Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.domain.positioning import PositioningSeries
    from investinglab.ports.errors import ProviderError
    from investinglab.ports.market_data import PositioningRequest, RatesRequest

__all__ = [
    "BASE_URL",
    "DATASET",
    "MAX_PAGES",
    "NAME",
    "PAGE_SIZE",
    "PERPETUAL",
    "OkxProvider",
    "explain_error",
    "http_client",
    "swap_id",
    "swap_instrument",
]

BASE_URL: Final = "https://www.okx.com"
DATASET: Final = "api/v5/public/funding-rate-history"

PAGE_SIZE: Final = 100
"""Most payments OKX returns per call."""

MAX_PAGES: Final = 40
"""Most calls per request: OKX's three months of hourly funding fit in 23."""

RATE_LIMITS: Final = (RateLimit(4, 1.0),)
"""Self-imposed quota: OKX allows 10 calls every 2 seconds per address on this endpoint."""


"""OKX settles its swaps quoted in US dollars in the base asset (inverse swaps)."""
_DAY: Final = timedelta(days=1)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def explain_error(response: httpx.Response, path: str) -> ProviderError | None:
    """Translate OKX's error documents (``{"code": ..., "msg": ...}``) on HTTP errors.

    Only an unknown swap needs it; throttling keeps the generic translation, which honours
    ``Retry-After``.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or str(body.get("code")) != INSTRUMENT_NOT_FOUND:
        return None
    return known_error(INSTRUMENT_NOT_FOUND, str(body.get("msg") or "no detail"), path)


def http_client(
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for OKX: its base URL, quota and error documents."""
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=RATE_LIMITS,
        transport=transport,
        explain=explain_error,
    )


class _Payment(BaseModel):
    model_config = ConfigDict(frozen=True)

    inst_id: str = Field(alias="instId")
    funding_time: int = Field(alias="fundingTime")
    funding_rate: str = Field(alias="fundingRate")
    realized_rate: str = Field("", alias="realizedRate")

    def rate(self) -> float:
        return float(self.realized_rate or self.funding_rate)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    msg: str = ""
    data: list[_Payment] = Field(default_factory=list)


class OkxProvider:
    """Funding of OKX's perpetual swaps, without an API key.

    Args:
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); payments after it are left out.
        page_size: Payments per call, up to :data:`PAGE_SIZE` (smaller pages are for tests).

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
        """Provider slug, also the venue of its rates."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Funding and positioning of perpetual swaps (``BASE/QUOTE:SETTLE``)."""
        return ProviderCapabilities(
            canary=Canary(Dataset.HOLDING_RATES, "BTC/USDT:USDT"),
            datasets=frozenset({Dataset.HOLDING_RATES, Dataset.POSITIONING}),
            asset_classes=frozenset({AssetClass.CRYPTO}),
            rate_limits=RATE_LIMITS,
            identifiers=PERPETUAL,
            frequencies_by_dataset={Dataset.POSITIONING: frozenset(positioning.NATIVE)},
            rate_kinds=frozenset({RateKind.FUNDING}),
            positioning_fields=positioning.FIELDS,
        )

    async def fetch_positioning(self, request: PositioningRequest) -> PositioningSeries:
        """Read the open interest and long/short ratios of a swap (see :mod:`.positioning`).

        Raises:
            UnsupportedRequestError: If the request is not for a swap OKX lists, at a frequency
                positioning is read at, or needs too many calls.
            SymbolNotFoundError: If OKX does not list the swap.
            ProviderDataError: If OKX keeps nothing in the range, or a payload is malformed.
        """
        if request.venue not in {None, NAME}:
            raise UnsupportedRequestError(
                NAME, f"OKX serves its own positioning, not {request.venue}'s"
            )
        return await positioning.fetch_positioning(self._client, request, now=self._clock())

    async def fetch_rates(self, request: RatesRequest) -> RateSeries:
        """Download the funding settled between ``request.start`` and ``end`` (UTC dates).

        Raises:
            UnsupportedRequestError: If the request is not for the funding of a perpetual swap
                on OKX, or needs more than :data:`MAX_PAGES` calls.
            SymbolNotFoundError: If OKX does not list the swap.
            ProviderDataError: If the payload is malformed or no payment settled in the range.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        if request.kind is not RateKind.FUNDING:
            raise UnsupportedRequestError(NAME, f"OKX serves funding, not {request.kind.value}")
        if request.venue not in {None, NAME}:
            raise UnsupportedRequestError(NAME, f"OKX serves its own rates, not {request.venue}'s")
        instrument = swap_instrument(request.symbol)
        now = self._clock()
        first = _midnight(request.start) if request.start else None
        last = min(_midnight(request.end) + _DAY, now) if request.end else now
        payments = await self._payments(swap_id(request.symbol), first, last)
        start = pd.Timestamp(first) if first else None
        end = pd.Timestamp(last) - _NANOSECOND
        if payments.loc[start:end].empty:
            raise ProviderDataError(
                NAME,
                f"{request.symbol}: no funding settled between {request.start or 'the listing'} "
                f"and {request.end or 'now'} (OKX keeps about three months)",
            )
        try:
            # The whole download, with the payment before the range, gives the interval.
            rates = RateSeries(
                instrument, NAME, RateKind.FUNDING, DataSource(NAME, now, DATASET), payments
            )
            return rates.between(start, end)
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

    async def _payments(self, swap: str, first: datetime | None, last: datetime) -> pd.Series:
        """Rates settled before ``last``, back to one payment before ``first`` (or all).

        The payment before ``first`` is kept so that the accrual interval can be inferred
        even when the range holds a single payment. Pages are read until one is empty or
        reaches ``first``: a short page does not prove the history ended, since OKX may
        cap the page below the size asked for.
        """
        floor = _milliseconds(first) if first else None
        cursor = _milliseconds(last)
        payments: list[_Payment] = []
        for _ in range(MAX_PAGES):
            params: dict[str, str | int] = {
                "instId": swap,
                "after": cursor,
                "limit": self._page_size,
            }
            page = _page(await self._client.get_json(f"/{DATASET}", params), swap)
            if not page:
                return _series(payments, swap)
            payments.extend(page)
            cursor = min(payment.funding_time for payment in page)
            if floor is not None and cursor < floor:
                return _series(payments, swap)
        raise UnsupportedRequestError(
            NAME, f"{swap}: more than {MAX_PAGES * self._page_size} payments; ask for fewer days"
        )


_NANOSECOND: Final = pd.Timedelta(1, "ns")


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _milliseconds(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _page(raw: Any, swap: str) -> list[_Payment]:  # noqa: ANN401 - decoded JSON
    try:
        response = _Response.model_validate(raw)
    except ValidationError as error:
        raise ProviderDataError(
            NAME, f"{swap}: unexpected funding payload ({error.error_count()} problems)"
        ) from None
    if response.code != OK:
        known = known_error(response.code, response.msg or "no detail", f"/{DATASET}")
        raise known or ProviderDataError(
            NAME, f"{swap}: OKX error {response.code} ({response.msg})"
        )
    strangers = sorted({payment.inst_id for payment in response.data} - {swap})
    if strangers:
        raise ProviderDataError(NAME, f"{swap}: OKX answered the funding of {strangers}")
    return response.data


def _series(payments: list[_Payment], swap: str) -> pd.Series:
    """Rates by settlement instant (UTC), oldest first, each instant once."""
    try:
        rates = [payment.rate() for payment in payments]
    except ValueError:
        raise ProviderDataError(NAME, f"{swap}: a funding rate is not a number") from None
    index = pd.to_datetime([payment.funding_time for payment in payments], unit="ms", utc=True)
    series = pd.Series(rates, index=index, dtype="float64").sort_index(kind="stable")
    return series[~series.index.duplicated(keep="last")]
