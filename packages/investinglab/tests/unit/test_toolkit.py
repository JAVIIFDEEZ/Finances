from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from investinglab.config import Settings
from investinglab.domain import (
    EUR,
    USD,
    DomainError,
    Frequency,
    Portfolio,
    PriceSeries,
)
from investinglab.services import DataUnavailableError
from investinglab.toolkit import AsyncToolkit, Toolkit
from support.factories import (
    business_days,
    gbm_prices,
    make_economic_series,
    make_fx_series,
    make_series,
)
from support.fakes import FakeBarsProvider, FakeEconomicProvider

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

INDEX = business_days(300)
A = make_series(gbm_prices(300, seed=1), symbol="A.MC", index=INDEX)
B = make_series(gbm_prices(300, seed=2), symbol="B.MC", index=INDEX)
US = make_series(gbm_prices(300, seed=3), symbol="US", index=INDEX, currency=USD)
USD_EUR = make_fx_series(
    gbm_prices(320, mu=0.0, sigma=0.05, s0=0.9, seed=4),
    pair="USDEUR",
    index=business_days(320, start="2023-12-01"),
)


def _estr() -> object:
    months = pd.date_range("2023-11-01", "2025-03-01", freq="MS")
    rows = [
        (str(month.date()), str((month + pd.offsets.MonthBegin(1)).date()), 3.5) for month in months
    ]
    return make_economic_series("ECBESTRVOLWGTTRMDMNRT", rows=rows)


def _settings(tmp_path: Path, **changes: object) -> Settings:
    return Settings(data_dir=tmp_path / "data", **changes)  # type: ignore[arg-type]


@pytest.fixture
def toolkit(tmp_path: Path) -> Iterator[Toolkit]:
    bars = FakeBarsProvider("fake", {s.symbol: s for s in (A, B, US, USD_EUR)})
    rates = FakeEconomicProvider("rates", {"ECBESTRVOLWGTTRMDMNRT": _estr()})  # type: ignore[dict-item]
    with Toolkit.from_settings(_settings(tmp_path), providers=[bars, rates], cache=False) as tk:
        yield tk


def test_series_and_concurrent_batches(toolkit: Toolkit) -> None:
    series = toolkit.series("A.MC", start=INDEX[100], end="2024-12-31")
    batch = toolkit.many(["A.MC", "B.MC", "MISSING"])

    assert series.start == INDEX[100]
    assert series.end <= pd.Timestamp("2024-12-31")
    assert batch.summary() == "2/3 succeeded; failed: MISSING"
    assert toolkit.providers == ("fake", "rates")


def test_portfolios_are_converted_to_the_base_currency(toolkit: Toolkit) -> None:
    portfolio = toolkit.portfolio("Mixed", {"A.MC": 0.5, "US": 0.5}, base_currency="EUR")

    assert isinstance(portfolio, Portfolio)
    assert portfolio.base_currency == EUR
    assert {s.currency for s in portfolio.series} == {EUR}


def test_single_currency_portfolios_need_no_base(toolkit: Toolkit) -> None:
    portfolio = toolkit.portfolio("Core", {"A.MC": 0.6, "B.MC": 0.4}, frequency="1d")

    assert portfolio.base_currency == EUR
    assert portfolio.weights.tolist() == [0.6, 0.4]


def test_mixed_currencies_need_a_base(toolkit: Toolkit) -> None:
    with pytest.raises(DomainError, match="pass base_currency"):
        toolkit.portfolio("Mixed", {"A.MC": 0.5, "US": 0.5})


def test_missing_holdings_abort_the_portfolio(toolkit: Toolkit) -> None:
    with pytest.raises(DataUnavailableError, match="1/2 succeeded; failed: MISSING"):
        toolkit.portfolio("Broken", {"A.MC": 0.5, "MISSING": 0.5})


def test_reports_use_the_point_in_time_risk_free_rate(toolkit: Toolkit) -> None:
    report = toolkit.report(A, language="en")

    assert "| Average risk-free rate | 3.50% |" in report
    assert "0% risk-free" not in report
    assert "Data was checked against the official market sessions" in report


def test_explicit_rates_are_respected(toolkit: Toolkit) -> None:
    report = toolkit.report(A, language="en", risk_free_rate=0.01)

    assert "| Average risk-free rate | 1.00% |" in report


