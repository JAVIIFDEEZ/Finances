from __future__ import annotations

import re

import pandas as pd
import pytest

from investinglab.domain import (
    EXCHANGES,
    AssetClass,
    DomainError,
    Frequency,
    Portfolio,
    PriceSeries,
    RebalancePolicy,
    SimulationConfig,
)
from investinglab.reporting.analysis import PortfolioAnalysis, choose_frequency
from investinglab.reporting.options import ReportOptions
from support.factories import business_days, gbm_prices, make_series

N = 504
INDEX = business_days(N)


def _asset(
    symbol: str, seed: int, *, index: pd.DatetimeIndex = INDEX, **kwargs: object
) -> PriceSeries:
    return make_series(gbm_prices(len(index), seed=seed), symbol=symbol, index=index, **kwargs)  # type: ignore[arg-type]


def _portfolio(policy: RebalancePolicy | None = None) -> Portfolio:
    assets = [_asset("AAA.MC", 1), _asset("BBB.MC", 2), _asset("CCC.MC", 3)]
    return Portfolio.from_weights("Núcleo", assets, [0.5, 0.3, 0.2], rebalance=policy)


def _headings(report: str) -> list[str]:
    return re.findall(r"^#+ (.+)$", report, flags=re.MULTILINE)


def test_spanish_portfolio_report_sections() -> None:
    report = _portfolio().report()

    assert _headings(report) == [
        "Informe de la cartera Núcleo",
        "Composición",
        "Rentabilidad y riesgo",
        "Rendimiento comparado",
        "Riesgo de cola por periodo",
        "Correlaciones",
        "Contribución al riesgo",
        "Rebalanceo y rotación",
        "Caídas desde máximos",
        "Calendarios y valoración",
        "Calidad de los datos",
        "Diagnósticos y advertencias",
        "Metodología",
    ]
    assert "política de rebalanceo: periódico, con frecuencia mensual" in report


def test_english_report_compares_every_holding_over_the_common_period() -> None:
    portfolio = _portfolio()

    report = portfolio.report(language="en")

    table = report.split("## Performance comparison")[1].split("##")[0]
    rows = [
        line.split("|")[1].strip()
        for line in table.splitlines()
        if line.startswith("| ") and not line.startswith("| :")
    ]
    assert rows == ["Asset", "Portfolio", "AAA.MC", "BBB.MC", "CCC.MC"]
    assert "Every figure covers the common period" in table


def test_portfolio_figures_match_the_domain() -> None:
    portfolio = _portfolio()
    metrics = portfolio.metrics()

    report = portfolio.report(language="en")

    assert f"| Sharpe ratio | {metrics.sharpe_ratio:.2f} |" in report
    assert f"| Annualised volatility | {metrics.annualized_volatility * 100:.1f}% |" in report
    assert "| AAA.MC | Synthetic AAA.MC | Equity | XMAD | EUR | 50.0% |" in report


def test_correlations_and_risk_contributions() -> None:
    portfolio = _portfolio()
    correlation = portfolio.correlation()

    report = portfolio.report(language="en")

    assert f"| AAA.MC | 1.00 | {correlation['BBB.MC']['AAA.MC']:.2f} |" in report
    assert "Correlations of daily returns" in report
    shares = re.findall(
        r"^\| (?:AAA|BBB|CCC)\.MC \| [\d.]+% \| [\d.]+% \| [\d.]+% \| (-?[\d.]+)% \|$",
        report,
        flags=re.MULTILINE,
    )
    assert sum(float(s) for s in shares) == pytest.approx(100.0, abs=0.2)
    assert "Diversification ratio" in report


def test_rebalancing_section_counts_the_rebalances() -> None:
    portfolio = _portfolio()
    backtest = portfolio.backtest()

    report = portfolio.report(language="en")

    assert f"| Rebalances | {len(backtest.rebalance_dates)} |" in report
    assert "| Policy | periodic (monthly) |" in report


@pytest.mark.parametrize(
    ("policy", "label"),
    [
        (RebalancePolicy.buy_and_hold(), "buy and hold (no rebalancing)"),
        (RebalancePolicy.threshold(0.05), "threshold (±5.0%)"),
    ],
)
def test_policies_are_described(policy: RebalancePolicy, label: str) -> None:
    assert f"| Policy | {label} |" in _portfolio(policy).report(language="en")


def test_single_holding_portfolio() -> None:
    portfolio = Portfolio.from_weights("Solo", [_asset("AAA.MC", 1)], [1.0])

    report = portfolio.report()

    assert "Con un único activo no hay correlaciones que mostrar." in report
    assert "No se comprobaron los huecos" in report


def test_mixed_hours_use_weekly_returns() -> None:
    madrid = _asset("SAN.MC", 1)
    new_york = _asset("SPY", 2, exchange=EXCHANGES["XNYS"])
    portfolio = Portfolio.from_weights("Global", [madrid, new_york], [0.5, 0.5])

    report = portfolio.report(language="en")

    assert "Correlations of weekly returns" in report
    assert "use weekly returns to avoid the bias of non-synchronous closes" in report


def test_multi_market_portfolios_explain_their_union_calendar() -> None:
    madrid = _asset("SAN.MC", 1)
    new_york = _asset("SPY", 2, exchange=EXCHANGES["XNYS"])
    portfolio = Portfolio.from_weights("Global", [madrid, new_york], [0.5, 0.5])

    report = portfolio.report(language="en")

    periods = f"{portfolio.periods_per_year:,.0f}"
    assert portfolio.periods_per_year > 252  # synthetic weekdays: no shared holidays
    assert (
        f"Annualised with {periods} periods per year, the density observed on the union" in report
    )
    assert "Annualised with 252 periods per year for the market" in _portfolio().report(
        language="en"
    )


