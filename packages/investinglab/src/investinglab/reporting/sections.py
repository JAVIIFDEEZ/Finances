"""Report sections shared by the series and portfolio reports."""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

import pandas as pd

from investinglab import __version__
from investinglab.analytics import VaRMethod
from investinglab.domain.errors import DomainError
from investinglab.domain.quality import Severity
from investinglab.domain.simulation import (
    CovarianceEstimator,
    DriftAssumption,
    SimulationResult,
)
from investinglab.domain.time import CALENDAR_YEAR_DAYS
from investinglab.reporting.diagnostics import Diagnostic, issue_message, level_label
from investinglab.reporting.i18n import MISSING
from investinglab.reporting.markdown import Align

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.quality import DataQualityReport
    from investinglab.domain.series import PriceSeries
    from investinglab.domain.simulation import SimulationConfig
    from investinglab.domain.time import Frequency
    from investinglab.reporting.i18n import Translator
    from investinglab.reporting.markdown import MarkdownBuilder

__all__ = [
    "diagnostics_summary",
    "resolve_simulation",
    "series_data_rows",
    "span_years",
    "write_diagnostics",
    "write_drawdowns",
    "write_methodology",
    "write_metrics",
    "write_quality",
    "write_simulation",
    "write_tail_risk",
]

_LR = (Align.LEFT, Align.RIGHT)


