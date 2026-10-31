"""Portfolio valuation engine with rebalancing, and risk decomposition.

The engine walks through time once: each period the holdings drift with their returns and,
on rebalancing dates (calendar) or when a weight drifts beyond a band (threshold), they are
reset to the target weights. Missing returns (an asset's market closed) mean the holding keeps
its last observed price that period, which is how a fund marks its NAV; the move is booked
when the market reopens (ADR-0008).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = ["RebalancedPath", "rebalanced_path", "risk_contributions"]


@dataclass(frozen=True, slots=True)
class RebalancedPath:
    """Result of :func:`rebalanced_path`.

    Attributes:
        returns: Portfolio return per period (first period excluded: it is the start).
        values: Portfolio value per period, starting at the initial value.
        weights: Weights held at the end of each period, after any rebalancing.
        turnover: One-way turnover traded at each period (0 when not rebalancing).
        rebalanced: Dates on which the portfolio was rebalanced.
    """

    returns: pd.Series
    values: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    rebalanced: pd.DatetimeIndex


def rebalanced_path(
    asset_returns: pd.DataFrame,
    target_weights: np.ndarray,
    *,
    rebalance_dates: pd.DatetimeIndex | None = None,
    band: float | None = None,
    initial_value: float = 1.0,
) -> RebalancedPath:
    """Value a portfolio through time under a rebalancing policy.

    Args:
        asset_returns: Simple returns with one column per asset. The first row is the start
            date (its returns are ignored). NaN means "not observed": the holding is marked
            at its last price for that period.
        target_weights: Target weights, aligned with the columns, summing to 1.
        rebalance_dates: Dates after whose close the holdings return to the targets.
        band: Rebalance whenever any weight deviates more than ``band`` from its target.
        initial_value: Portfolio value at the start date.

    Returns:
        The return, value, weight and turnover paths. ``rebalance_dates=None`` with
        ``band=None`` is buy-and-hold.
    """
    targets = np.asarray(target_weights, dtype="float64")
    returns = asset_returns.to_numpy(dtype="float64", na_value=np.nan)
    returns = np.nan_to_num(returns, nan=0.0)
    index = asset_returns.index
    scheduled = (
        np.zeros(len(index), dtype=bool)
        if rebalance_dates is None
        else np.asarray(index.isin(rebalance_dates))
    )

    periods = len(index)
    weights = np.full((periods, targets.size), np.nan)
    portfolio_returns = np.full(periods, np.nan)
    values = np.full(periods, np.nan)
    turnover = np.zeros(periods)
    current = targets.copy()
    weights[0] = current
    values[0] = initial_value
    rebalanced: list[pd.Timestamp] = []

    for t in range(1, periods):
        grown = current * (1.0 + returns[t])
        growth = float(grown.sum())
        if growth <= 0.0:
            # The portfolio lost everything (possible with leverage or short positions):
            # the path ends here and later periods stay undefined (NaN).
            portfolio_returns[t] = -1.0
            values[t] = 0.0
            break
        portfolio_returns[t] = growth - 1.0
        values[t] = values[t - 1] * growth
        drifted = grown / growth
        drift_breach = band is not None and float(np.abs(drifted - targets).max()) > band
        if scheduled[t] or drift_breach:
            turnover[t] = float(np.abs(targets - drifted).sum() / 2)
            current = targets.copy()
            rebalanced.append(index[t])
        else:
            current = drifted
        weights[t] = current

    return RebalancedPath(
        returns=pd.Series(portfolio_returns, index=index, name="portfolio").iloc[1:],
        values=pd.Series(values, index=index, name="value"),
        weights=pd.DataFrame(weights, index=index, columns=asset_returns.columns),
        turnover=pd.Series(turnover, index=index, name="turnover"),
        rebalanced=pd.DatetimeIndex(rebalanced),
    )


def risk_contributions(weights: np.ndarray, covariance: np.ndarray) -> pd.DataFrame:
    """Euler decomposition of portfolio volatility into per-asset contributions.

    Returns:
        A frame with ``weight``, ``marginal`` (∂sigma/∂w), ``contribution`` (w · marginal,
        summing to the portfolio volatility) and ``share`` (contribution / sigma, summing to 1).
        Values are per period; scale by √periods to annualise.
    """
    w = np.asarray(weights, dtype="float64")
    cov = np.asarray(covariance, dtype="float64")
    variance = float(w @ cov @ w)
    volatility = float(np.sqrt(variance)) if variance > 0 else 0.0
    marginal = cov @ w / volatility if volatility > 0 else np.zeros_like(w)
    contribution = w * marginal
    share = contribution / volatility if volatility > 0 else np.full_like(w, np.nan)
    return pd.DataFrame(
        {"weight": w, "marginal": marginal, "contribution": contribution, "share": share}
    )
