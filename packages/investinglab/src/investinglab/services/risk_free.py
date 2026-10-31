"""Risk-free rate per currency, point-in-time (ADR-0014).

The annual risk-free rate at each date is the latest value *already published* (vintage
data, ADR-0009), converted from percent to decimal. When the preferred series did not
exist yet (€STR starts in October 2019), the next configured series of the same currency
is used for those dates; no value is ever interpolated.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.domain.errors import DomainError
from investinglab.domain.money import EUR, USD
from investinglab.ports.market_data import EconomicRequest, VintageMode
from investinglab.services.market_data import DataUnavailableError, FetchAttempt

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.money import Currency
    from investinglab.services.market_data import MarketDataService

__all__ = ["DEFAULT_RISK_FREE_SERIES", "RiskFreeRateService"]

DEFAULT_RISK_FREE_SERIES: Final[Mapping[Currency, tuple[str, ...]]] = MappingProxyType(
    {
        # €STR (ECB, published since 2019-10), then the ECB deposit facility rate.
        EUR: ("ECBESTRVOLWGTTRMDMNRT", "ECBDFR"),
        # 3-month Treasury bill (constant maturity).
        USD: ("DGS3MO",),
    }
)
"""FRED/ALFRED series used for each currency, in order of preference."""


def _as_decimal(series: EconomicSeries) -> float:
    units = series.units.lower()
    if "percent" in units:
        return 0.01
    raise DomainError(f"{series.series_id} is in {series.units!r}; expected a percent rate")


class RiskFreeRateService:
    """Annual risk-free rates known at each date, by currency.

    Args:
        market_data: Source of the economic series.
        series: Series ids per currency, in order of preference.
        mode: Vintages to use (first releases by default: what was known at the time).
    """

    def __init__(
        self,
        market_data: MarketDataService,
        *,
        series: Mapping[Currency, Sequence[str]] = DEFAULT_RISK_FREE_SERIES,
        mode: VintageMode = VintageMode.FIRST_RELEASE,
    ) -> None:
        self._market_data = market_data
        self._series = series
        self._mode = mode

    def supports(self, currency: Currency) -> bool:
        """Whether a risk-free series is configured for ``currency``."""
        return currency in self._series

    async def annual_rates(self, currency: Currency, dates: pd.DatetimeIndex) -> pd.Series:
        """Annual risk-free rate (decimal) known at each date of ``dates``.

        Dates before the first publication of every configured series are NaN.

        Raises:
            DomainError: If no series is configured for ``currency``.
            DataUnavailableError: If none of the configured series could be obtained.
        """
        if currency not in self._series:
            raise DomainError(f"No risk-free series configured for {currency}")
        target = pd.DatetimeIndex(dates)
        ids = list(self._series[currency])
        batch = await self._market_data.get_many_economic_series(
            EconomicRequest(series_id, mode=self._mode) for series_id in ids
        )
        result = pd.Series(float("nan"), index=target, name=f"risk_free_{currency}")
        attempts: list[FetchAttempt] = []
        for series_id in ids:
            if series_id in batch.failed:
                attempts.extend(batch.failed[series_id].attempts)
                continue
            economic = batch.succeeded[series_id]
            known = economic.known_values_at(target) * _as_decimal(economic)
            result = result.combine_first(known)
        if result.isna().all():
            raise DataUnavailableError(
                f"risk-free {currency}", tuple(attempts), reason="no usable series"
            )
        return result.rename(f"risk_free_{currency}")
