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

__all__ = [
    "ReturnMoments",
    "annualize_mean",
    "annualize_volatility",
    "cagr",
    "cumulative_returns",
    "describe_returns",
    "drawdown",
    "log_returns",
    "max_drawdown",
    "simple_returns",
    "total_return",
]
