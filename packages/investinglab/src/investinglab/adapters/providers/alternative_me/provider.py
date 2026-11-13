"""alternative.me: the crypto Fear & Greed Index as a daily economic series.

The index (0 = extreme fear, 100 = extreme greed) summarises volatility, momentum, social
media, dominance and search trends of the crypto market. alternative.me publishes it once a
day, without an API key, at ``https://api.alternative.me/fng/``. The adapter reads it through
the shared :class:`~investinglab.adapters.http.HttpClient` and returns an
:class:`~investinglab.domain.EconomicSeries` with id ``FNG``.

* **Point in time.** Each value is dated by the UTC day it describes and became public that
  same day (alternative.me computes it at 00:00 UTC), so it is never known earlier.
* **Nothing invented.** A day alternative.me skipped stays absent; a value outside 0-100 is
  a malformed answer, not a market reading.
* **Only what is asked.** With a start date the request asks for the days since then, not
  the whole history (one value per day since February 2018).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from investinglab.adapters.http import HttpClient
from investinglab.domain.economic import EconomicSeries
from investinglab.domain.errors import DomainError
from investinglab.domain.series import DataSource
from investinglab.domain.time import Frequency
from investinglab.ports.errors import ProviderDataError, SymbolNotFoundError
from investinglab.ports.market_data import Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.ports.market_data import EconomicRequest

__all__ = ["BASE_URL", "DATASET", "FEAR_GREED", "NAME", "AlternativeMeProvider", "http_client"]

NAME: Final = "alternative_me"
BASE_URL: Final = "https://api.alternative.me"
DATASET: Final = "fng"
FEAR_GREED: Final = "FNG"
"""Series id of the crypto Fear & Greed Index."""

TITLE: Final = "Crypto Fear & Greed Index"
UNITS: Final = "Index 0-100 (0 = extreme fear, 100 = extreme greed)"
RATE_LIMITS: Final = (RateLimit(60, 60.0),)
"""alternative.me allows 60 requests a minute."""

_SCALE: Final = (0.0, 100.0)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def http_client(
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for alternative.me: its base URL and quota."""
    return HttpClient(
        NAME,
        base_url=BASE_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=RATE_LIMITS,
        transport=transport,
    )


class _Reading(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float
    timestamp: int


class _Metadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: str | None = None


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[_Reading] = Field(default_factory=list)
    metadata: _Metadata = Field(default_factory=_Metadata)


class AlternativeMeProvider:
    """The crypto Fear & Greed Index, without an API key.

    Args:
        client: HTTP client to use; :func:`http_client` by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); decides how many days to ask for.
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
        """The ``FNG`` series only."""
        return ProviderCapabilities(
            datasets=frozenset({Dataset.ECONOMIC}),
            rate_limits=RATE_LIMITS,
            identifiers=FEAR_GREED,
        )

    async def fetch_economic_series(self, request: EconomicRequest) -> EconomicSeries:
        """Download the index between ``request.start`` and ``request.end`` (UTC days).

        Every vintage mode gets the same values: the index is never revised.

        Raises:
            SymbolNotFoundError: For any series but ``FNG``.
            ProviderDataError: If the payload is malformed, reports an error or has no value
                in the range.
            ProviderError: Any other failure, translated by the HTTP client.
        """
        if request.series_id != FEAR_GREED:
            raise SymbolNotFoundError(NAME, f"alternative.me only publishes {FEAR_GREED}")
        now = self._clock()
        days = 0 if request.start is None else max((now.date() - request.start).days + 1, 1)
        raw = await self._client.get_json(f"/{DATASET}/", {"limit": days, "format": "json"})
        frame = _observations(raw)
        dates = frame["observation_date"]
        keep = pd.Series(data=True, index=frame.index)
        if request.start is not None:
            keep &= dates >= pd.Timestamp(request.start)
        if request.end is not None:
            keep &= dates <= pd.Timestamp(request.end)
        inside = frame[keep]
        if inside.empty:
            raise ProviderDataError(
                NAME,
                f"no Fear & Greed value between {request.start or 'February 2018'} "
                f"and {request.end or 'today'}",
            )
        try:
            return EconomicSeries(
                series_id=FEAR_GREED,
                title=TITLE,
                units=UNITS,
                frequency=Frequency.DAY_1,
                source=DataSource(NAME, now, DATASET),
                data=inside,
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"{FEAR_GREED}: {error}") from error

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


def _observations(raw: Any) -> pd.DataFrame:  # noqa: ANN401 - decoded JSON
    """One row per day: the UTC date, published that same day, and the reading."""
    try:
        response = _Response.model_validate(raw)
    except ValidationError as error:
        raise ProviderDataError(
            NAME, f"unexpected Fear & Greed payload ({error.error_count()} problems)"
        ) from None
    if response.metadata.error:
        raise ProviderDataError(NAME, f"alternative.me reports: {response.metadata.error}")
    low, high = _SCALE
    outside = [reading.value for reading in response.data if not low <= reading.value <= high]
    if outside:
        raise ProviderDataError(NAME, f"readings outside {low:g}-{high:g}: {outside[:3]}")
    days = pd.to_datetime([r.timestamp for r in response.data], unit="s", utc=True)
    dates = days.tz_localize(None).normalize()
    frame = pd.DataFrame(
        {
            "observation_date": dates,
            "published_at": dates,
            "value": [reading.value for reading in response.data],
        }
    )
    return frame.drop_duplicates("observation_date", keep="first").sort_values(
        "observation_date", ignore_index=True
    )
