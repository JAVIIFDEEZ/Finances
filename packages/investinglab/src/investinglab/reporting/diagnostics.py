"""Diagnostics and warnings: what the reader should know before trusting the figures.

Each rule turns a measurable condition into a :class:`Diagnostic` with a severity, an
explanation quoting the figures behind it and a recommendation, in the report language.
Rules never change the data or the metrics: they only explain their limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.domain.instruments import AssetClass
from investinglab.domain.quality import IssueKind, Severity
from investinglab.domain.series import PriceAdjustment, PriceField
from investinglab.domain.simulation import DriftAssumption
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.quality import DataQualityReport, QualityIssue
    from investinglab.domain.series import PriceSeries
    from investinglab.domain.simulation import SimulationResult
    from investinglab.reporting.i18n import Translator

__all__ = [
    "Diagnostic",
    "correlation_diagnostics",
    "data_diagnostics",
    "history_diagnostics",
    "issue_message",
    "level_label",
    "metrics_diagnostics",
    "portfolio_structure_diagnostics",
    "risk_diagnostics",
    "simulation_diagnostics",
    "sort_diagnostics",
    "staleness_diagnostics",
]

NORMALITY_P_VALUE: Final = 0.01
"""Below this Jarque-Bera p-value, returns are reported as non-normal."""
MIN_TAIL_OBSERVATIONS: Final = 10
"""Fewer observations beyond the VaR quantile make the tail estimate fragile."""
RISK_CONCENTRATION_SHARE: Final = 0.5
HIGH_CORRELATION: Final = 0.9
MAX_HIGH_CORRELATION_PAIRS: Final = 5
STALE_MARK_PERIODS: Final = 5
HIGH_ANNUAL_TURNOVER: Final = 1.0
TRUNCATION_DAYS: Final = 90
WIDE_INTERVAL_RATIO: Final = 0.1
"""Width of the simulated VaR interval, relative to the VaR, beyond which more paths help."""

# Days between the last observation and the download beyond which the data may be stale.
_LAG_DAYS: Final[dict[Frequency, float]] = {
    Frequency.DAY_1: 7,
    Frequency.WEEK_1: 14,
    Frequency.MONTH_1: 45,
    Frequency.QUARTER_1: 120,
    Frequency.YEAR_1: 400,
}
_INTRADAY_LAG_DAYS: Final = 3.0
_DIVIDEND_PAYERS: Final = frozenset({AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUND})


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding, ready to print.

    Attributes:
        severity: How much it may distort conclusions.
        message: What was found, with the figures behind it.
        advice: What to do about it.
        subject: Symbol it refers to; ``None`` for the whole report subject.
    """

    severity: Severity
    message: str
    advice: str
    subject: str | None = None


def sort_diagnostics(items: Iterable[Diagnostic]) -> list[Diagnostic]:
    """Most severe first, keeping the original order within a severity."""
    return sorted(items, key=lambda item: -item.severity.rank)


def level_label(level: float, tr: Translator) -> str:
    """A confidence level as a percentage (``0.95`` → ``95 %``, ``0.975`` → ``97,5 %``)."""
    decimals = 0 if math.isclose(level * 100, round(level * 100)) else 1
    return tr.percent(level, decimals)


# ── Data quality ────────────────────────────────────────────────────


def issue_message(issue: QualityIssue, tr: Translator) -> str:
    """The issue explained in the report language (its English message as a fallback)."""
    details = issue.details
    kind = issue.kind
    try:
        if kind is IssueKind.MISSING_SESSIONS:
            params = {
                "count": tr.integer(float(details["count"])),
                "ratio": tr.percent(float(details["ratio"])),
            }
        elif kind is IssueKind.OUTLIER_RETURNS:
            params = {
                "count": tr.integer(float(details["count"])),
                "threshold": tr.number(float(details["threshold"]), 0),
            }
        elif kind is IssueKind.SUSPECTED_SPLIT:
            status = "adjusted" if float(details["adjusted"]) else "unadjusted"
            params = {
                "count": tr.integer(float(details["count"])),
                "ratios": str(details["ratios"]),
                "status": tr.text(f"issue.suspected_split.{status}"),
            }
        elif kind is IssueKind.STALE_PRICES:
            params = {
                "runs": tr.integer(float(details["runs"])),
                "longest": tr.integer(float(details["longest"])),
            }
        elif kind is IssueKind.SHORT_HISTORY:
            params = {"years": tr.number(float(details["years"]))}
        else:
            params = {"count": tr.integer(float(details["count"]))}
    except KeyError:
        return issue.message
    return tr.text(f"issue.{kind.value}.message", **params)


