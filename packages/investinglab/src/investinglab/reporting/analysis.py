"""Portfolio figures computed once and shared by the Markdown report and the charts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics import correlation_from_covariance
from investinglab.domain.metrics import RiskMetrics
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from investinglab.domain.portfolio import Portfolio, PortfolioBacktest
    from investinglab.reporting.options import ReportOptions

__all__ = ["MIN_WEEKS_FOR_WEEKLY", "FrequencyChoice", "PortfolioAnalysis"]

MIN_WEEKS_FOR_WEEKLY: Final = 26
"""Common history needed (in weeks) to measure co-movement on weekly returns."""


@dataclass(frozen=True, slots=True)
class FrequencyChoice:
    """Frequency of the returns used for correlations and risk contributions.

    Attributes:
        frequency: The frequency used.
        reason: ``"nonsynchronous"`` when weekly returns were chosen because holdings trade
            on different hours or calendars, ``"weekly_unavailable"`` when that was needed
            but the history is too short, ``None`` otherwise.
    """

    frequency: Frequency
    reason: str | None = None


def _mixed_calendars(portfolio: Portfolio, when: pd.Timestamp) -> bool:
    """Whether holdings close at different instants (UTC offset) or keep different schedules.

    Madrid and Frankfurt share an offset and close together; New York does not.
    """
    series = portfolio.series
    moment = pd.Timestamp(when)
    naive = moment.tz_localize(None) if moment.tzinfo is not None else moment
    offsets = {
        naive.tz_localize(s.timezone, ambiguous=True, nonexistent="shift_forward").utcoffset()
        for s in series
    }
    schedules = {s.instrument.schedule for s in series}
    return len(offsets) > 1 or len(schedules) > 1


def choose_frequency(
    portfolio: Portfolio, options: ReportOptions, start: pd.Timestamp, end: pd.Timestamp
) -> FrequencyChoice:
    """Explicit option, or weekly returns when holdings' closes are not synchronous."""
    if options.correlation_frequency is not None:
        return FrequencyChoice(Frequency(options.correlation_frequency))
    native = portfolio.frequency
    if not _mixed_calendars(portfolio, end) or not native.is_finer_than(Frequency.WEEK_1):
        return FrequencyChoice(native)
    weeks = (pd.Timestamp(end) - pd.Timestamp(start)).days / 7
    if weeks >= MIN_WEEKS_FOR_WEEKLY:
        return FrequencyChoice(Frequency.WEEK_1, "nonsynchronous")
    return FrequencyChoice(native, "weekly_unavailable")


@dataclass(frozen=True, slots=True, eq=False)
class PortfolioAnalysis:
    """Everything the report and the charts need about a portfolio.

    Attributes:
        portfolio: The analysed portfolio.
        backtest: Historical path under the rebalancing policy.
        metrics: Return and risk metrics of the historical portfolio returns.
        choice: Frequency used for correlations and risk contributions.
        correlation: Correlation matrix at that frequency.
        risk: Risk contributions (``weight``, ``share``, ``annualized_contribution``...)
            plus each holding's annualised ``volatility``.
        ex_ante_volatility: Annualised volatility implied by the covariance and weights.
        diversification_ratio: Weighted average volatility over portfolio volatility.
        years: Length of the backtest in years (periods over periods per year).
        annual_turnover: Average one-way turnover per year.
    """

    portfolio: Portfolio
    backtest: PortfolioBacktest
    metrics: RiskMetrics
    choice: FrequencyChoice
    correlation: pd.DataFrame
    risk: pd.DataFrame
    ex_ante_volatility: float
    diversification_ratio: float
    years: float
    annual_turnover: float

    @classmethod
    def compute(cls, portfolio: Portfolio, options: ReportOptions) -> PortfolioAnalysis:
        """Backtest the portfolio and measure its risk structure."""
        backtest = portfolio.backtest()
        metrics = RiskMetrics.from_returns(
            backtest.returns,
            periods_per_year=portfolio.periods_per_year,
            risk_free_rate=options.risk_free_rate,
            levels=options.confidence_levels,
        )
        choice = choose_frequency(portfolio, options, backtest.start, backtest.end)
        covariance = portfolio.covariance(choice.frequency)
        risk = portfolio.risk_contributions(choice.frequency)
        periods = max(
            h.series.instrument.schedule.periods_per_year(choice.frequency) for h in portfolio
        )
        volatility = np.sqrt(np.clip(np.diag(covariance.to_numpy()), 0.0, None) * periods)
        risk["volatility"] = volatility
        ex_ante = float(risk["annualized_contribution"].sum())
        weighted = float(np.sum(np.abs(risk["weight"].to_numpy()) * volatility))
        years = (len(backtest.values) - 1) / portfolio.periods_per_year
        return cls(
            portfolio=portfolio,
            backtest=backtest,
            metrics=metrics,
            choice=choice,
            correlation=correlation_from_covariance(covariance),
            risk=risk,
            ex_ante_volatility=ex_ante,
            diversification_ratio=weighted / ex_ante if ex_ante > 0 else math.nan,
            years=years,
            annual_turnover=backtest.total_turnover / years if years > 0 else math.nan,
        )
