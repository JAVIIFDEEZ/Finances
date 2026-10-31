"""Risk and risk-adjusted performance measures on return series.

Conventions:

* Returns are simple, per period. Missing values (NaN) are ignored.
* ``risk_free`` is the risk-free return **per period** (a scalar or a series aligned with
  the returns). Ratios are annualised with ``periods_per_year``.
* Value at Risk and Conditional VaR (Expected Shortfall) are reported as **positive loss
  fractions per period**: ``0.023`` means "a 2.3 % loss over one period".
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Final

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from investinglab.analytics.descriptive import describe_returns

__all__ = [
    "VaRMethod",
    "beta",
    "calmar_ratio",
    "conditional_value_at_risk",
    "downside_deviation",
    "effective_number_of_assets",
    "excess_returns",
    "herfindahl_index",
    "per_period_rate",
    "sharpe_ratio",
    "sortino_ratio",
    "value_at_risk",
]

_NAN = float("nan")


class VaRMethod(StrEnum):
    """How the loss quantile is estimated."""

    HISTORICAL = "historical"
    """Empirical quantile of the observed returns (no distributional assumption)."""
    GAUSSIAN = "gaussian"
    """Normal distribution with the sample mean and volatility."""
    CORNISH_FISHER = "cornish_fisher"
    """Normal quantile corrected for sample skewness and excess kurtosis."""


def _clean(values: pd.Series | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype="float64")
    return array[~np.isnan(array)]


def per_period_rate(annual_rate: float | pd.Series, periods_per_year: float) -> float | pd.Series:
    """Convert an annual (compounded) rate into the equivalent rate per period.

    Works for a scalar or a series of annual rates in decimal form (``0.03`` for 3 %).
    """
    if isinstance(annual_rate, pd.Series):
        return (1.0 + annual_rate) ** (1.0 / periods_per_year) - 1.0
    return float((1.0 + annual_rate) ** (1.0 / periods_per_year) - 1.0)


def excess_returns(returns: pd.Series, risk_free: float | pd.Series = 0.0) -> pd.Series:
    """Returns in excess of the per-period risk-free rate.

    A risk-free series is aligned on the return dates; dates without a rate give NaN.
    """
    if isinstance(risk_free, pd.Series):
        return returns - risk_free.reindex(returns.index)
    return returns - risk_free


def sharpe_ratio(
    returns: pd.Series, *, periods_per_year: float, risk_free: float | pd.Series = 0.0
) -> float:
    """Annualised Sharpe ratio: mean excess return over its volatility, times √periods."""
    excess = _clean(excess_returns(returns, risk_free))
    if excess.size < 2:  # noqa: PLR2004
        return _NAN
    std = float(excess.std(ddof=1))
    if std == 0.0 or not math.isfinite(std):
        return _NAN
    return float(excess.mean() / std * math.sqrt(periods_per_year))


def downside_deviation(returns: pd.Series | np.ndarray, *, target: float = 0.0) -> float:
    """Root mean square of the shortfalls below ``target`` (all periods in the denominator)."""
    values = _clean(returns)
    if values.size == 0:
        return _NAN
    shortfall = np.minimum(values - target, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


def sortino_ratio(
    returns: pd.Series, *, periods_per_year: float, risk_free: float | pd.Series = 0.0
) -> float:
    """Annualised Sortino ratio: mean excess return over the downside deviation."""
    excess = _clean(excess_returns(returns, risk_free))
    if excess.size < 2:  # noqa: PLR2004
        return _NAN
    downside = downside_deviation(excess)
    if downside == 0.0:
        return _NAN
    return float(excess.mean() / downside * math.sqrt(periods_per_year))


def calmar_ratio(annualized_return: float, max_drawdown: float) -> float:
    """Annualised return divided by the absolute maximum drawdown."""
    if not max_drawdown < 0.0:
        return _NAN
    return annualized_return / abs(max_drawdown)


def _cornish_fisher_z(z: np.ndarray, skew: float, kurt: float) -> np.ndarray:
    return np.asarray(
        z + (z**2 - 1) * skew / 6 + (z**3 - 3 * z) * kurt / 24 - (2 * z**3 - 5 * z) * skew**2 / 36,
        dtype="float64",
    )


_CF_GRID: Final = (np.arange(20_000) + 0.5) / 20_000


def _cornish_fisher_quantiles(skew: float, kurt: float) -> np.ndarray:
    """Cornish-Fisher standardised quantiles on ``_CF_GRID``, monotonically rearranged.

    Outside its domain of validity (strong skewness or kurtosis) the expansion is not
    monotonic; sorting it (Chernozhukov, Fernandez-Val & Galichon, 2010) restores a proper
    quantile function, which keeps Expected Shortfall at least as large as VaR.
    """
    return np.sort(_cornish_fisher_z(sp_stats.norm.ppf(_CF_GRID), skew, kurt))


def value_at_risk(
    returns: pd.Series | np.ndarray,
    level: float = 0.95,
    method: VaRMethod | str = VaRMethod.HISTORICAL,
) -> float:
    """Value at Risk at confidence ``level`` as a positive loss fraction per period.

    Raises:
        ValueError: If ``level`` is not in (0, 1).
    """
    _check_level(level)
    values = _clean(returns)
    if values.size < 2:  # noqa: PLR2004
        return _NAN
    how = VaRMethod(method)
    tail = 1.0 - level
    if how is VaRMethod.HISTORICAL:
        return float(-np.quantile(values, tail))
    moments = describe_returns(values)
    if how is VaRMethod.CORNISH_FISHER:
        quantiles = _cornish_fisher_quantiles(
            _zero_if_nan(moments.skewness), _zero_if_nan(moments.excess_kurtosis)
        )
        z = float(np.interp(tail, _CF_GRID, quantiles))
    else:
        z = float(sp_stats.norm.ppf(tail))
    return float(-(moments.mean + moments.std * z))


def conditional_value_at_risk(
    returns: pd.Series | np.ndarray,
    level: float = 0.95,
    method: VaRMethod | str = VaRMethod.HISTORICAL,
) -> float:
    """Expected loss beyond the VaR (Expected Shortfall), as a positive loss fraction.

    The historical estimate averages the returns at or below the VaR quantile; the
    Gaussian one uses the closed form; Cornish-Fisher integrates its corrected quantile
    function over the tail.

    Raises:
        ValueError: If ``level`` is not in (0, 1).
    """
    _check_level(level)
    values = _clean(returns)
    if values.size < 2:  # noqa: PLR2004
        return _NAN
    how = VaRMethod(method)
    tail = 1.0 - level
    if how is VaRMethod.HISTORICAL:
        threshold = np.quantile(values, tail)
        return float(-values[values <= threshold].mean())
    moments = describe_returns(values)
    if how is VaRMethod.GAUSSIAN:
        z = float(sp_stats.norm.ppf(tail))
        return float(-(moments.mean - moments.std * sp_stats.norm.pdf(z) / tail))
    # Cornish-Fisher: average of the (rearranged) corrected quantiles over the tail.
    quantiles = _cornish_fisher_quantiles(
        _zero_if_nan(moments.skewness), _zero_if_nan(moments.excess_kurtosis)
    )
    in_tail = quantiles[tail >= _CF_GRID]
    tail_mean = float(in_tail.mean()) if in_tail.size else float(quantiles[0])
    return float(-(moments.mean + moments.std * tail_mean))


def beta(asset_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Sensitivity of an asset to a benchmark on the dates where both are observed."""
    joined = pd.concat([asset_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(joined) < 2:  # noqa: PLR2004
        return _NAN
    variance = float(joined.iloc[:, 1].var(ddof=1))
    if variance == 0.0:
        return _NAN
    return float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / variance)


def herfindahl_index(weights: pd.Series | np.ndarray) -> float:
    """Concentration of a portfolio: sum of squared normalised absolute weights.

    1 for a single asset, ``1/n`` for ``n`` equal weights.
    """
    absolute = np.abs(np.asarray(weights, dtype="float64"))
    total = absolute.sum()
    if total == 0.0:
        return _NAN
    return float(np.sum((absolute / total) ** 2))


def effective_number_of_assets(weights: pd.Series | np.ndarray) -> float:
    """Inverse Herfindahl index: how many equally weighted assets the portfolio behaves like."""
    index = herfindahl_index(weights)
    return 1.0 / index if index > 0 else _NAN


def _check_level(level: float) -> None:
    if not 0.0 < level < 1.0:
        raise ValueError(f"Confidence level must be in (0, 1), got {level}")


def _zero_if_nan(value: float) -> float:
    return 0.0 if math.isnan(value) else value
