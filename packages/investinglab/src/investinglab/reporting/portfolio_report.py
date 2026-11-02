"""Markdown report of a portfolio (``Portfolio.report()``, B1-T1 §4.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab.domain.errors import DomainError
from investinglab.domain.portfolio import RebalanceKind
from investinglab.domain.quality import Severity
from investinglab.reporting.analysis import PortfolioAnalysis
from investinglab.reporting.diagnostics import (
    Diagnostic,
    correlation_diagnostics,
    data_diagnostics,
    history_diagnostics,
    metrics_diagnostics,
    portfolio_structure_diagnostics,
    risk_diagnostics,
    simulation_diagnostics,
    sort_diagnostics,
    staleness_diagnostics,
)
from investinglab.reporting.i18n import MISSING
from investinglab.reporting.markdown import Align, MarkdownBuilder
from investinglab.reporting.sections import (
    diagnostics_summary,
    resolve_simulation,
    span_years,
    write_diagnostics,
    write_drawdowns,
    write_methodology,
    write_metrics,
    write_quality,
    write_simulation,
    write_tail_risk,
)

if TYPE_CHECKING:
    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.portfolio import Portfolio, RebalancePolicy
    from investinglab.domain.quality import DataQualityReport
    from investinglab.domain.simulation import SimulationResult
    from investinglab.reporting.i18n import Translator
    from investinglab.reporting.markdown import MarkdownReport
    from investinglab.reporting.options import ReportOptions

__all__ = ["build_portfolio_report", "policy_label"]


def policy_label(policy: RebalancePolicy, tr: Translator) -> str:
    """The rebalancing policy in words."""
    if policy.kind is RebalanceKind.PERIODIC and policy.frequency is not None:
        return tr.text("rebalance.periodic", frequency=tr.frequency(policy.frequency.value))
    if policy.kind is RebalanceKind.THRESHOLD and policy.band is not None:
        return tr.text("rebalance.threshold", band=tr.percent(policy.band))
    return tr.text("rebalance.buy_and_hold")


def _comparison_row(name: str, metrics: RiskMetrics | None, tr: Translator) -> tuple[str, ...]:
    if metrics is None:
        return (name, MISSING, MISSING, MISSING, MISSING, MISSING)
    return (
        name,
        tr.percent(metrics.total_return),
        tr.percent(metrics.annualized_return),
        tr.percent(metrics.annualized_volatility),
        tr.number(metrics.sharpe_ratio),
        tr.percent(metrics.max_drawdown),
    )


def _write_composition(doc: MarkdownBuilder, portfolio: Portfolio, tr: Translator) -> None:
    rows = []
    for holding in portfolio.holdings:
        series = holding.series
        exchange = series.instrument.exchange
        rows.append(
            (
                series.symbol,
                series.name,
                tr.text(f"asset_class.{series.asset_class.value}"),
                exchange.code if exchange else MISSING,
                str(series.currency),
                tr.percent(holding.weight),
                tr.date(series.start),
                tr.date(series.end),
                tr.integer(len(series)),
                series.source.provider,
            )
        )
    doc.table(
        [
            tr.text("common.asset"),
            tr.text("field.name"),
            tr.text("composition.class"),
            tr.text("field.exchange"),
            tr.text("field.currency"),
            tr.text("composition.weight"),
            tr.text("composition.start"),
            tr.text("composition.end"),
            tr.text("composition.observations"),
            tr.text("field.source"),
        ],
        rows,
        align=[Align.LEFT] * 5 + [Align.RIGHT, Align.LEFT, Align.LEFT, Align.RIGHT, Align.LEFT],
    )
    doc.paragraph(
        tr.text(
            "composition.concentration",
            hhi=tr.number(portfolio.herfindahl_index, 3),
            effective=tr.number(portfolio.effective_number_of_assets, 1),
            gross=tr.percent(portfolio.gross_exposure, 0),
        )
    )


def _write_comparison(
    doc: MarkdownBuilder, analysis: PortfolioAnalysis, options: ReportOptions, tr: Translator
) -> None:
    backtest = analysis.backtest
    rows = [_comparison_row(tr.text("common.portfolio"), analysis.metrics, tr)]
    for series in analysis.portfolio.series:
        try:
            metrics: RiskMetrics | None = series.between(backtest.start, backtest.end).metrics(
                risk_free_rate=options.risk_free_rate, levels=options.confidence_levels
            )
        except DomainError:
            metrics = None
        rows.append(_comparison_row(series.symbol, metrics, tr))
    doc.table(
        [
            tr.text("common.asset"),
            tr.text("comparison.total"),
            tr.text("comparison.cagr"),
            tr.text("comparison.volatility"),
            tr.text("comparison.sharpe"),
            tr.text("comparison.max_drawdown"),
        ],
        rows,
        align=[Align.LEFT] + [Align.RIGHT] * 5,
    )
    doc.note(tr.text("comparison.note", start=tr.date(backtest.start), end=tr.date(backtest.end)))


def _write_correlation(doc: MarkdownBuilder, analysis: PortfolioAnalysis, tr: Translator) -> None:
    correlation = analysis.correlation
    if len(correlation) < 2:  # noqa: PLR2004
        doc.paragraph(tr.text("correlation.single"))
        return
    symbols = [str(c) for c in correlation.columns]
    doc.table(
        ["", *symbols],
        [
            (symbol, *(tr.number(float(v)) for v in correlation.loc[symbol].to_numpy()))
            for symbol in symbols
        ],
        align=[Align.LEFT] + [Align.RIGHT] * len(symbols),
    )
    doc.note(tr.text("correlation.note", frequency=tr.frequency(analysis.choice.frequency.value)))


def _write_risk(doc: MarkdownBuilder, analysis: PortfolioAnalysis, tr: Translator) -> None:
    risk = analysis.risk
    doc.table(
        [
            tr.text("common.asset"),
            tr.text("risk.weight"),
            tr.text("risk.volatility"),
            tr.text("risk.contribution"),
            tr.text("risk.share"),
        ],
        [
            (
                str(symbol),
                tr.percent(float(row["weight"])),
                tr.percent(float(row["volatility"])),
                tr.percent(float(row["annualized_contribution"]), 2),
                tr.percent(float(row["share"])),
            )
            for symbol, row in risk.iterrows()
        ],
        align=[Align.LEFT] + [Align.RIGHT] * 4,
    )
    doc.note(
        tr.text(
            "risk.note",
            frequency=tr.frequency(analysis.choice.frequency.value),
            volatility=tr.percent(analysis.ex_ante_volatility),
            ratio=tr.number(analysis.diversification_ratio),
        )
    )


def _write_rebalancing(doc: MarkdownBuilder, analysis: PortfolioAnalysis, tr: Translator) -> None:
    backtest = analysis.backtest
    doc.table(
        [tr.text("metric.metric"), tr.text("common.value")],
        [
            (tr.text("rebalancing.policy"), policy_label(analysis.portfolio.rebalance, tr)),
            (tr.text("rebalancing.count"), tr.integer(len(backtest.rebalance_dates))),
            (tr.text("rebalancing.turnover"), tr.percent(backtest.total_turnover)),
            (tr.text("rebalancing.annual_turnover"), tr.percent(analysis.annual_turnover)),
        ],
        align=(Align.LEFT, Align.RIGHT),
    )
    doc.note(tr.text("rebalancing.note"))


def _write_valuation(doc: MarkdownBuilder, analysis: PortfolioAnalysis, tr: Translator) -> None:
    staleness = analysis.backtest.staleness
    rows = []
    for series in analysis.portfolio.series:
        ages = staleness[series.symbol].dropna()
        exchange = series.instrument.exchange
        rows.append(
            (
                series.symbol,
                exchange.code if exchange else MISSING,
                series.timezone,
                tr.integer(int((ages == 0).sum())),
                tr.percent(float((ages > 0).mean())) if len(ages) else MISSING,
                tr.integer(float(ages.max())) if len(ages) else MISSING,
            )
        )
    doc.table(
        [
            tr.text("common.asset"),
            tr.text("field.exchange"),
            tr.text("valuation.timezone"),
            tr.text("valuation.observations"),
            tr.text("valuation.stale_share"),
            tr.text("valuation.max_age"),
        ],
        rows,
        align=[Align.LEFT, Align.LEFT, Align.LEFT, Align.RIGHT, Align.RIGHT, Align.RIGHT],
    )
    doc.note(tr.text("valuation.note"))


def _diagnostics(
    analysis: PortfolioAnalysis,
    qualities: list[DataQualityReport],
    simulation: SimulationResult | None,
    options: ReportOptions,
    tr: Translator,
) -> list[Diagnostic]:
    portfolio = analysis.portfolio
    found: list[Diagnostic] = []
    for series, quality in zip(portfolio.series, qualities, strict=True):
        found += data_diagnostics(series, quality, tr, subject=series.symbol)
    found += history_diagnostics(portfolio.series, analysis.backtest.start, tr)
    found += metrics_diagnostics(
        analysis.metrics,
        tr,
        levels=options.confidence_levels,
        zero_risk_free=options.uses_constant_zero_rate,
    )
    found += risk_diagnostics(analysis.risk, tr)
    if len(analysis.correlation) > 1:
        found += correlation_diagnostics(analysis.correlation, tr)
    reason = analysis.choice.reason
    if reason is not None:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text(f"diag.{reason}", frequency=tr.frequency(analysis.choice.frequency.value)),
                tr.text(f"diag.{reason}.advice"),
            )
        )
    found += staleness_diagnostics(analysis.backtest.staleness, tr)
    found += portfolio_structure_diagnostics(
        annual_turnover=analysis.annual_turnover,
        gross_exposure=portfolio.gross_exposure,
        tr=tr,
    )
    if simulation is not None:
        found += simulation_diagnostics(simulation, tr)
    return sort_diagnostics(found)


def build_portfolio_report(portfolio: Portfolio, options: ReportOptions) -> MarkdownReport:
    """Write the report of ``portfolio``.

    Sections: summary, composition, return and risk, performance comparison over the common
    period, tail risk, correlations, risk contribution, rebalancing, drawdowns, calendars
    and valuation, Monte Carlo (when requested), data quality, diagnostics and methodology.
    """
    tr = options.translator
    analysis = PortfolioAnalysis.compute(portfolio, options)
    metrics, backtest = analysis.metrics, analysis.backtest
    qualities = [options.quality_for(s.symbol) or s.quality() for s in portfolio.series]
    simulation = resolve_simulation(options.simulation, portfolio.monte_carlo, portfolio.symbols)
    diagnostics = _diagnostics(analysis, qualities, simulation, options, tr)

    doc = MarkdownBuilder()
    doc.heading(options.title or tr.text("portfolio.title", name=portfolio.name), 1)
    doc.paragraph(
        tr.text(
            "portfolio.summary",
            name=portfolio.name,
            holdings=tr.plural("count.assets", len(portfolio)),
            currency=str(portfolio.base_currency),
            policy=policy_label(portfolio.rebalance, tr),
            start=tr.date(backtest.start),
            end=tr.date(backtest.end),
            years=tr.number(span_years(backtest.start, backtest.end), 1),
            total_return=tr.percent(metrics.total_return),
            cagr=tr.percent(metrics.annualized_return),
            volatility=tr.percent(metrics.annualized_volatility),
            sharpe=tr.number(metrics.sharpe_ratio),
            max_drawdown=tr.percent(metrics.max_drawdown),
        )
    )
    doc.paragraph(diagnostics_summary(diagnostics, tr))

    doc.heading(tr.text("section.composition"))
    _write_composition(doc, portfolio, tr)
    doc.heading(tr.text("section.performance"))
    write_metrics(doc, metrics, tr)
    doc.heading(tr.text("section.comparison"))
    _write_comparison(doc, analysis, options, tr)
    doc.heading(tr.text("section.tail"))
    write_tail_risk(doc, metrics, tr, portfolio.frequency)
    doc.heading(tr.text("section.correlation"))
    _write_correlation(doc, analysis, tr)
    doc.heading(tr.text("section.risk_contribution"))
    _write_risk(doc, analysis, tr)
    doc.heading(tr.text("section.rebalancing"))
    _write_rebalancing(doc, analysis, tr)
    doc.heading(tr.text("section.drawdowns"))
    write_drawdowns(doc, backtest.drawdown_episodes(top=options.top_drawdowns), tr)
    doc.heading(tr.text("section.valuation"))
    _write_valuation(doc, analysis, tr)
    if simulation is not None:
        doc.heading(tr.text("section.simulation"))
        write_simulation(doc, simulation, tr, portfolio.frequency)
    doc.heading(tr.text("section.quality"))
    write_quality(doc, qualities, tr)
    doc.heading(tr.text("section.diagnostics"))
    write_diagnostics(doc, diagnostics, tr, scoped=True)
    doc.heading(tr.text("section.methodology"))
    write_methodology(doc, tr, periods_per_year=portfolio.periods_per_year, portfolio=True)
    return doc.build()