def _quality_diagnostics(
    report: DataQualityReport, tr: Translator, subject: str | None
) -> list[Diagnostic]:
    return [
        Diagnostic(
            issue.severity, issue_message(issue, tr), tr.text(f"diag.{issue.kind.value}"), subject
        )
        for issue in report.issues
        if issue.severity is not Severity.INFO
    ]


def _lag_days(series: PriceSeries) -> float:
    retrieved = pd.Timestamp(series.retrieved_at).tz_convert(UTC)
    end = pd.Timestamp(series.end)
    if end.tzinfo is not None:
        return (retrieved - end).total_seconds() / 86_400
    return float((retrieved.tz_localize(None).normalize() - end).days)


def data_diagnostics(
    series: PriceSeries,
    quality: DataQualityReport,
    tr: Translator,
    *,
    subject: str | None = None,
) -> list[Diagnostic]:
    """Quality issues (warning or worse), price adjustment and data freshness of a series."""
    found = _quality_diagnostics(quality, tr, subject)
    adjusted_close = series.price_field is PriceField.ADJ_CLOSE
    if series.asset_class in _DIVIDEND_PAYERS and not adjusted_close:
        if series.adjustment is PriceAdjustment.RAW:
            found.append(
                Diagnostic(
                    Severity.WARNING,
                    tr.text("diag.unadjusted"),
                    tr.text("diag.unadjusted.advice"),
                    subject,
                )
            )
        elif series.adjustment is PriceAdjustment.SPLITS:
            found.append(
                Diagnostic(
                    Severity.INFO,
                    tr.text("diag.split_only"),
                    tr.text("diag.unadjusted.advice"),
                    subject,
                )
            )
    limit = _INTRADAY_LAG_DAYS if series.frequency.is_intraday else _LAG_DAYS[series.frequency]
    lag = _lag_days(series)
    if lag > limit:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text(
                    "diag.data_lag",
                    end=tr.date(series.end),
                    days=tr.integer(math.floor(lag)),
                    retrieved=tr.date(series.retrieved_at),
                ),
                tr.text("diag.data_lag.advice"),
                subject,
            )
        )
    return found


# ── Metrics ─────────────────────────────────────────────────────────


def metrics_diagnostics(
    metrics: RiskMetrics,
    tr: Translator,
    *,
    levels: Sequence[float],
    zero_risk_free: bool,
    subject: str | None = None,
) -> list[Diagnostic]:
    """Statistical reliability of the metrics: Sharpe uncertainty, normality, tail depth."""
    found: list[Diagnostic] = []
    low, high = metrics.sharpe_confidence_interval(0.95)
    if math.isfinite(low) and math.isfinite(high) and low <= 0.0 <= high:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text("diag.sharpe_uncertain", low=tr.number(low), high=tr.number(high)),
                tr.text("diag.sharpe_uncertain.advice"),
                subject,
            )
        )
    p_value = metrics.normality_p_value
    if math.isfinite(p_value) and p_value < NORMALITY_P_VALUE:
        found.append(
            Diagnostic(
                Severity.WARNING,
                tr.text(
                    "diag.non_normal",
                    p_value=tr.number(p_value, 3),
                    skewness=tr.number(metrics.skewness),
                    kurtosis=tr.number(metrics.excess_kurtosis),
                ),
                tr.text("diag.non_normal.advice"),
                subject,
            )
        )
    level = max(levels)
    tail = math.floor(metrics.periods * (1.0 - level))
    if tail < MIN_TAIL_OBSERVATIONS:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text("diag.thin_tail", level=level_label(level, tr), count=tr.integer(tail)),
                tr.text("diag.thin_tail.advice"),
                subject,
            )
        )
    if zero_risk_free:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text("diag.zero_risk_free"),
                tr.text("diag.zero_risk_free.advice"),
                subject,
            )
        )
    return found


# ── Portfolio ───────────────────────────────────────────────────────


def history_diagnostics(
    series: Sequence[PriceSeries], common_start: pd.Timestamp, tr: Translator
) -> list[Diagnostic]:
    """Warn when one holding's short history truncates the portfolio analysis."""
    earliest = min(series, key=lambda s: s.start)
    latest = max(series, key=lambda s: s.start)
    gap = pd.Timestamp(latest.start) - pd.Timestamp(earliest.start)
    if gap <= pd.Timedelta(days=TRUNCATION_DAYS):
        return []
    return [
        Diagnostic(
            Severity.INFO,
            tr.text(
                "diag.history_truncated",
                start=tr.date(common_start),
                symbol=latest.symbol,
                earliest=tr.date(earliest.start),
            ),
            tr.text("diag.history_truncated.advice"),
        )
    ]


