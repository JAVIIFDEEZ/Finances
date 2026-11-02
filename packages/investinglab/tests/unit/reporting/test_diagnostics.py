from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    AssetClass,
    DataSource,
    DriftAssumption,
    Frequency,
    IssueKind,
    PriceAdjustment,
    PriceSeries,
    QualityIssue,
    RiskMetrics,
    Severity,
    SimulationConfig,
)
from investinglab.reporting.diagnostics import (
    Diagnostic,
    correlation_diagnostics,
    data_diagnostics,
    history_diagnostics,
    issue_message,
    level_label,
    metrics_diagnostics,
    portfolio_structure_diagnostics,
    risk_diagnostics,
    simulation_diagnostics,
    sort_diagnostics,
    staleness_diagnostics,
)
from investinglab.reporting.i18n import Translator
from support.factories import business_days, gbm_prices, make_series

ES = Translator("es")
EN = Translator("en")


def _fresh(series_end: pd.Timestamp) -> DataSource:
    return DataSource("synthetic", retrieved_at=(series_end + timedelta(days=1)).tz_localize("UTC"))


def _series(n: int = 300, **kwargs: object) -> PriceSeries:
    index = business_days(n)
    series = make_series(gbm_prices(n), index=index, **kwargs)  # type: ignore[arg-type]
    return series.with_bars(series.bars, source=_fresh(index[-1]))


# ── Labels and messages ─────────────────────────────────────────────


def test_level_labels() -> None:
    assert level_label(0.95, ES) == "95\u00a0%"
    assert level_label(0.975, EN) == "97.5%"


@pytest.mark.parametrize(
    ("kind", "details", "spanish"),
    [
        (
            IssueKind.MISSING_SESSIONS,
            {"count": 12, "ratio": 0.024},
            "Sesiones de mercado sin datos: 12 (2,4",
        ),
        (
            IssueKind.UNEXPECTED_SESSIONS,
            {"count": 2},
            "Observaciones en días sin sesión oficial: 2",
        ),
        (
            IssueKind.OUTLIER_RETURNS,
            {"count": 3, "threshold": 8.0},
            "Retornos a más de 8 desviaciones robustas de la mediana: 3",
        ),
        (
            IssueKind.SUSPECTED_SPLIT,
            {"count": 1, "ratios": "0.25", "adjusted": 0.0},
            "ratios típicos de un split: 1 (0.25); los precios no están ajustados",
        ),
        (
            IssueKind.STALE_PRICES,
            {"runs": 2, "longest": 7},
            "Rachas de precios idénticos: 2 (la más larga, de 7",
        ),
        (
            IssueKind.OHLC_INCONSISTENT,
            {"count": 4},
            "Barras cuyo máximo o mínimo contradice la apertura o el cierre: 4",
        ),
        (IssueKind.ZERO_VOLUME, {"count": 5}, "Observaciones con volumen cero: 5"),
        (IssueKind.SHORT_HISTORY, {"years": 0.5}, "Solo 0,50 años de histórico"),
    ],
)
def test_quality_issues_are_translated(
    kind: IssueKind, details: dict[str, float | str], spanish: str
) -> None:
    issue = QualityIssue(kind, Severity.WARNING, "english fallback", details=details)

    assert spanish in issue_message(issue, ES)
    assert issue_message(issue, EN) != "english fallback"


def test_issues_without_details_keep_their_message() -> None:
    issue = QualityIssue(IssueKind.STALE_PRICES, Severity.WARNING, "raw message")

    assert issue_message(issue, ES) == "raw message"


def test_split_on_adjusted_prices_asks_to_check_the_adjustment() -> None:
    issue = QualityIssue(
        IssueKind.SUSPECTED_SPLIT,
        Severity.WARNING,
        "x",
        details={"count": 1, "ratios": "2", "adjusted": 1.0},
    )

    assert "check the adjustment" in issue_message(issue, EN)


def test_sorting_puts_the_most_severe_first_and_keeps_order() -> None:
    items = [
        Diagnostic(Severity.INFO, "a", ""),
        Diagnostic(Severity.CRITICAL, "b", ""),
        Diagnostic(Severity.INFO, "c", ""),
        Diagnostic(Severity.WARNING, "d", ""),
    ]

    assert [d.message for d in sort_diagnostics(items)] == ["b", "d", "a", "c"]


# ── Data ────────────────────────────────────────────────────────────


def test_unadjusted_equity_prices_are_a_warning() -> None:
    series = _series()

    found = data_diagnostics(series, series.quality(), EN)

    assert [d.severity for d in found] == [Severity.WARNING]
    assert "not adjusted" in found[0].message


def test_split_only_adjustment_is_informational() -> None:
    series = _series()
    split_adjusted = series.with_bars(series.bars, adjustment=PriceAdjustment.SPLITS)

    found = data_diagnostics(split_adjusted, split_adjusted.quality(), EN)

    assert [d.severity for d in found] == [Severity.INFO]
    assert "split-adjusted" in found[0].message


def test_adjusted_close_and_assets_without_dividends_need_no_warning() -> None:
    series = _series()
    bars = series.bars
    bars["adj_close"] = bars["close"] * 0.98
    adjusted = series.with_bars(bars)
    index = _series(asset_class=AssetClass.INDEX, exchange=None)

    assert data_diagnostics(adjusted, adjusted.quality(), EN) == []
    assert data_diagnostics(index, index.quality(), EN) == []


def test_quality_warnings_become_diagnostics_with_advice() -> None:
    prices = gbm_prices(300)
    prices[200:] /= 4
    series = make_series(prices, index=business_days(300), asset_class=AssetClass.INDEX)
    series = series.with_bars(series.bars, source=_fresh(series.end))

    found = data_diagnostics(series, series.quality(), ES, subject="X")

    assert found[0].severity is Severity.CRITICAL
    assert "adj_close" in found[0].advice
    assert found[0].subject == "X"