def test_same_offset_markets_are_synchronous() -> None:
    madrid = _asset("SAN.MC", 1)
    frankfurt = _asset("SAP.DE", 2, exchange=EXCHANGES["XETR"])
    portfolio = Portfolio.from_weights("Europe", [madrid, frankfurt], [0.5, 0.5])
    backtest = portfolio.backtest()

    choice = choose_frequency(portfolio, ReportOptions(), backtest.start, backtest.end)

    assert choice.frequency is Frequency.DAY_1
    assert choice.reason is None


def test_short_mixed_histories_keep_daily_returns_and_say_so() -> None:
    short = business_days(60)
    portfolio = Portfolio.from_weights(
        "Short",
        [
            _asset("SAN.MC", 1, index=short),
            _asset("SPY", 2, index=short, exchange=EXCHANGES["XNYS"]),
        ],
        [0.5, 0.5],
    )

    report = portfolio.report(language="en")

    assert "the history is too short for weekly returns" in report
    assert "Correlations of daily returns" in report


def test_crypto_and_equities_have_different_schedules() -> None:
    days = pd.date_range("2024-01-01", periods=400, freq="D")
    crypto = make_series(
        gbm_prices(400, seed=4, periods_per_year=365),
        symbol="BTC-EUR",
        index=days,
        asset_class=AssetClass.CRYPTO,
        exchange=EXCHANGES["CRYPTO"],
    )
    equity = _asset("SAN.MC", 1, index=business_days(286, start="2024-01-01"))
    portfolio = Portfolio.from_weights("Mixed", [equity, crypto], [0.7, 0.3])
    backtest = portfolio.backtest()

    choice = choose_frequency(portfolio, ReportOptions(), backtest.start, backtest.end)

    assert choice.frequency is Frequency.WEEK_1
    assert choice.reason == "nonsynchronous"


def test_explicit_correlation_frequency_wins() -> None:
    report = _portfolio().report(language="en", correlation_frequency="1mo")

    assert "Correlations of monthly returns" in report


def test_identical_findings_are_merged_across_holdings() -> None:
    report = _portfolio().report(language="en")

    assert (
        "| Warning | AAA.MC, BBB.MC, CCC.MC | Prices are not adjusted for dividends or splits"
        in report
    )


def test_late_holdings_and_stale_marks_are_explained() -> None:
    late = _asset("LATE.MC", 4, index=business_days(300, start="2024-06-03"))
    early = _asset("AAA.MC", 1, index=business_days(400))
    portfolio = Portfolio.from_weights("Late", [early, late], [0.5, 0.5])

    report = portfolio.report(language="en")

    assert "when LATE.MC starts trading" in report
    assert "AAA.MC was valued with prices up to" in report


def test_holdings_with_too_little_data_in_the_common_period_show_dashes() -> None:
    # ENDING stops trading two sessions after LATE starts: too little data to measure it.
    ending = _asset("ENDING.MC", 1, index=business_days(300))
    late = _asset("LATE.MC", 2, index=business_days(60, start=str(ending.prices.index[-2].date())))
    portfolio = Portfolio.from_weights("Brief", [ending, late], [0.5, 0.5])

    report = portfolio.report(language="en")

    assert "| ENDING.MC | — | — | — | — | — |" in report


def test_leverage_is_reported() -> None:
    assets = [_asset("AAA.MC", 1), _asset("BBB.MC", 2)]
    portfolio = Portfolio.from_weights("Long-short", assets, [1.5, -0.5], allow_short=True)

    report = portfolio.report(language="en")

    assert "Gross exposure is 200%" in report


def test_simulation_section_and_its_diagnostics() -> None:
    report = _portfolio().report(
        language="en", simulation=SimulationConfig(n_paths=300, horizon=21, seed=1)
    )

    assert "## Monte Carlo simulation" in report
    assert "| Paths | 300 |" in report
    assert "uses the historical mean as expected return" in report


def test_a_simulation_of_other_assets_is_rejected() -> None:
    other = _asset("ZZZ", 9).monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    with pytest.raises(DomainError, match="calibrated on"):
        _portfolio().report(simulation=other)


def test_quality_summary_and_details_for_several_holdings() -> None:
    prices = gbm_prices(N, seed=5)
    prices[200:210] = prices[200]
    frozen = make_series(prices, symbol="FRZ.MC", index=INDEX)
    portfolio = Portfolio.from_weights("Q", [_asset("AAA.MC", 1), frozen], [0.5, 0.5])

    report = portfolio.report(language="en")

    assert "| FRZ.MC | 504 | Warning | 1 |" in report
    assert "| AAA.MC | 504 | OK | 0 |" in report
    assert "| FRZ.MC | Warning | Frozen prices | 1 |" in report


def test_analysis_is_shared_by_report_and_charts() -> None:
    analysis = PortfolioAnalysis.compute(_portfolio(), ReportOptions())

    assert analysis.risk["share"].sum() == pytest.approx(1.0)
    assert analysis.ex_ante_volatility > 0
    assert analysis.diversification_ratio >= 1.0
    assert analysis.annual_turnover > 0
    assert analysis.years == pytest.approx((N - 1) / 252)
