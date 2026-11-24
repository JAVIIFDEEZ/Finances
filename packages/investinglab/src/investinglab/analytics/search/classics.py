"""The classic strategies, written in the grammar: CryptoWorld's ``seed_specs`` (ADR-0050).

They show that the grammar says what the classics say, give a backtest something known to
start from, and seed the genetic search (G4) with strategies that are not random. The
parity tests check that each one is CryptoWorld's, with its definition hash.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from investinglab.analytics.search.grammar import (
    Block,
    Compare,
    Cross,
    Leg,
    Operator,
    StrategySpec,
    Threshold,
)

__all__ = ["CLASSICS"]

_PRICE: Final = Leg("PRICE")
_RSI: Final = Leg("RSI", {"window": 14})
_MACD: Final = {"fast": 12, "slow": 26, "signal": 9}


def _one(condition: Threshold | Cross | Compare) -> Block:
    return Block((condition,))


def _crossing(a: Leg, b: Leg) -> StrategySpec:
    """Enter when ``a`` crosses above ``b``, leave when it crosses below."""
    return StrategySpec(
        entry=_one(Cross(a, b, Operator.CROSS_ABOVE)),
        exit=_one(Cross(a, b, Operator.CROSS_BELOW)),
    )


CLASSICS: Final = MappingProxyType(
    {
        "rsi_reversal": StrategySpec(
            entry=_one(Threshold(_RSI, Operator.LT, 30.0)),
            exit=_one(Threshold(_RSI, Operator.GT, 70.0)),
        ),
        "macd_crossover": _crossing(Leg("MACD_LINE", _MACD), Leg("MACD_SIGNAL", _MACD)),
        "sma_crossover": _crossing(Leg("SMA", {"window": 20}), Leg("SMA", {"window": 50})),
        "ema_trend": _crossing(_PRICE, Leg("EMA", {"window": 26})),
        "bollinger_bounce": StrategySpec(
            entry=_one(
                Cross(_PRICE, Leg("BB_LOWER", {"window": 20, "dev": 2.0}), Operator.CROSS_BELOW)
            ),
            exit=_one(
                Cross(_PRICE, Leg("BB_UPPER", {"window": 20, "dev": 2.0}), Operator.CROSS_ABOVE)
            ),
        ),
        "donchian_breakout": StrategySpec(  # the turtles' breakout, in a trend
            entry=Block(
                (
                    Cross(_PRICE, Leg("DONCH_UPPER", {"window": 20}), Operator.CROSS_ABOVE),
                    Compare(_PRICE, Leg("SMA", {"window": 100}), Operator.ABOVE),
                )
            ),
            exit=_one(Cross(_PRICE, Leg("DONCH_LOWER", {"window": 10}), Operator.CROSS_BELOW)),
        ),
        "trend_pullback": StrategySpec(  # a cheap RSI with the price over its SMA(150)
            entry=Block(
                (
                    Threshold(_RSI, Operator.LT, 40.0),
                    Compare(_PRICE, Leg("SMA", {"window": 150}), Operator.ABOVE),
                )
            ),
            exit=_one(Threshold(_RSI, Operator.GT, 65.0)),
        ),
    }
)
"""The classic strategies by name, in CryptoWorld's order."""