def test_portfolio_reports_are_enriched_too(toolkit: Toolkit) -> None:
    portfolio = toolkit.portfolio("Core", {"A.MC": 0.6, "B.MC": 0.4})

    report = toolkit.report(portfolio, language="en")

    assert "| Average risk-free rate | 3.50% |" in report


def test_without_a_rate_source_the_report_says_so(tmp_path: Path) -> None:
    bars = FakeBarsProvider("fake", {"A.MC": A})
    with Toolkit.from_settings(_settings(tmp_path), providers=[bars], cache=False) as tk:
        report = tk.report(A, language="en")

    assert "Sharpe and Sortino use a 0% risk-free rate." in report


def test_currencies_without_a_rate_series_are_skipped(toolkit: Toolkit) -> None:
    chf = make_series(gbm_prices(60), symbol="CHF.S", currency=EUR.__class__("CHF"))

    assert "0% risk-free" in toolkit.report(chf, language="en")


def test_intraday_subjects_keep_the_given_rate(toolkit: Toolkit) -> None:
    index = pd.date_range("2024-03-04 14:30", periods=40, freq="1h", tz="UTC")
    intraday = make_series(gbm_prices(40), index=index, frequency=Frequency.HOUR_1)

    assert "0% risk-free" in toolkit.report(intraday, language="en")


def test_local_files_are_served_as_a_provider(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    pd.DataFrame({"Date": INDEX.strftime("%Y-%m-%d"), "Close": A.prices.to_numpy()}).to_csv(
        folder / "LOCAL.csv", index=False
    )
    (folder / "instruments.toml").write_text('["LOCAL"]\ncurrency = "EUR"\nexchange = "XMAD"\n')

    with Toolkit.from_settings(_settings(tmp_path, local_data_dir=folder)) as tk:
        series = tk.series("LOCAL")
        again = tk.series("LOCAL")  # served from the Parquet cache

    assert tk.providers == ("files",)
    assert series.prices.tolist() == pytest.approx(A.prices.tolist())
    assert again.prices.equals(series.prices)


def test_files_and_dataframes_can_be_imported(toolkit: Toolkit, tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {"date": INDEX[:5].strftime("%Y-%m-%d"), "close": [1.0, 1.1, 1.2, 1.1, 1.3]}
    )
    frame.to_csv(tmp_path / "x.csv", index=False)

    loaded = toolkit.load(tmp_path / "x.csv", symbol="X", currency="EUR")
    validated = toolkit.from_dataframe(frame, symbol="X", currency="EUR")

    assert isinstance(loaded, PriceSeries)
    assert loaded.bars.equals(validated.bars)
    assert validated.source.dataset == "dataframe"


def test_quality_uses_the_official_calendar(toolkit: Toolkit) -> None:
    assert toolkit.quality(A).expected_sessions is not None


def test_risk_free_rates_on_demand(toolkit: Toolkit) -> None:
    rates = toolkit.risk_free("EUR", pd.DatetimeIndex(INDEX[:5]))

    assert rates.tolist() == pytest.approx([0.035] * 5)


def test_the_sync_toolkit_works_inside_a_running_event_loop(toolkit: Toolkit) -> None:
    async def notebook_cell() -> PriceSeries:
        return toolkit.series("A.MC")  # Jupyter already runs a loop: asyncio.run would fail

    assert asyncio.run(notebook_cell()).symbol == "A.MC"
    assert isinstance(toolkit.asynchronous, AsyncToolkit)


@dataclass
class ClosingProvider(FakeBarsProvider):
    closed: list[bool] = field(default_factory=list)

    async def aclose(self) -> None:
        self.closed.append(True)


def test_closing_releases_provider_clients(tmp_path: Path) -> None:
    provider = ClosingProvider("closing")

    tk = Toolkit.from_settings(_settings(tmp_path), providers=[provider], cache=False)
    tk.close()
    tk.close()  # idempotent

    assert provider.closed == [True]


async def test_async_toolkit_context_manager(tmp_path: Path) -> None:
    provider = ClosingProvider("closing", {"A.MC": A})

    async with AsyncToolkit.from_settings(
        _settings(tmp_path), providers=[provider], cache=False
    ) as tk:
        series = await tk.series("A.MC")

    assert series.symbol == "A.MC"
    assert provider.closed == [True]
