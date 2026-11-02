"""Markdown report of one price series (``PriceSeries.report()``, B1-T1 §4.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab.reporting.diagnostics import (
    data_diagnostics,
    metrics_diagnostics,
    simulation_diagnostics,
    sort_diagnostics,
)
from investinglab.reporting.markdown import Align, MarkdownBuilder
from investinglab.reporting.sections import (
    diagnostics_summary,
    resolve_simulation,
    series_data_rows,
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
    from investinglab.domain.series import PriceSeries
    from investinglab.reporting.markdown import MarkdownReport
    from investinglab.reporting.options import ReportOptions

__all__ = ["build_series_report"]


def build_series_report(series: PriceSeries, options: ReportOptions) -> MarkdownReport:
    """Write the report of ``series``.

    Sections: summary, data and provenance, return and risk, tail risk, drawdowns, Monte
    Carlo (when requested), data quality, diagnostics and methodology.
    """
    tr = options.translator
    metrics = series.metrics(
        risk_free_rate=options.risk_free_rate, levels=options.confidence_levels
    )
    quality = options.quality_for(series.symbol) or series.quality()
    simulation = resolve_simulation(options.simulation, series.monte_carlo, (series.symbol,))
    diagnostics = sort_diagnostics(
        [
            *data_diagnostics(series, quality, tr),
            *metrics_diagnostics(
                metrics,
                tr,
                levels=options.confidence_levels,
                zero_risk_free=options.uses_constant_zero_rate,
            ),
            *(simulation_diagnostics(simulation, tr) if simulation is not None else ()),
        ]
    )

    doc = MarkdownBuilder()
    doc.heading(options.title or tr.text("series.title", symbol=series.symbol, name=series.name), 1)
    doc.paragraph(
        tr.text(
            "series.summary",
            start=tr.date(series.start),
            end=tr.date(series.end),
            years=tr.number(span_years(series.start, series.end), 1),
            observations=tr.integer(len(series)),
            frequency=tr.frequency(series.frequency.value),
            symbol=series.symbol,
            total_return=tr.percent(metrics.total_return),
            cagr=tr.percent(metrics.annualized_return),
            volatility=tr.percent(metrics.annualized_volatility),
            max_drawdown=tr.percent(metrics.max_drawdown),
        )
    )
    doc.paragraph(diagnostics_summary(diagnostics, tr))

    doc.heading(tr.text("section.data"))
    doc.table(
        [tr.text("common.field"), tr.text("common.value")],
        series_data_rows(series, tr),
        align=(Align.LEFT, Align.LEFT),
    )
    doc.heading(tr.text("section.performance"))
    write_metrics(doc, metrics, tr)
    doc.heading(tr.text("section.tail"))
    write_tail_risk(doc, metrics, tr, series.frequency)
    doc.heading(tr.text("section.drawdowns"))
    write_drawdowns(doc, series.drawdown_episodes(top=options.top_drawdowns), tr)
    if simulation is not None:
        doc.heading(tr.text("section.simulation"))
        write_simulation(doc, simulation, tr, series.frequency)
    doc.heading(tr.text("section.quality"))
    write_quality(doc, [quality], tr)
    doc.heading(tr.text("section.diagnostics"))
    write_diagnostics(doc, diagnostics, tr)
    doc.heading(tr.text("section.methodology"))
    write_methodology(doc, tr, periods_per_year=series.periods_per_year, portfolio=False)
    return doc.build()
