"""Risk and performance metrics of a return series (an asset or a portfolio)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics import (
    VaRMethod,
    cagr,
    calmar_ratio,
    conditional_value_at_risk,
    describe_returns,
    max_drawdown,
    per_period_rate,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
)
from investinglab.domain.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["DEFAULT_CONFIDENCE_LEVELS", "RiskMetrics", "TailRisk"]

DEFAULT_CONFIDENCE_LEVELS: Final = (0.95, 0.99)


@dataclass(frozen=True, slots=True)
class TailRisk:
    """Value at Risk and Expected Shortfall at one confidence level and method.

    Both are positive loss fractions **per period** (``0.02`` = a 2 % loss).
    """

    level: float
    method: VaRMethod
    value_at_risk: float
    conditional_value_at_risk: float


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    """Performance and risk summary of a return series.

    Attributes:
        start: First return date.
        end: Last return date.
        periods: Number of returns.
        periods_per_year: Annualisation factor.
        total_return: Compounded return over the whole period.
        annualized_return: Compound annual growth rate.
        annualized_volatility: Annualised standard deviation of returns.
        sharpe_ratio: Annualised Sharpe ratio net of the risk-free rate.
        sortino_ratio: Annualised Sortino ratio net of the risk-free rate.
        calmar_ratio: Annualised return over the absolute maximum drawdown.
        max_drawdown: Worst peak-to-trough decline of the compounded value (non-positive).
        best_period: Best single-period return.
        worst_period: Worst single-period return.
        positive_ratio: Share of periods with a positive return.
        skewness: Sample skewness of returns.
        excess_kurtosis: Sample excess kurtosis of returns.
        risk_free_rate: Average annual risk-free rate used (decimal).
        tail: VaR and CVaR for every requested level and method.
    """

    start: pd.Timestamp
    end: pd.Timestamp
    periods: int
    periods_per_year: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    best_period: float
    worst_period: float
    positive_ratio: float
    skewness: float
    excess_kurtosis: float
    risk_free_rate: float
    tail: tuple[TailRisk, ...]

    def tail_risk(
        self, level: float = 0.95, method: VaRMethod | str = VaRMethod.HISTORICAL
    ) -> TailRisk:
        """The VaR/CVaR entry for ``level`` and ``method``.

        Raises:
            KeyError: If that combination was not computed.
        """
        wanted = VaRMethod(method)
        for entry in self.tail:
            if math.isclose(entry.level, level) and entry.method is wanted:
                return entry
        raise KeyError(f"No tail risk computed for level={level} method={wanted.value}")

    @classmethod
    def from_returns(
        cls,
        returns: pd.Series,
        *,
        periods_per_year: float,
        risk_free_rate: float | pd.Series = 0.0,
        levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS,
        methods: Sequence[VaRMethod] = tuple(VaRMethod),
    ) -> RiskMetrics:
        """Compute the metrics of simple returns.

        Args:
            returns: Simple returns per period (NaN values are ignored).
            periods_per_year: Annualisation factor of the returns' frequency.
            risk_free_rate: Annual risk-free rate in decimal form: a constant or a series
                of rates known at each date (point-in-time), aligned on the returns.
            levels: Confidence levels for VaR and CVaR.
            methods: Estimation methods for VaR and CVaR.

        Raises:
            DomainError: With fewer than two returns.
        """
        clean = returns.dropna()
        if len(clean) < 2:  # noqa: PLR2004
            raise DomainError("Risk metrics need at least two returns")
        annual_rf: float | pd.Series
        if isinstance(risk_free_rate, pd.Series):
            annual_rf = risk_free_rate.reindex(clean.index)
            average_rf = float(annual_rf.mean())
        else:
            annual_rf = risk_free_rate
            average_rf = float(risk_free_rate)
        rf_per_period = per_period_rate(annual_rf, periods_per_year)

        moments = describe_returns(clean)
        growth = pd.concat(
            [pd.Series([1.0]), (1.0 + clean).cumprod().reset_index(drop=True)],
            ignore_index=True,
        )
        total = float(growth.iloc[-1] - 1.0)
        annual = cagr(total, len(clean), periods_per_year)
        drawdown = max_drawdown(growth)
        tail = tuple(
            TailRisk(
                level=level,
                method=method,
                value_at_risk=value_at_risk(clean, level, method),
                conditional_value_at_risk=conditional_value_at_risk(clean, level, method),
            )
            for level in levels
            for method in methods
        )
        return cls(
            start=pd.Timestamp(clean.index[0]),
            end=pd.Timestamp(clean.index[-1]),
            periods=len(clean),
            periods_per_year=periods_per_year,
            total_return=total,
            annualized_return=annual,
            annualized_volatility=float(moments.std * np.sqrt(periods_per_year)),
            sharpe_ratio=sharpe_ratio(
                clean, periods_per_year=periods_per_year, risk_free=rf_per_period
            ),
            sortino_ratio=sortino_ratio(
                clean, periods_per_year=periods_per_year, risk_free=rf_per_period
            ),
            calmar_ratio=calmar_ratio(annual, drawdown),
            max_drawdown=drawdown,
            best_period=moments.maximum,
            worst_period=moments.minimum,
            positive_ratio=float((clean > 0).mean()),
            skewness=moments.skewness,
            excess_kurtosis=moments.excess_kurtosis,
            risk_free_rate=average_rf,
            tail=tail,
        )
