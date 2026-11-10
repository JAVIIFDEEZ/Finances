from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    EUR,
    GBP,
    OVERNIGHT_ACT_360,
    USD,
    DayCount,
    DomainError,
    EconomicSeries,
    Frequency,
    RateConvention,
)
from investinglab.ports import ProviderUnavailableError
from investinglab.services import (
    DEFAULT_RISK_FREE_SERIES,
    DataUnavailableError,
    MarketDataService,
    ProviderRegistry,
    RiskFreeRateService,
    RiskFreeSource,
)
from support.factories import SYNTHETIC_SOURCE
from support.fakes import FakeEconomicProvider

NOW = datetime(2026, 10, 31, tzinfo=UTC)


def _economic(
    series_id: str, rows: list[tuple[str, str, float]], units: str = "Percent"
) -> EconomicSeries:
    data = pd.DataFrame(rows, columns=["observation_date", "published_at", "value"])
    data["observation_date"] = pd.to_datetime(data["observation_date"])
    data["published_at"] = pd.to_datetime(data["published_at"])
    return EconomicSeries(
        series_id, f"Synthetic {series_id}", units, Frequency.DAY_1, SYNTHETIC_SOURCE, data
    )


# Synthetic stand-ins: the deposit rate covers 2019, €STR only exists from October.
DEPOSIT = _economic(
    "ECBDFR", [("2019-01-01", "2019-01-02", -0.40), ("2019-09-18", "2019-09-19", -0.50)]
)
ESTR = _economic(
    "ECBESTRVOLWGTTRMDMNRT",
    [("2019-10-01", "2019-10-02", -0.55), ("2019-10-02", "2019-10-03", -0.54)],
)


def _service(provider: FakeEconomicProvider, **options: object) -> RiskFreeRateService:
    registry = ProviderRegistry()
    registry.register(provider)
    return RiskFreeRateService(MarketDataService(registry, clock=lambda: NOW), **options)  # type: ignore[arg-type]


def _overnight(*quoted: float) -> list[float]:
    return [OVERNIGHT_ACT_360.effective_annual(rate) for rate in quoted]


async def test_preferred_series_with_fallback_before_it_existed() -> None:
    provider = FakeEconomicProvider("fred", {"ECBDFR": DEPOSIT, "ECBESTRVOLWGTTRMDMNRT": ESTR})
    dates = pd.DatetimeIndex(["2018-12-31", "2019-06-03", "2019-10-01", "2019-10-03"])

    rates = await _service(provider).annual_rates(EUR, dates)

    assert np.isnan(rates.iloc[0])  # nothing published yet
    assert rates.iloc[1:].tolist() == pytest.approx(_overnight(-0.004, -0.005, -0.0054))
    assert rates.name == "risk_free_EUR"


async def test_usd_uses_treasury_bills() -> None:
    bills = _economic("DGS3MO", [("2024-01-02", "2024-01-03", 5.25)])
    service = _service(FakeEconomicProvider("fred", {"DGS3MO": bills}))

    rates = await service.annual_rates(USD, pd.DatetimeIndex(["2024-01-05"]))

    # A bond-equivalent yield of 5.25 % on a three-month bill, rolled for a year.
    assert rates.iloc[0] == pytest.approx((1 + 0.0525 * 91 / 365) ** (365 / 91) - 1)
    assert service.supports(USD)
    assert not service.supports(GBP)
    assert [source.series_id for source in DEFAULT_RISK_FREE_SERIES[EUR]] == [
        "EST.B.EU000A2X2A25.WT",
        "ECBESTRVOLWGTTRMDMNRT",
        "FM.D.U2.EUR.4F.KR.DFR.LEV",
        "ECBDFR",
    ]


async def test_each_series_uses_its_own_convention() -> None:
    gilts = _economic("GILT1Y", [("2024-01-02", "2024-01-03", 4.0)])
    annual = RateConvention(DayCount.ACT_365, term_days=365)
    service = _service(
        FakeEconomicProvider("fred", {"GILT1Y": gilts}),
        series={GBP: (RiskFreeSource("GILT1Y", annual),)},
    )

    rates = await service.annual_rates(GBP, pd.DatetimeIndex(["2024-01-05"]))

    assert rates.iloc[0] == pytest.approx(0.04)


async def test_partial_failures_still_use_the_available_series() -> None:
    provider = FakeEconomicProvider(
        "fred",
        {"ECBDFR": DEPOSIT},
        errors={"ECBESTRVOLWGTTRMDMNRT": ProviderUnavailableError("fred", "503")},
    )

    rates = await _service(provider).annual_rates(EUR, pd.DatetimeIndex(["2019-12-02"]))

    assert rates.iloc[0] == pytest.approx(_overnight(-0.005)[0])


async def test_all_series_failing() -> None:
    service = _service(FakeEconomicProvider("fred"))

    with pytest.raises(DataUnavailableError) as caught:
        await service.annual_rates(EUR, pd.DatetimeIndex(["2024-01-02"]))

    assert len(caught.value.attempts) == len(DEFAULT_RISK_FREE_SERIES[EUR])  # one per series


async def test_unconfigured_currency_and_unexpected_units() -> None:
    odd = _economic("DGS3MO", [("2024-01-02", "2024-01-03", 5.25)], units="Basis points")
    service = _service(FakeEconomicProvider("fred", {"DGS3MO": odd}))

    with pytest.raises(DomainError, match="No risk-free series"):
        await service.annual_rates(GBP, pd.DatetimeIndex(["2024-01-02"]))
    with pytest.raises(DomainError, match="expected a percent"):
        await service.annual_rates(USD, pd.DatetimeIndex(["2024-01-05"]))
