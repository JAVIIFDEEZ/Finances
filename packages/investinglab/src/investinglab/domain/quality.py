"""Data-quality diagnostics of price series (ADR-0015).

Quality issues are *diagnostics*, not validation errors: a series with an outlier is still
a valid series (the outlier may be a real crash). The report lists what looks suspicious,
how serious it is and where, and leaves the data untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.analytics import log_returns
from investinglab.analytics.quality import (
    missing_sessions,
    ohlc_violations,
    robust_zscores,
    split_like_jumps,
    stale_runs,
    unexpected_sessions,
)

if TYPE_CHECKING:
    from investinglab.domain.series import PriceSeries

# Column and adjustment labels (kept as plain values to avoid an import cycle with series).
_VOLUME: Final = "volume"
_ADJ_CLOSE: Final = "adj_close"
_RAW: Final = "raw"

__all__ = [
    "DataQualityReport",
    "IssueKind",
    "QualityIssue",
    "QualityThresholds",
    "Severity",
    "assess_quality",
]


class IssueKind(StrEnum):
    """Kind of data-quality issue."""

    MISSING_SESSIONS = "missing_sessions"
    UNEXPECTED_SESSIONS = "unexpected_sessions"
    OUTLIER_RETURNS = "outlier_returns"
    SUSPECTED_SPLIT = "suspected_split"
    STALE_PRICES = "stale_prices"
    OHLC_INCONSISTENT = "ohlc_inconsistent"
    ZERO_VOLUME = "zero_volume"
    SHORT_HISTORY = "short_history"


class Severity(StrEnum):
    """How much an issue may distort the analysis."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """0 for info, 1 for warning, 2 for critical."""
        return list(Severity).index(self)


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    """Tunable thresholds of the detectors.

    Attributes:
        outlier_zscore: Robust z-score of a log return above which it is flagged.
        split_tolerance: Relative tolerance to match a price ratio with a split factor.
        stale_run: Consecutive identical prices that count as a frozen feed.
        min_history_years: Minimum span for reliable annualised statistics.
        missing_warning_ratio: Share of missing sessions above which it is a warning.
    """

    outlier_zscore: float = 8.0
    split_tolerance: float = 0.02
    stale_run: int = 5
    min_history_years: float = 1.0
    missing_warning_ratio: float = 0.01


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """One diagnosed issue.

    Attributes:
        kind: What was detected.
        severity: How much it may distort the analysis.
        message: Human-readable explanation.
        timestamps: Affected dates (empty for whole-series issues).
    """

    kind: IssueKind
    severity: Severity
    message: str
    timestamps: tuple[pd.Timestamp, ...] = ()

    @property
    def count(self) -> int:
        """Number of affected dates."""
        return len(self.timestamps)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Diagnostics of one series.

    Attributes:
        symbol: Instrument symbol.
        observations: Number of observations.
        start: First observation.
        end: Last observation.
        expected_sessions: Market sessions in the observed range, when a calendar was used.
        issues: Diagnosed issues, most severe first.
    """

    symbol: str
    observations: int
    start: pd.Timestamp
    end: pd.Timestamp
    expected_sessions: int | None
    issues: tuple[QualityIssue, ...]

    @property
    def ok(self) -> bool:
        """``True`` when no issue is a warning or worse."""
        return all(issue.severity is Severity.INFO for issue in self.issues)

    @property
    def worst_severity(self) -> Severity | None:
        """Highest severity found, ``None`` when there is no issue at all."""
        if not self.issues:
            return None
        return max((issue.severity for issue in self.issues), key=lambda s: s.rank)

    def issues_of(self, kind: IssueKind) -> tuple[QualityIssue, ...]:
        """Issues of one kind."""
        return tuple(issue for issue in self.issues if issue.kind is kind)

    def to_frame(self) -> pd.DataFrame:
        """One row per issue: ``kind``, ``severity``, ``count``, ``first``, ``message``."""
        return pd.DataFrame(
            [
                {
                    "kind": issue.kind.value,
                    "severity": issue.severity.value,
                    "count": issue.count,
                    "first": issue.timestamps[0] if issue.timestamps else pd.NaT,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
            columns=["kind", "severity", "count", "first", "message"],
        )

    def summary(self) -> str:
        """Short human-readable summary."""
        if not self.issues:
            return f"{self.symbol}: no data-quality issues"
        parts = [f"{issue.severity.value}: {issue.message}" for issue in self.issues]
        return f"{self.symbol}: " + "; ".join(parts)


def _sessions_of(series: PriceSeries) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(series.bars.index)
    if series.frequency.is_intraday:
        local = index.tz_convert(series.timezone).tz_localize(None)
        return pd.DatetimeIndex(local.normalize().unique())
    return index


def _dates(index: pd.Index) -> tuple[pd.Timestamp, ...]:
    return tuple(pd.Timestamp(ts) for ts in index)


def assess_quality(
    series: PriceSeries,
    *,
    expected_sessions: pd.DatetimeIndex | None = None,
    thresholds: QualityThresholds | None = None,
) -> DataQualityReport:
    """Diagnose a price series without modifying it.

    Args:
        series: Series to inspect.
        expected_sessions: Official market sessions (session labels) covering the series,
            to detect missing and unexpected observations. Skipped when ``None``.
        thresholds: Detector thresholds.
    """
    limits = thresholds or QualityThresholds()
    issues: list[QualityIssue] = []
    sessions = _sessions_of(series)

    if expected_sessions is not None:
        missing = missing_sessions(sessions, pd.DatetimeIndex(expected_sessions))
        if len(missing):
            window = expected_sessions[
                (expected_sessions >= sessions.min()) & (expected_sessions <= sessions.max())
            ]
            ratio = len(missing) / max(len(window), 1)
            issues.append(
                QualityIssue(
                    IssueKind.MISSING_SESSIONS,
                    Severity.WARNING if ratio > limits.missing_warning_ratio else Severity.INFO,
                    f"{len(missing)} market sessions without data ({ratio:.1%})",
                    _dates(missing),
                )
            )
        extra = unexpected_sessions(sessions, pd.DatetimeIndex(expected_sessions))
        if len(extra):
            issues.append(
                QualityIssue(
                    IssueKind.UNEXPECTED_SESSIONS,
                    Severity.WARNING,
                    f"{len(extra)} observations on non-trading days (wrong calendar or bad data?)",
                    _dates(extra),
                )
            )

    prices = series.prices
    zscores = robust_zscores(log_returns(prices))
    flagged = zscores[zscores.abs() > limits.outlier_zscore]
    if len(flagged):
        issues.append(
            QualityIssue(
                IssueKind.OUTLIER_RETURNS,
                Severity.WARNING,
                f"{len(flagged)} returns beyond {limits.outlier_zscore:g} robust standard "
                "deviations (bad ticks or genuine shocks: review, not removed)",
                _dates(flagged.index),
            )
        )

    jumps = split_like_jumps(prices, tolerance=limits.split_tolerance)
    if len(jumps):
        unadjusted = series.adjustment == _RAW and _ADJ_CLOSE not in series.bars.columns
        ratios = ", ".join(f"{ratio:.3g}" for ratio in jumps.iloc[:5])
        issues.append(
            QualityIssue(
                IssueKind.SUSPECTED_SPLIT,
                Severity.CRITICAL if unadjusted else Severity.WARNING,
                f"{len(jumps)} price jumps with split-like ratios ({ratios}); "
                + ("prices are not adjusted" if unadjusted else "check the adjustment"),
                _dates(jumps.index),
            )
        )

    runs = stale_runs(prices, min_length=limits.stale_run)
    if runs:
        longest = max(length for _, _, length in runs)
        issues.append(
            QualityIssue(
                IssueKind.STALE_PRICES,
                Severity.WARNING,
                f"{len(runs)} runs of identical prices (longest: {longest} observations)",
                tuple(start for start, _, _ in runs),
            )
        )

    violations = ohlc_violations(series.bars)
    if len(violations):
        issues.append(
            QualityIssue(
                IssueKind.OHLC_INCONSISTENT,
                Severity.WARNING,
                f"{len(violations)} bars where high/low contradict open/close",
                _dates(violations),
            )
        )

    if _VOLUME in series.bars.columns:
        volume = series.bars[_VOLUME]
        zero = volume.index[(volume == 0).to_numpy()]
        if len(zero):
            issues.append(
                QualityIssue(
                    IssueKind.ZERO_VOLUME,
                    Severity.INFO,
                    f"{len(zero)} observations with zero volume",
                    _dates(zero),
                )
            )

    years = (len(series) - 1) / series.periods_per_year
    if years < limits.min_history_years:
        issues.append(
            QualityIssue(
                IssueKind.SHORT_HISTORY,
                Severity.WARNING,
                f"only {years:.2f} years of history; annualised statistics are unreliable",
            )
        )

    issues.sort(key=lambda issue: -issue.severity.rank)
    expected_count: int | None = None
    if expected_sessions is not None:
        window = expected_sessions[
            (expected_sessions >= sessions.min()) & (expected_sessions <= sessions.max())
        ]
        expected_count = len(window)
    return DataQualityReport(
        symbol=series.symbol,
        observations=len(series),
        start=series.start,
        end=series.end,
        expected_sessions=expected_count,
        issues=tuple(issues),
    )