def span_years(start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Calendar years between two timestamps."""
    return (pd.Timestamp(end) - pd.Timestamp(start)).days / CALENDAR_YEAR_DAYS


def resolve_simulation(
    option: SimulationConfig | SimulationResult | None,
    run: Callable[[SimulationConfig], SimulationResult],
    symbols: Sequence[str],
) -> SimulationResult | None:
    """The simulation to report: none, a given result, or a configuration to run.

    Raises:
        DomainError: If a given result simulated other assets.
    """
    if option is None:
        return None
    if isinstance(option, SimulationResult):
        if tuple(option.calibration.symbols) != tuple(symbols):
            raise DomainError(
                f"The simulation was calibrated on {list(option.calibration.symbols)}, "
                f"not on {list(symbols)}"
            )
        return option
    return run(option)


def diagnostics_summary(diagnostics: Sequence[Diagnostic], tr: Translator) -> str:
    """One line counting the diagnostics by severity."""
    if not diagnostics:
        return tr.text("summary.clean")
    counts = Counter(d.severity for d in diagnostics)
    return tr.text(
        "summary.diagnostics",
        critical=counts[Severity.CRITICAL],
        warning=counts[Severity.WARNING],
        info=counts[Severity.INFO],
    )


def series_data_rows(series: PriceSeries, tr: Translator) -> list[tuple[str, str]]:
    """Field/value rows describing a series and its provenance."""
    instrument = series.instrument
    identifiers = [
        f"{name.upper()} {value}"
        for name in ("isin", "figi", "cik", "lei")
        if (value := getattr(instrument.identifiers, name)) is not None
    ]
    exchange = instrument.exchange
    source = series.source.provider + (
        f" ({series.source.dataset})" if series.source.dataset else ""
    )
    return [
        (tr.text("field.symbol"), series.symbol),
        (tr.text("field.name"), series.name),
        (tr.text("field.asset_class"), tr.text(f"asset_class.{series.asset_class.value}")),
        (tr.text("field.exchange"), f"{exchange.code} · {exchange.name}" if exchange else MISSING),
        (tr.text("field.currency"), str(series.currency)),
        (tr.text("field.identifiers"), ", ".join(identifiers) or MISSING),
        (tr.text("field.frequency"), tr.frequency(series.frequency.value)),
        (tr.text("field.prices"), tr.text(f"adjustment.{series.adjustment.value}")),
        (tr.text("field.price_field"), tr.text(f"price_field.{series.price_field.value}")),
        (
            tr.text("field.period"),
            tr.text("common.period", start=tr.date(series.start), end=tr.date(series.end)),
        ),
        (tr.text("field.observations"), tr.integer(len(series))),
        (tr.text("field.periods_per_year"), tr.number(series.periods_per_year, 0)),
        (tr.text("field.source"), source),
        (tr.text("field.retrieved"), tr.date(series.retrieved_at)),
    ]


def write_metrics(doc: MarkdownBuilder, metrics: RiskMetrics, tr: Translator) -> None:
    """The return and risk table."""
    low, high = metrics.sharpe_confidence_interval(0.95)
    interval = (
        tr.text("common.interval", low=tr.number(low), high=tr.number(high))
        if math.isfinite(low) and math.isfinite(high)
        else MISSING
    )
    rows = [
        ("metric.total_return", tr.percent(metrics.total_return)),
        ("metric.cagr", tr.percent(metrics.annualized_return)),
        ("metric.volatility", tr.percent(metrics.annualized_volatility)),
        ("metric.sharpe", tr.number(metrics.sharpe_ratio)),
        ("metric.sharpe_interval", interval),
        ("metric.sortino", tr.number(metrics.sortino_ratio)),
        ("metric.calmar", tr.number(metrics.calmar_ratio)),
        ("metric.max_drawdown", tr.percent(metrics.max_drawdown)),
        ("metric.best_period", tr.percent(metrics.best_period, 2)),
        ("metric.worst_period", tr.percent(metrics.worst_period, 2)),
        ("metric.positive_ratio", tr.percent(metrics.positive_ratio)),
        ("metric.skewness", tr.number(metrics.skewness)),
        ("metric.excess_kurtosis", tr.number(metrics.excess_kurtosis)),
        ("metric.normality", tr.number(metrics.normality_p_value, 3)),
        ("metric.risk_free", tr.percent(metrics.risk_free_rate, 2)),
    ]
    doc.table(
        [tr.text("metric.metric"), tr.text("common.value")],
        [(tr.text(key), value) for key, value in rows],
        align=_LR,
    )


def write_tail_risk(
    doc: MarkdownBuilder, metrics: RiskMetrics, tr: Translator, frequency: Frequency
) -> None:
    """VaR and CVaR per level and method, with a note on the convention."""
    rows = [
        (
            level_label(entry.level, tr),
            tr.text(f"var_method.{VaRMethod(entry.method).value}"),
            tr.percent(entry.value_at_risk, 2),
            tr.percent(entry.conditional_value_at_risk, 2),
        )
        for entry in metrics.tail
    ]
    doc.table(
        [tr.text("tail.level"), tr.text("tail.method"), tr.text("tail.var"), tr.text("tail.cvar")],
        rows,
        align=(Align.LEFT, Align.LEFT, Align.RIGHT, Align.RIGHT),
    )
    doc.note(tr.text("tail.note", frequency=tr.frequency(frequency.value)))


def write_drawdowns(doc: MarkdownBuilder, episodes: pd.DataFrame, tr: Translator) -> None:
    """The deepest drawdown episodes."""
    if episodes.empty:
        doc.paragraph(tr.text("drawdown.none"))
        return
    rows = []
    for rank, episode in enumerate(episodes.to_dict("records"), start=1):
        recovery = episode["recovery"]
        rows.append(
            (
                str(rank),
                tr.date(pd.Timestamp(episode["peak"])),
                tr.date(pd.Timestamp(episode["trough"])),
                tr.text("drawdown.open") if pd.isna(recovery) else tr.date(pd.Timestamp(recovery)),
                tr.percent(float(episode["depth"])),
                tr.integer(float(episode["decline_periods"])),
                tr.integer(float(episode["duration_periods"])),
            )
        )
    doc.table(
        [
            tr.text("drawdown.rank"),
            tr.text("drawdown.peak"),
            tr.text("drawdown.trough"),
            tr.text("drawdown.recovery"),
            tr.text("drawdown.depth"),
            tr.text("drawdown.decline"),
            tr.text("drawdown.duration"),
        ],
        rows,
        align=(
            Align.RIGHT,
            Align.LEFT,
            Align.LEFT,
            Align.LEFT,
            Align.RIGHT,
            Align.RIGHT,
            Align.RIGHT,
        ),
    )


def _issue_rows(
    report: DataQualityReport, tr: Translator, *, with_symbol: bool
) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = []
    for issue in report.issues:
        row = (
            tr.text(f"severity.{issue.severity.value}"),
            tr.text(f"issue.{issue.kind.value}"),
            tr.integer(issue.count) if issue.timestamps else MISSING,
            tr.date(issue.timestamps[0]) if issue.timestamps else MISSING,
            issue_message(issue, tr),
        )
        rows.append((report.symbol, *row) if with_symbol else row)
    return rows


def write_quality(
    doc: MarkdownBuilder, reports: Sequence[DataQualityReport], tr: Translator
) -> None:
    """Data-quality findings: a detail table for one series, a summary plus details for many."""
    headers = [
        tr.text("quality.severity"),
        tr.text("quality.issue"),
        tr.text("quality.count"),
        tr.text("quality.first"),
        tr.text("quality.detail"),
    ]
    align = [Align.LEFT, Align.LEFT, Align.RIGHT, Align.LEFT, Align.LEFT]
    if len(reports) == 1:
        report = reports[0]
        if report.expected_sessions is not None:
            doc.paragraph(
                tr.text("quality.calendar", expected=tr.integer(report.expected_sessions))
            )
        else:
            doc.paragraph(tr.text("quality.no_calendar"))
        if report.issues:
            doc.table(headers, _issue_rows(report, tr, with_symbol=False), align=align)
        else:
            doc.paragraph(tr.text("quality.none"))
    else:
        doc.table(
            [
                tr.text("common.asset"),
                tr.text("field.observations"),
                tr.text("quality.worst"),
                tr.text("quality.issues"),
            ],
            [
                (
                    report.symbol,
                    tr.integer(report.observations),
                    tr.text(f"severity.{report.worst_severity.value}")
                    if report.worst_severity is not None
                    else tr.text("quality.ok"),
                    tr.integer(len(report.issues)),
                )
                for report in reports
            ],
            align=(Align.LEFT, Align.RIGHT, Align.LEFT, Align.RIGHT),
        )
        detail = [row for report in reports for row in _issue_rows(report, tr, with_symbol=True)]
        if detail:
            doc.table([tr.text("common.asset"), *headers], detail, align=[Align.LEFT, *align])
    doc.note(tr.text("quality.policy"))


def write_diagnostics(
    doc: MarkdownBuilder,
    diagnostics: Sequence[Diagnostic],
    tr: Translator,
    *,
    scoped: bool = False,
) -> None:
    """The diagnostics table (with a scope column for portfolios)."""
    if not diagnostics:
        doc.paragraph(tr.text("diag.none"))
        return
    headers = [tr.text("diag.severity"), tr.text("diag.message"), tr.text("diag.advice")]
    if scoped:
        diagnostics = _merge_subjects(diagnostics)
    rows: list[tuple[str, ...]] = []
    for item in diagnostics:
        row: tuple[str, ...] = (
            tr.text(f"severity.{item.severity.value}"),
            item.message,
            item.advice,
        )
        if scoped:
            scope = item.subject or tr.text("common.portfolio")
            row = (row[0], scope, *row[1:])
        rows.append(row)
    if scoped:
        headers.insert(1, tr.text("diag.subject"))
    doc.table(headers, rows)


def _merge_subjects(diagnostics: Sequence[Diagnostic]) -> list[Diagnostic]:
    """One row per identical finding, listing every asset it applies to."""
    merged: dict[tuple[Severity, str, str, bool], list[str]] = {}
    for item in diagnostics:
        key = (item.severity, item.message, item.advice, item.subject is None)
        subjects = merged.setdefault(key, [])
        if item.subject is not None:
            subjects.append(item.subject)
    return [
        Diagnostic(severity, message, advice, ", ".join(subjects) or None)
        for (severity, message, advice, _), subjects in merged.items()
    ]


def _drift_label(result: SimulationResult, tr: Translator) -> str:
    drift = result.config.drift
    if drift is DriftAssumption.RISK_FREE:
        return tr.text("drift.risk_free", rate=tr.percent(result.config.risk_free_rate, 2))
    return tr.text(f"drift.{drift.value}")


def write_simulation(
    doc: MarkdownBuilder, result: SimulationResult, tr: Translator, frequency: Frequency
) -> None:
    """Configuration and results of a Monte Carlo simulation."""
    config, calibration = result.config, result.calibration
    if config.covariance is CovarianceEstimator.LEDOIT_WOLF:
        shrinkage = calibration.shrinkage if calibration.shrinkage is not None else float("nan")
        covariance = tr.text("covariance.ledoit_wolf", shrinkage=tr.number(shrinkage, 3))
    else:
        covariance = tr.text("covariance.sample")
    settings = [
        (tr.text("simulation.model"), tr.text(f"model.{config.model.value}")),
        (tr.text("simulation.paths"), tr.integer(result.n_paths)),
        (
            tr.text("simulation.horizon"),
            tr.text(
                "simulation.horizon_value",
                periods=tr.plural("count.periods", result.horizon),
                frequency=tr.frequency(frequency.value),
            ),
        ),
        (tr.text("simulation.drift"), _drift_label(result, tr)),
        (tr.text("simulation.volatility"), tr.text(f"volatility.{config.volatility.value}")),
        (tr.text("simulation.covariance"), covariance),
        (tr.text("simulation.calibration"), tr.integer(calibration.observations)),
        (tr.text("simulation.seed"), str(config.seed) if config.seed is not None else MISSING),
        (tr.text("simulation.initial_value"), tr.number(config.initial_value)),
    ]
    doc.table([tr.text("common.field"), tr.text("common.value")], settings, align=_LR)

    expected = result.expected_value_estimate()
    rows = [
        (
            tr.text("simulation.expected"),
            f"{tr.number(expected.value)} (± {tr.number(expected.standard_error)})",
        ),
        (tr.text("simulation.median"), tr.number(result.median_terminal_value)),
        (tr.text("simulation.loss_probability"), tr.percent(result.probability_of_loss)),
    ]
    for level in config.confidence_levels:
        label = level_label(level, tr)
        var = result.value_at_risk(level)
        interval = tr.text("common.interval", low=tr.percent(var.lower), high=tr.percent(var.upper))
        rows += [
            (tr.text("simulation.var", level=label), f"{tr.percent(var.value)} ({interval})"),
            (
                tr.text("simulation.cvar", level=label),
                tr.percent(result.conditional_value_at_risk(level).value),
            ),
            (
                tr.text("simulation.drawdown_at_risk", level=label),
                tr.percent(result.drawdown_at_risk(level)),
            ),
        ]
    rows.append(
        (tr.text("simulation.expected_drawdown"), tr.percent(float(result.max_drawdowns.mean())))
    )
    doc.table([tr.text("metric.metric"), tr.text("common.value")], rows, align=_LR)
    doc.note(tr.text("simulation.note"))


def write_methodology(
    doc: MarkdownBuilder, tr: Translator, *, periods_per_year: float, portfolio: bool
) -> None:
    """Conventions behind every figure of the report."""
    items = [
        tr.text("method.returns"),
        tr.text("method.annualisation", periods=tr.number(periods_per_year, 0)),
        tr.text("method.sharpe"),
        tr.text("method.var"),
        tr.text("method.quality"),
    ]
    if portfolio:
        items.append(tr.text("method.portfolio"))
    doc.bullets(items)
    doc.paragraph(f"*{tr.text('method.footer', version=__version__)}*")
