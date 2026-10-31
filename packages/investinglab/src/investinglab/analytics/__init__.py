"""Functional core: pure numerical analytics over NumPy arrays and pandas objects.

This is the innermost layer. It knows nothing about the domain model, performs no I/O and
draws nothing: functions take arrays or series and return numbers, arrays or small value
objects. Domain objects (``PriceSeries``, ``Portfolio``) delegate their calculations here.
"""

from investinglab.analytics.descriptive import (
    ReturnMoments,
    annualize_mean,
    annualize_volatility,
    cagr,
    describe_returns,
)
from investinglab.analytics.drawdown import drawdown, max_drawdown
from investinglab.analytics.returns import (
    cumulative_returns,
    log_returns,
    simple_returns,
    total_return,
)
from investinglab.analytics.risk import (
    VaRMethod,
    beta,
    calmar_ratio,
    conditional_value_at_risk,
    downside_deviation,
    effective_number_of_assets,
    excess_returns,
    herfindahl_index,
    per_period_rate,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
)

__all__ = [
    "ReturnMoments",
    "VaRMethod",
    "annualize_mean",
    "annualize_volatility",
    "beta",
    "cagr",
    "calmar_ratio",
    "conditional_value_at_risk",
    "cumulative_returns",
    "describe_returns",
    "downside_deviation",
    "drawdown",
    "effective_number_of_assets",
    "excess_returns",
    "herfindahl_index",
    "log_returns",
    "max_drawdown",
    "per_period_rate",
    "sharpe_ratio",
    "simple_returns",
    "sortino_ratio",
    "total_return",
    "value_at_risk",
]
