"""Risk-free rate per currency, point-in-time (ADR-0014, ADR-0020).

The annual risk-free rate at each date is the latest value *already published* (vintage
data, ADR-0009), converted from percent to decimal and then from the series' quoting
convention to an effective annual rate (€STR is a simple ACT/360 rate). When the preferred
series did not exist yet (€STR starts in October 2019), the next configured series of the
same currency is used for those dates; no value is ever interpolated.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.domain.errors import DomainError
from investinglab.domain.money import EUR, USD
from investinglab.domain.rates import OVERNIGHT_ACT_360, DayCount, RateConvention
from investinglab.ports.market_data import EconomicRequest, VintageMode
from investinglab.services.market_data import DataUnavailableError, FetchAttempt

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.money import Currency
    from investinglab.services.market_data import MarketDataService

__all__ = ["DEFAULT_RISK_FREE_SERIES", "RiskFreeRateService", "RiskFreeSource"]


@dataclass(frozen=True, slots=True)
class RiskFreeSource:
    """An economic series that quotes a risk-free rate, and how that rate is quoted.

    Attributes:
        series_id: Identifier of the series (an ECB series key or a FRED/ALFRED id).
        convention: Quoting convention, used to turn the rate into an effective annual one.
    """

    series_id: str
    convention: RateConvention = OVERNIGHT_ACT_360


DEFAULT_RISK_FREE_SERIES: Final[Mapping[Currency, tuple[RiskFreeSource, ...]]] = MappingProxyType(
    {
        # €STR (published since 2019-10), then the ECB deposit facility rate: both overnight
        # rates on ACT/360. Each from the ECB Data Portal first, then from its FRED mirror.
        EUR: (
            RiskFreeSource("EST.B.EU000A2X2A25.WT"),
            RiskFreeSource("ECBESTRVOLWGTTRMDMNRT"),
            RiskFreeSource("FM.D.U2.EUR.4F.KR.DFR.LEV"),
            RiskFreeSource("ECBDFR"),
        ),
        # 3-month Treasury bill at constant maturity, quoted on an investment basis
        # (bond-equivalent yield: simple ACT/365 over the bill's ~91 days).
        USD: (RiskFreeSource("DGS3MO", RateConvention(DayCount.ACT_365, term_days=91)),),
    }
)
"""Series used for each currency, in order of preference (ECB Data Portal and FRED/ALFRED)."""


def _as_decimal(series: EconomicSeries) -> float:
    units = series.units.lower()
    if "percent" in units:
        return 0.01
    raise DomainError(f"{series.series_id} is in {series.units!r}; expected a percent rate")


class RiskFreeRateService:
    """Annual risk-free rates known at each date, by currency.

    Args:
        market_data: Source of the economic series.
        series: Risk-free series per currency, in order of preference.
        mode: Vintages to use (first releases by default: what was known at the time).
    """

    def __init__(
        self,
        market_data: MarketDataService,
        *,
        series: Mapping[Currency, Sequence[RiskFreeSource]] = DEFAULT_RISK_FREE_SERIES,
        mode: VintageMode = VintageMode.FIRST_RELEASE,
    ) -> None:
        self._market_data = market_data
        self._series = series
        self._mode = mode

    def supports(self, currency: Currency) -> bool:
        """Whether a risk-free series is configured for ``currency``."""
        return currency in self._series

    async def annual_rates(self, currency: Currency, dates: pd.DatetimeIndex) -> pd.Series:
        """Effective annual risk-free rate (decimal, compounded) known at each date.

        Each series is converted with its own convention, so the rates can be used directly
        by :class:`~investinglab.domain.RiskMetrics`. Dates before the first publication of
        every configured series are NaN.

        Raises:
            DomainError: If no series is configured for ``currency``.
            DataUnavailableError: If none of the configured series could be obtained.
        """
        if currency not in self._series:
            raise DomainError(f"No risk-free series configured for {currency}")
        target = pd.DatetimeIndex(dates)
        sources = list(self._series[currency])
        batch = await self._market_data.get_many_economic_series(
            EconomicRequest(source.series_id, mode=self._mode) for source in sources
        )
        result = pd.Series(float("nan"), index=target, name=f"risk_free_{currency}")
        attempts: list[FetchAttempt] = []
        for source in sources:
            if source.series_id in batch.failed:
                attempts.extend(batch.failed[source.series_id].attempts)
                continue
            economic = batch.succeeded[source.series_id]
            quoted = economic.known_values_at(target) * _as_decimal(economic)
            result = result.combine_first(source.convention.effective_annual(quoted))
        if result.isna().all():
            raise DataUnavailableError(
                f"risk-free {currency}", tuple(attempts), reason="no usable series"
            )
        return result.rename(f"risk_free_{currency}")
