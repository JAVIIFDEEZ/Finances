from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    CovarianceEstimator,
    DataSource,
    DomainError,
    DriftAssumption,
    PriceSeries,
    SimulationConfig,
)
from investinglab.reporting.markdown import MarkdownReport
from investinglab.reporting.options import ReportOptions
from support.factories import business_days, gbm_prices, make_series

if TYPE_CHECKING:
    from pathlib import Path

N = 504


def _series(symbol: str = "SAN.MC", *, seed: int = 1) -> PriceSeries:
    index = business_days(N)
    series = make_series(gbm_prices(N, seed=seed), symbol=symbol, index=index, ohlc=True)
    source = DataSource(
        "synthetic", retrieved_at=(index[-1] + timedelta(days=1)).tz_localize("UTC")
    )
    return series.with_bars(series.bars, source=source)


def _headings(report: str) -> list[str]:
    return re.findall(r"^#+ (.+)$", report, flags=re.MULTILINE)


def test_spanish_report_has_every_section_in_order() -> None:
    report = _series().report()

    assert isinstance(report, MarkdownReport)
    assert _headings(report) == [
        "Informe de SAN.MC · Synthetic SAN.MC",
        "Datos y procedencia",
        "Rentabilidad y riesgo",
        "Riesgo de cola por periodo",
        "Caídas desde máximos",
        "Calidad de los datos",
        "Diagnósticos y advertencias",
        "Metodología",
    ]
    assert "observaciones con frecuencia diaria" in report
    assert "Ratio de Sharpe: intervalo de confianza al 95\u00a0%" in report


def test_english_report() -> None:
    report = _series().report(language="en")

    assert _headings(report)[:3] == [
        "SAN.MC · Synthetic SAN.MC report",
        "Data and provenance",
        "Return and risk",
    ]
    assert "observations, daily" in report
    assert "Report generated with InvestingLab" in report


def test_figures_match_the_domain_metrics() -> None:
    series = _series()
    metrics = series.metrics(risk_free_rate=0.02)

    report = series.report(language="en", risk_free_rate=0.02)

    assert f"| Sharpe ratio | {metrics.sharpe_ratio:.2f} |" in report
    assert f"| Annualised volatility | {metrics.annualized_volatility * 100:.1f}% |" in report
    assert f"| Maximum drawdown | {metrics.max_drawdown * 100:.1f}% |" in report
    assert "| Average risk-free rate | 2.00% |" in report
    assert "0% risk-free" not in report


def test_reports_are_deterministic() -> None:
    assert _series().report() == _series().report()


def test_keyword_settings_override_options() -> None:
    options = ReportOptions(language="en", title="Custom title")

    report = _series().report(options, top_drawdowns=1)

    assert report.startswith("# Custom title\n")
    drawdown_rows = re.findall(r"^\| 1 \| \d{4}-", report, flags=re.MULTILINE)
    assert len(drawdown_rows) == 1
    assert not re.search(r"^\| 2 \| \d{4}-", report, flags=re.MULTILINE)


def test_tail_table_lists_every_level_and_method() -> None:
    report = _series().report(language="en", confidence_levels=(0.9, 0.975))

    assert report.count("| 90% |") == 3
    assert report.count("| 97.5% |") == 3
    assert "| 99% |" not in report


def test_calendar_checked_quality_is_used() -> None:
    series = _series()
    sessions = business_days(N + 2)
    quality = series.quality(expected_sessions=sessions)

    report = series.report(quality=quality)

    assert "Se compararon los datos con las sesiones oficiales del mercado" in report


def test_quality_issues_are_listed_with_their_dates() -> None:
    prices = gbm_prices(N)
    prices[300:310] = prices[300]
    series = make_series(prices, index=business_days(N))

    report = series.report(language="en")

    assert "| Warning | Frozen prices | 1 |" in report
    assert "Runs of identical prices: 1 (longest: 10 observations)" in report


def test_monotone_series_have_no_drawdowns() -> None:
    series = make_series(np.linspace(100, 150, 60), index=business_days(60))

    assert "No hubo caídas desde máximos en el periodo." in series.report()


def test_simulation_section_from_a_configuration_or_a_result() -> None:
    series = _series()
    config = SimulationConfig(n_paths=500, horizon=21, seed=3)

    from_config = series.report(language="en", simulation=config)
    from_result = series.report(language="en", simulation=series.monte_carlo(config))

    assert "## Monte Carlo simulation" in from_config
    assert "| Paths | 500 |" in from_config
    assert "| Horizon | 21 periods (daily) |" in from_config
    assert from_config == from_result


def test_a_simulation_of_another_asset_is_rejected() -> None:
    other = _series("OTHER", seed=2).monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    with pytest.raises(DomainError, match="calibrated on"):
        _series().report(simulation=other)


def test_identifiers_and_adjusted_prices_are_described() -> None:
    series = _series()
    bars = series.bars
    bars["adj_close"] = bars["close"] * 0.97
    adjusted = series.with_bars(bars)

    report = adjusted.report(language="en")

    assert "| Price analysed | close adjusted for splits and dividends |" in report
    assert "not adjusted for dividends" not in report


def test_reports_can_be_saved(tmp_path: Path) -> None:
    path = _series().report().save(tmp_path / "report.md")

    assert path.read_text(encoding="utf-8").startswith("# Informe de SAN.MC")


def test_point_in_time_risk_free_series_is_accepted() -> None:
    series = _series()
    rates = pd.Series(0.03, index=series.prices.index)

    report = series.report(language="en", risk_free_rate=rates)

    assert "| Average risk-free rate | 3.00% |" in report


def test_a_clean_series_has_no_warnings() -> None:
    n = 1_500
    index = business_days(n)
    prices = gbm_prices(n, mu=0.30, sigma=0.15, seed=11)
    bars = pd.DataFrame({"close": prices, "adj_close": prices}, index=index)
    series = make_series(prices, index=index).with_bars(
        bars,
        source=DataSource(
            "synthetic", retrieved_at=(index[-1] + timedelta(days=1)).tz_localize("UTC")
        ),
    )

    report = series.report(risk_free_rate=0.01, confidence_levels=(0.95,))

    assert "Diagnóstico: sin advertencias en los datos ni en las métricas." in report
    assert "Sin advertencias." in report


def test_simulation_settings_are_described() -> None:
    config = SimulationConfig(
        n_paths=200,
        horizon=1,
        drift=DriftAssumption.RISK_FREE,
        risk_free_rate=0.025,
        covariance=CovarianceEstimator.LEDOIT_WOLF,
        seed=None,
    )

    report = _series().report(language="en", simulation=config)

    assert "| Expected return | risk-free rate (2.50% a year) |" in report
    assert "| Covariance | Ledoit-Wolf (shrinkage 0.000) |" in report
    assert "| Seed | — |" in report
    assert "| Horizon | 1 period (daily) |" in report