def test_old_data_is_flagged_with_its_lag() -> None:
    stale = make_series(gbm_prices(300), index=business_days(300), asset_class=AssetClass.INDEX)

    (found,) = data_diagnostics(stale, stale.quality(), EN)

    assert found.severity is Severity.INFO
    assert "days before it was retrieved" in found.message


def test_intraday_lag_is_measured_in_hours() -> None:
    index = pd.date_range("2024-03-04 14:30", periods=50, freq="1h", tz="UTC")
    series = make_series(
        gbm_prices(50),
        index=index,
        frequency=Frequency.HOUR_1,
        asset_class=AssetClass.INDEX,
        exchange=None,
    )
    recent = series.with_bars(
        series.bars, source=DataSource("synthetic", retrieved_at=index[-1] + timedelta(hours=5))
    )

    def lags(item: object) -> list[Diagnostic]:
        found = data_diagnostics(item, item.quality(), EN)  # type: ignore[arg-type, attr-defined]
        return [d for d in found if "before it was retrieved" in d.message]

    assert lags(recent) == []
    assert len(lags(series)) == 1


# ── Metrics ─────────────────────────────────────────────────────────


def _metrics(returns: np.ndarray) -> RiskMetrics:
    index = pd.bdate_range("2015-01-01", periods=returns.size)
    return RiskMetrics.from_returns(pd.Series(returns, index=index), periods_per_year=252)


def test_noisy_sharpe_and_thin_tails_are_explained() -> None:
    rng = np.random.default_rng(0)
    metrics = _metrics(rng.normal(0.0002, 0.01, 300))

    found = metrics_diagnostics(metrics, EN, levels=(0.95, 0.99), zero_risk_free=True)

    messages = " ".join(d.message for d in found)
    assert "includes zero" in messages
    assert "rests on few tail observations: 3" in messages
    assert "0% risk-free" in messages
    assert all(d.severity is Severity.INFO for d in found)


def test_significant_sharpe_on_a_long_history_raises_nothing() -> None:
    rng = np.random.default_rng(1)
    metrics = _metrics(rng.normal(0.002, 0.01, 5_000))

    assert metrics_diagnostics(metrics, EN, levels=(0.95,), zero_risk_free=False) == []


def test_fat_tails_reject_normality() -> None:
    rng = np.random.default_rng(2)
    metrics = _metrics(rng.standard_t(3, 3_000) * 0.01 + 0.002)

    found = metrics_diagnostics(metrics, EN, levels=(0.95,), zero_risk_free=False)

    (warning,) = [d for d in found if d.severity is Severity.WARNING]
    assert "not normally distributed" in warning.message
    assert "Cornish-Fisher" in warning.advice


# ── Portfolio ───────────────────────────────────────────────────────


def test_a_late_holding_truncates_the_history() -> None:
    early = make_series(gbm_prices(300), symbol="EARLY", index=business_days(300))
    late = make_series(gbm_prices(100), symbol="LATE", index=business_days(100, start="2024-10-01"))

    (found,) = history_diagnostics([early, late], late.start, EN)
    assert "LATE starts trading" in found.message
    assert history_diagnostics([early, early], early.start, EN) == []


def test_risk_concentration_and_hedges() -> None:
    table = pd.DataFrame(
        {"weight": [0.4, 0.4, 0.2], "share": [0.8, 0.3, -0.1]}, index=["A", "B", "C"]
    )

    found = risk_diagnostics(table, EN)

    assert [(d.severity, d.subject) for d in found] == [
        (Severity.WARNING, "A"),
        (Severity.INFO, "C"),
    ]
    assert risk_diagnostics(table.iloc[:1], EN) == []


def test_highly_correlated_pairs_are_listed_strongest_first() -> None:
    symbols = ["A", "B", "C"]
    correlation = pd.DataFrame(
        [[1.0, 0.92, 0.97], [0.92, 1.0, 0.5], [0.97, 0.5, 1.0]], index=symbols, columns=symbols
    )

    found = correlation_diagnostics(correlation, EN)

    assert [d.message.split(" have")[0] for d in found] == ["A and C", "A and B"]


def test_long_stale_marks_are_reported() -> None:
    staleness = pd.DataFrame({"A": [0, 0, 0, 0], "B": [0, 3, 6, 7]})

    (found,) = staleness_diagnostics(staleness, EN)

    assert found.subject == "B"
    assert "up to 7 periods" in found.message


def test_turnover_and_leverage() -> None:
    found = portfolio_structure_diagnostics(annual_turnover=2.5, gross_exposure=1.6, tr=EN)

    assert len(found) == 2
    assert "250%" in found[0].message
    assert "160%" in found[1].message
    assert portfolio_structure_diagnostics(annual_turnover=0.2, gross_exposure=1.0, tr=EN) == []


# ── Simulation ──────────────────────────────────────────────────────


def test_historical_drift_and_imprecise_var_are_flagged() -> None:
    series = make_series(gbm_prices(400), index=business_days(400))
    noisy = series.monte_carlo(SimulationConfig(n_paths=100, horizon=20, confidence_levels=(0.99,)))
    calm = series.monte_carlo(
        SimulationConfig(n_paths=20_000, horizon=20, drift=DriftAssumption.ZERO)
    )

    found = simulation_diagnostics(noisy, EN)

    assert found[0].severity is Severity.WARNING
    assert "historical mean" in found[0].message
    assert any("wide confidence interval" in d.message for d in found)
    assert simulation_diagnostics(calm, EN) == []
