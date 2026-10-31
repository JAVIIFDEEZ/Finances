"""Functional core: pure numerical analytics over NumPy arrays and pandas objects.

This is the innermost layer. It knows nothing about the domain model, performs no I/O and
draws nothing: functions take arrays or series and return numbers, arrays or small value
objects. Domain objects (``PriceSeries``, ``Portfolio``) delegate their calculations here.
"""

from investinglab.analytics.covariance import (
    correlation_from_covariance,
    covariance_matrix,
    is_positive_semidefinite,
    nearest_positive_semidefinite,
)
from investinglab.analytics.descriptive import (
    ReturnMoments,
    annualize_mean,
    annualize_volatility,
    cagr,
    describe_returns,
)
from investinglab.analytics.drawdown import drawdown, max_drawdown
from investinglab.analytics.portfolio import RebalancedPath, rebalanced_path, risk_contributions
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
    "RebalancedPath",
    "ReturnMoments",
    "VaRMethod",
    "annualize_mean",
    "annualize_volatility",
    "beta",
    "cagr",
    "calmar_ratio",
    "conditional_value_at_risk",
    "correlation_from_covariance",
    "covariance_matrix",
    "cumulative_returns",
    "describe_returns",
    "downside_deviation",
    "drawdown",
    "effective_number_of_assets",
    "excess_returns",
    "herfindahl_index",
    "is_positive_semidefinite",
    "log_returns",
    "max_drawdown",
    "nearest_positive_semidefinite",
    "per_period_rate",
    "rebalanced_path",
    "risk_contributions",
    "sharpe_ratio",
    "simple_returns",
    "sortino_ratio",
    "total_return",
    "value_at_risk",
]
