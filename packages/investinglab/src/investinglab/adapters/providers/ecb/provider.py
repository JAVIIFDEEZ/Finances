"""European Central Bank provider: official euro reference rates and euro money-market rates.

The ECB Data Portal (``data-api.ecb.europa.eu``) needs no key. The adapter serves:

* **Bars of currency pairs** from the euro foreign exchange reference rates (dataflow
  ``EXR``, published around 16:00 CET for 14:15 CET): ``EURUSD=X`` directly, ``USDEUR=X``
  as its inverse and pairs without the euro (``GBPUSD=X``) as the ratio of two reference
  rates of the same day. Each bar holds the close only, labelled with the fixing date.
* **Economic series** of the :data:`~investinglab.adapters.providers.ecb.catalogue.CATALOGUE`
  (€STR and the ECB's policy rates), each with the day it became public, so they can be
  used point in time (ADR-0009).

Days without a fixing (TARGET holidays) are absent, never filled.
"""

from __future__ import annotations

import asyncio
import io
import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final, Self

import pandas as pd

from investinglab.adapters.http import HttpClient
from investinglab.adapters.providers.ecb.calendar import next_target_days
from investinglab.adapters.providers.ecb.catalogue import CATALOGUE, Publication
from investinglab.domain.economic import EconomicSeries
from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import EXCHANGES, AssetClass, Instrument
from investinglab.domain.money import Currency
from investinglab.domain.series import DataSource, PriceAdjustment, PriceSeries
from investinglab.domain.time import Frequency
from investinglab.ports.errors import (
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from investinglab.ports.market_data import Dataset, ProviderCapabilities, RateLimit

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from investinglab.adapters.http import RetryPolicy
    from investinglab.adapters.providers.ecb.catalogue import EcbSeries
    from investinglab.ports.market_data import BarsRequest, EconomicRequest

__all__ = ["BASE_URL", "NAME", "REFERENCE_CURRENCIES", "EcbProvider"]

NAME: Final = "ecb"
BASE_URL: Final = "https://data-api.ecb.europa.eu"
RATE_LIMITS: Final = (RateLimit(10, 1.0),)
"""Self-imposed quota: the ECB publishes none."""

REFERENCE_CURRENCIES: Final = frozenset(
    {
        "AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "GBP", "HKD",
        "HUF", "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK",
        "NZD", "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
    }
)  # fmt: skip
"""Currencies with a daily euro reference rate."""

FREQUENCIES: Final = frozenset(
    {Frequency.DAY_1, Frequency.WEEK_1, Frequency.MONTH_1, Frequency.QUARTER_1, Frequency.YEAR_1}
)
"""Daily fixings, and coarser bars aggregated from them."""

_CURRENCY: Final = "(?:EUR|" + "|".join(sorted(REFERENCE_CURRENCIES)) + ")"
_PAIR: Final = re.compile(rf"(?P<base>{_CURRENCY})(?!(?P=base)=X)(?P<quote>{_CURRENCY})=X")
"""``EURUSD=X``-style pair of two different reference currencies."""
_EURO: Final = "EUR"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EcbProvider:
    """Euro reference rates (bars) and euro money-market rates (economic series).

    Args:
        client: HTTP client to use; one with the ECB's base URL and quota by default.
        timeout: Seconds before a request times out (default client only).
        retry: Retry policy for transient failures (default client only).
        clock: Current time (injectable for tests); stamps the provenance.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client or HttpClient(
            NAME, base_url=BASE_URL, timeout=timeout, retry=retry, rate_limits=RATE_LIMITS
        )
        self._clock = clock

    @property
    def name(self) -> str:
        """Provider slug."""
        return NAME

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Daily and coarser FX bars of the reference currencies, and the catalogue."""
        series = "|".join(re.escape(series_id) for series_id in CATALOGUE)
        return ProviderCapabilities(
            datasets=frozenset({Dataset.BARS, Dataset.ECONOMIC}),
            asset_classes=frozenset({AssetClass.FX}),
            frequencies=FREQUENCIES,
            rate_limits=RATE_LIMITS,
            identifiers=f"{_PAIR.pattern}|{series}",
        )

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Daily closes of a currency pair from the euro reference rates.

        Raises:
            SymbolNotFoundError: If the symbol is not a pair of reference currencies.
            UnsupportedRequestError: For intraday frequencies.
            ProviderDataError: If the payload is malformed or too short.
        """
        base, quote = _pair(request.symbol)
        if request.frequency not in FREQUENCIES:
            raise UnsupportedRequestError(
                NAME, f"{request.symbol}: reference rates are daily, not {request.frequency}"
            )
        now = self._clock()
        if base == _EURO:
            closes = await self._reference_rates(quote, request.start, request.end)
        elif quote == _EURO:
            closes = 1.0 / await self._reference_rates(base, request.start, request.end)
        else:
            numerator, denominator = await asyncio.gather(
                self._reference_rates(quote, request.start, request.end),
                self._reference_rates(base, request.start, request.end),
            )
            # Same-day fixings only: a day missing on either side is absent, never filled.
            closes = (numerator / denominator).dropna()
        name = f"{base}/{quote} ECB reference rate"
        if _EURO not in {base, quote}:
            name += "s (cross via EUR)"
        try:
            instrument = Instrument(
                symbol=request.symbol,
                name=name,
                asset_class=AssetClass.FX,
                currency=Currency(quote),
                exchange=EXCHANGES["FX"],
            )
            series = PriceSeries(
                instrument=instrument,
                frequency=Frequency.DAY_1,
                source=DataSource(NAME, now, "EXR"),
                data=pd.DataFrame({"close": closes}),
                adjustment=PriceAdjustment.RAW,
            )
            if request.frequency is not Frequency.DAY_1:
                series = series.resample(request.frequency)
        except DomainError as error:
            raise ProviderDataError(NAME, f"{request.symbol}: {error}") from error
        return series

    async def fetch_economic_series(self, request: EconomicRequest) -> EconomicSeries:
        """A series of the catalogue, with the day each value became public.

        The ECB keeps no vintages: every request mode returns the published values.

        Raises:
            SymbolNotFoundError: If the series is not in the catalogue.
            ProviderDataError: If the payload is malformed or empty.
        """
        entry = CATALOGUE.get(request.series_id)
        if entry is None:
            raise SymbolNotFoundError(
                NAME, f"{request.series_id} is not served; known: {sorted(CATALOGUE)}"
            )
        values = await self._observations(entry.series_id, request.start, request.end)
        dates = pd.DatetimeIndex(values.index)
        try:
            return EconomicSeries(
                series_id=entry.series_id,
                title=entry.title,
                units=entry.units,
                frequency=entry.frequency,
                source=DataSource(NAME, self._clock(), entry.flow),
                data=pd.DataFrame(
                    {
                        "observation_date": dates,
                        "published_at": _published(entry, dates),
                        "value": values.to_numpy(),
                    }
                ),
            )
        except DomainError as error:
            raise ProviderDataError(NAME, f"{entry.series_id}: {error}") from error

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

    async def _reference_rates(
        self, currency: str, start: date | None, end: date | None
    ) -> pd.Series:
        """Units of ``currency`` per euro, by fixing date."""
        return await self._observations(f"EXR.D.{currency}.EUR.SP00.A", start, end)

    async def _observations(
        self, series_id: str, start: date | None, end: date | None
    ) -> pd.Series:
        """Published values of a series, indexed by observation date (``NaN`` rows dropped)."""
        flow, key = series_id.split(".", 1)
        params = {
            "format": "csvdata",
            "startPeriod": start.isoformat() if start else None,
            "endPeriod": end.isoformat() if end else None,
        }
        text = await self._client.get_text(f"/service/data/{flow}/{key}", params)
        return _parse(text, series_id)


def _pair(symbol: str) -> tuple[str, str]:
    match = _PAIR.fullmatch(symbol)
    if match is None:
        raise SymbolNotFoundError(
            NAME, f"{symbol} is not a pair of ECB reference currencies (like EURUSD=X)"
        )
    return match["base"], match["quote"]


def _parse(text: str, series_id: str) -> pd.Series:
    """Values of ``series_id`` in an SDMX-CSV document, by observation date."""
    if not text.strip():  # the portal answers an empty body when the range has no values
        raise ProviderDataError(NAME, f"{series_id}: no published values in the range")
    try:
        frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except (ValueError, pd.errors.ParserError) as error:
        raise ProviderDataError(NAME, f"{series_id}: unreadable CSV ({error})") from error
    missing = sorted({"KEY", "TIME_PERIOD", "OBS_VALUE"} - set(frame.columns))
    if missing:
        raise ProviderDataError(NAME, f"{series_id}: CSV without columns {missing}")
    foreign = sorted(set(frame["KEY"]) - {series_id})
    if foreign:
        raise ProviderDataError(NAME, f"{series_id}: unexpected series {foreign[:3]}")
    values = pd.to_numeric(frame["OBS_VALUE"].replace("", "nan"), errors="coerce")
    dates = pd.to_datetime(frame["TIME_PERIOD"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ProviderDataError(NAME, f"{series_id}: observation dates are not daily dates")
    observed = values.notna()  # holidays come as empty values: absent, not zero
    series = pd.Series(
        values[observed].to_numpy(dtype=float),
        index=pd.DatetimeIndex(dates[observed]),
        name=series_id,
    ).sort_index()
    if series.index.has_duplicates:
        raise ProviderDataError(NAME, f"{series_id}: repeated observation dates")
    if series.empty:
        raise ProviderDataError(NAME, f"{series_id}: no published values in the range")
    return series


def _published(entry: EcbSeries, dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if entry.publication is Publication.NEXT_TARGET_DAY:
        return next_target_days(dates)
    return dates
