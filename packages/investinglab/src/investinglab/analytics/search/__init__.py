"""Strategies as data and their signals: CryptoWorld's strategy grammar (ADR-0050).

:mod:`~investinglab.analytics.search.grammar` says what a strategy is
(:class:`StrategySpec`), :mod:`~investinglab.analytics.search.compiler` turns one into the
signals of the backtest engine, and :data:`CLASSICS` holds the classic strategies written in
it. The genetic search over the grammar joins them in the Laboratory (G4).
"""

from investinglab.analytics.search.classics import CLASSICS
from investinglab.analytics.search.compiler import Sides, compile_sides
from investinglab.analytics.search.grammar import (
    MAX_CONDITIONS,
    MIN_NEGATED_LOOKBACK,
    REGIME_ADX_WINDOW,
    Block,
    Combine,
    Compare,
    Condition,
    ConditionKind,
    Cross,
    Leg,
    Operator,
    PatternCondition,
    Regime,
    Slope,
    StrategyDirection,
    StrategySpec,
    Threshold,
)

__all__ = [
    "CLASSICS",
    "MAX_CONDITIONS",
    "MIN_NEGATED_LOOKBACK",
    "REGIME_ADX_WINDOW",
    "Block",
    "Combine",
    "Compare",
    "Condition",
    "ConditionKind",
    "Cross",
    "Leg",
    "Operator",
    "PatternCondition",
    "Regime",
    "Sides",
    "Slope",
    "StrategyDirection",
    "StrategySpec",
    "Threshold",
    "compile_sides",
]