def risk_diagnostics(contributions: pd.DataFrame, tr: Translator) -> list[Diagnostic]:
    """Risk concentrated in one holding, and holdings that hedge the rest."""
    found: list[Diagnostic] = []
    if len(contributions) < 2:  # noqa: PLR2004
        return found
    for symbol, row in contributions.iterrows():
        share, weight = float(row["share"]), float(row["weight"])
        if share > RISK_CONCENTRATION_SHARE and share > 1.5 * abs(weight):
            found.append(
                Diagnostic(
                    Severity.WARNING,
                    tr.text(
                        "diag.risk_concentration",
                        symbol=symbol,
                        share=tr.percent(share),
                        weight=tr.percent(weight),
                    ),
                    tr.text("diag.risk_concentration.advice"),
                    str(symbol),
                )
            )
        elif share < 0.0:
            found.append(
                Diagnostic(
                    Severity.INFO,
                    tr.text("diag.hedge", symbol=symbol, share=tr.percent(share)),
                    tr.text("diag.hedge.advice"),
                    str(symbol),
                )
            )
    return found


def correlation_diagnostics(correlation: pd.DataFrame, tr: Translator) -> list[Diagnostic]:
    """Pairs of holdings so correlated that they barely diversify each other."""
    values = correlation.to_numpy()
    symbols = [str(c) for c in correlation.columns]
    upper = np.triu(np.ones_like(values, dtype=bool), k=1)
    rows, cols = np.nonzero(upper & (values > HIGH_CORRELATION))
    pairs = sorted(zip(rows, cols, strict=True), key=lambda rc: -values[rc[0], rc[1]])
    return [
        Diagnostic(
            Severity.INFO,
            tr.text(
                "diag.high_correlation",
                first=symbols[i],
                second=symbols[j],
                correlation=tr.number(float(values[i, j])),
            ),
            tr.text("diag.high_correlation.advice"),
        )
        for i, j in pairs[:MAX_HIGH_CORRELATION_PAIRS]
    ]


def staleness_diagnostics(staleness: pd.DataFrame, tr: Translator) -> list[Diagnostic]:
    """Holdings valued with old prices for many periods in a row."""
    found: list[Diagnostic] = []
    for symbol in staleness.columns:
        ages = staleness[symbol].dropna()
        if ages.empty:
            continue
        oldest = float(ages.max())
        if oldest > STALE_MARK_PERIODS:
            found.append(
                Diagnostic(
                    Severity.INFO,
                    tr.text(
                        "diag.stale_marks",
                        symbol=symbol,
                        age=tr.integer(oldest),
                        share=tr.percent(float((ages > 0).mean())),
                    ),
                    tr.text("diag.stale_marks.advice"),
                    str(symbol),
                )
            )
    return found


def portfolio_structure_diagnostics(
    *, annual_turnover: float, gross_exposure: float, tr: Translator
) -> list[Diagnostic]:
    """Turnover without costs and leverage."""
    found: list[Diagnostic] = []
    if math.isfinite(annual_turnover) and annual_turnover > HIGH_ANNUAL_TURNOVER:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text("diag.high_turnover", turnover=tr.percent(annual_turnover, 0)),
                tr.text("diag.high_turnover.advice"),
            )
        )
    if gross_exposure > 1.0 + 1e-9:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text("diag.leverage", exposure=tr.percent(gross_exposure, 0)),
                tr.text("diag.leverage.advice"),
            )
        )
    return found


# ── Simulation ──────────────────────────────────────────────────────


def simulation_diagnostics(result: SimulationResult, tr: Translator) -> list[Diagnostic]:
    """Noise of a historical drift and precision of the simulated VaR."""
    found: list[Diagnostic] = []
    config, calibration = result.config, result.calibration
    if config.drift is DriftAssumption.HISTORICAL:
        weights = calibration.weights
        variance = float(weights @ calibration.covariance @ weights)
        years = calibration.observations / calibration.periods_per_year
        error = math.sqrt(max(variance, 0.0) * calibration.periods_per_year / years)
        found.append(
            Diagnostic(
                Severity.WARNING,
                tr.text("diag.historical_drift", error=tr.percent(error)),
                tr.text("diag.historical_drift.advice"),
            )
        )
    level = max(config.confidence_levels)
    var = result.value_at_risk(level)
    if var.value > 0 and (var.upper - var.lower) / var.value > WIDE_INTERVAL_RATIO:
        found.append(
            Diagnostic(
                Severity.INFO,
                tr.text(
                    "diag.wide_var_interval",
                    level=level_label(level, tr),
                    low=tr.percent(var.lower),
                    high=tr.percent(var.upper),
                ),
                tr.text("diag.wide_var_interval.advice"),
            )
        )
    return found
