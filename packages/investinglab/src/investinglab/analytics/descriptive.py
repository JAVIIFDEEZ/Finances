"""Descriptive statistics of return distributions and annualisation helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "ReturnMoments",
    "annualize_mean",
    "annualize_volatility",
    "cagr",
    "describe_returns",
]


@dataclass(frozen=True, slots=True)
class ReturnMoments:
    """Sample moments of a return distribution (per period, not annualised).

    Attributes:
        count: Number of returns.
        mean: Arithmetic mean.
        std: Sample standard deviation (``ddof=1``); ``nan`` with fewer than two returns.
        skewness: Bias-corrected sample skewness; ``nan`` with fewer than three returns.
        excess_kurtosis: Bias-corrected excess kurtosis (normal = 0); ``nan`` with fewer
            than four returns.
        minimum: Worst return.
        maximum: Best return.
    """

    count: int
    mean: float
    std: float
    skewness: float
    excess_kurtosis: float
    minimum: float
    maximum: float


def describe_returns(returns: pd.Series | np.ndarray) -> ReturnMoments:
    """Compute the sample moments of a return series, ignoring NaN values."""
    values = np.asarray(returns, dtype="float64")
    values = values[~np.isnan(values)]
    count = int(values.size)
    nan = float("nan")
    if count == 0:
        return ReturnMoments(0, nan, nan, nan, nan, nan, nan)

    constant = bool(np.ptp(values) == 0.0)
    std = nan
    if count >= 2:  # noqa: PLR2004 - a sample deviation needs two values
        std = 0.0 if constant else float(values.std(ddof=1))
    skewness, kurtosis = (nan, nan) if constant else _shape(values)
    return ReturnMoments(
        count=count,
        mean=float(values.mean()),
        std=std,
        skewness=skewness,
        excess_kurtosis=kurtosis,
        minimum=float(values.min()),
        maximum=float(values.max()),
    )


def _shape(values: np.ndarray) -> tuple[float, float]:
    """Bias-corrected sample skewness and excess kurtosis (adjusted Fisher-Pearson)."""
    n = values.size
    deviations = values - values.mean()
    m2 = float(np.mean(deviations**2))
    m3 = float(np.mean(deviations**3))
    m4 = float(np.mean(deviations**4))
    nan = float("nan")
    if not m2**2 > 0.0:
        # Spread so small it underflows (e.g. subnormal numbers): shape is undefined.
        return nan, nan
    skewness = (
        nan if n < 3 else (m3 / m2**1.5) * math.sqrt(n * (n - 1)) / (n - 2)  # noqa: PLR2004
    )
    excess = m4 / m2**2 - 3.0
    kurtosis = (
        nan
        if n < 4  # noqa: PLR2004
        else ((n + 1) * excess + 6.0) * (n - 1) / ((n - 2) * (n - 3))
    )
    return skewness, kurtosis


def annualize_mean(mean: float, periods_per_year: float) -> float:
    """Annualise an arithmetic per-period mean return: ``mean * periods_per_year``."""
    return mean * periods_per_year


def annualize_volatility(std: float, periods_per_year: float) -> float:
    """Annualise a per-period volatility with the square-root-of-time rule."""
    return std * math.sqrt(periods_per_year)


def cagr(total_return: float, periods: int, periods_per_year: float) -> float:
    """Compound annual growth rate implied by a total return earned over ``periods`` periods.

    Args:
        total_return: Simple total return, e.g. ``0.21`` for +21 %.
        periods: Number of return periods elapsed (observations minus one).
        periods_per_year: Periods in a year for the series' frequency and market.

    Returns:
        The geometric annualised return; ``nan`` when it is undefined (no periods, or a
        total loss of 100 % or more) and ``inf`` when extrapolating a very short window
        overflows.
    """
    if periods <= 0 or total_return <= -1.0 or periods_per_year <= 0:
        return float("nan")
    years = periods / periods_per_year
    exponent = math.log1p(total_return) / years
    try:
        return math.expm1(exponent)
    except OverflowError:
        # Annualising a tiny window (e.g. minutes of data) can exceed float range.
        return math.inf
