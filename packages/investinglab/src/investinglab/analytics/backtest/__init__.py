"""The backtest engine: one instrument's signals, bar by bar, with costs (ADR-0049).

Pure numerical code over arrays, like the rest of :mod:`investinglab.analytics`: the domain
(:func:`investinglab.domain.run_backtest`) gives it a series' bars and turns its result into
dated trades, an equity curve and their metrics.
"""

from investinglab.analytics.backtest.engine import Simulation, Trade, simulate
from investinglab.analytics.backtest.models import (
    BPS,
    FULL_SIZING,
    NO_COSTS,
    NO_RISK,
    CostModel,
    ExitReason,
    RiskModel,
    Side,
    SizingMode,
    SizingModel,
)

__all__ = [
    "BPS",
    "FULL_SIZING",
    "NO_COSTS",
    "NO_RISK",
    "CostModel",
    "ExitReason",
    "RiskModel",
    "Side",
    "Simulation",
    "SizingMode",
    "SizingModel",
    "Trade",
    "simulate",
]
