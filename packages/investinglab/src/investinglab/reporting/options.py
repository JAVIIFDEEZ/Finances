"""Options shared by ``report()`` (Markdown) and ``plots_report()`` (charts)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, TypedDict

import pandas as pd

from investinglab.domain.errors import DomainError
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS
from investinglab.domain.quality import DataQualityReport
from investinglab.domain.time import Frequency
from investinglab.reporting.i18n import Language, Translator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from investinglab.domain.simulation import SimulationConfig, SimulationResult

__all__ = ["ReportOptions", "ReportSettings"]

_MIN_ROLLING_WINDOW = 5
_RATE_BOUNDS = (-0.5, 1.0)
"""Plausible annual risk-free rates in decimal form (rejects percentages like 3.0)."""


class ReportSettings(TypedDict, total=False):
    """Keyword arguments accepted by ``report()`` and ``plots_report()``.

    They override the fields of :class:`ReportOptions` with the same name.
    """

    language: Language | str
    title: str | None
    risk_free_rate: float | pd.Series
    confidence_levels: Sequence[float]
    top_drawdowns: int
    quality: DataQualityReport | Mapping[str, DataQualityReport] | None
    simulation: SimulationConfig | SimulationResult | None
    correlation_frequency: Frequency | str | None
    rolling_window: int | None


def _rate_problem(values: Sequence[float]) -> str | None:
    finite = [v for v in values if not math.isnan(v)]
    if any(math.isinf(v) for v in finite):
        return "risk_free_rate must be finite"
    low, high = _RATE_BOUNDS
    if any(not low < v < high for v in finite):
        return "risk_free_rate is an annual decimal rate (0.03 = 3 %)"
    return None


@dataclass(frozen=True, slots=True, eq=False)
class ReportOptions:
    """What a report contains and how it is written.

    Attributes:
        language: ``es`` (default) or ``en``.
        title: Custom title; a descriptive one is used when ``None``.
        risk_free_rate: Effective annual risk-free rate (decimal) for Sharpe and Sortino: a
            constant or the point-in-time series known at each date.
        confidence_levels: Levels for VaR and CVaR.
        top_drawdowns: Number of drawdown episodes listed.
        quality: Precomputed data-quality report(s), e.g. checked against the official
            calendar by :class:`~investinglab.services.DataQualityService`; one report or a
            mapping by symbol. Missing ones are computed without a calendar.
        simulation: Include a Monte Carlo section: a configuration to run or a result.
        correlation_frequency: Frequency of the returns used for correlations and risk
            contributions; ``None`` picks weekly returns automatically when holdings trade
            on different hours or calendars.
        rolling_window: Window of the rolling-volatility chart (about three months of
            periods when ``None``).

    Raises:
        DomainError: Listing every invalid option.
    """

    language: Language | str = Language.ES
    title: str | None = None
    risk_free_rate: float | pd.Series = 0.0
    confidence_levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS
    top_drawdowns: int = 5
    quality: DataQualityReport | Mapping[str, DataQualityReport] | None = None
    simulation: SimulationConfig | SimulationResult | None = None
    correlation_frequency: Frequency | str | None = None
    rolling_window: int | None = None

    def __post_init__(self) -> None:  # noqa: PLR0912 - one check per option
        problems: list[str] = []
        try:
            object.__setattr__(self, "language", Language(self.language))
        except ValueError:
            problems.append(f"language must be one of {[lang.value for lang in Language]}")
        if self.title is not None and not self.title.strip():
            problems.append("title must not be empty")
        rate = self.risk_free_rate
        if isinstance(rate, pd.Series):
            if not isinstance(rate.index, pd.DatetimeIndex):
                problems.append("a risk_free_rate series needs a DatetimeIndex")
            problem = _rate_problem(rate.astype("float64").tolist())
        else:
            problem = _rate_problem([float(rate)])
        if problem:
            problems.append(problem)
        levels = tuple(float(level) for level in self.confidence_levels)
        if not levels or not all(0.0 < level < 1.0 for level in levels):
            problems.append("confidence_levels must be in (0, 1)")
        object.__setattr__(self, "confidence_levels", levels)
        if self.top_drawdowns < 1:
            problems.append("top_drawdowns must be at least 1")
        quality: object = self.quality
        if quality is not None and not isinstance(quality, DataQualityReport | Mapping):
            problems.append("quality must be a DataQualityReport or a mapping of them")
        if self.correlation_frequency is not None:
            try:
                object.__setattr__(
                    self, "correlation_frequency", Frequency(self.correlation_frequency)
                )
            except ValueError:
                problems.append(f"unknown correlation_frequency {self.correlation_frequency!r}")
        if self.rolling_window is not None and self.rolling_window < _MIN_ROLLING_WINDOW:
            problems.append(f"rolling_window must be at least {_MIN_ROLLING_WINDOW}")
        if problems:
            raise DomainError("Invalid report options: " + "; ".join(problems))

    @classmethod
    def resolve(cls, options: ReportOptions | None, settings: Mapping[str, Any]) -> ReportOptions:
        """``options`` (or the defaults) with the keyword ``settings`` applied on top."""
        base = options if options is not None else cls()
        return replace(base, **settings) if settings else base

    @property
    def translator(self) -> Translator:
        """Texts and number formats in the report language."""
        return Translator(self.language)

    @property
    def uses_constant_zero_rate(self) -> bool:
        """Whether Sharpe and Sortino use a flat 0 % risk-free rate."""
        rate = self.risk_free_rate
        return not isinstance(rate, pd.Series) and float(rate) == 0.0

    def quality_for(self, symbol: str) -> DataQualityReport | None:
        """The precomputed data-quality report of ``symbol``, if one was given."""
        if isinstance(self.quality, DataQualityReport):
            return self.quality if self.quality.symbol == symbol else None
        if isinstance(self.quality, Mapping):
            return self.quality.get(symbol)
        return None
