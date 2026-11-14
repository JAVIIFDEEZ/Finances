"""The price pattern catalogue of CryptoWorld, on any price series (ADR-0035).

The twenty patterns of its strategy grammar (``price_patterns.PATTERNS``) keep their names
and parameters, with their search ranges, so that a strategy keeps its meaning when it
moves platform; the parity tests check they flag the same bars. The five candles that only
its screen had (``detect_candle_patterns``: the inverted hammer, the stars, the soldiers and
the crows) join them with names in the same style. Where the screen and the grammar defined
the same candle differently (the hammer, the doji...), the grammar's definition is the one
kept: it is the one strategies were found with.

Each entry says which price columns it reads: a pattern is never computed from substitutes
(a close standing in for a missing open), it is left out.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

import pandas as pd

from investinglab.analytics.patterns import candles, liquidity, sessions, zones
from investinglab.analytics.technical.catalogue import Column, Parameter

__all__ = ["MIRRORS", "PATTERNS", "Direction", "Family", "Pattern", "detect", "occurred_within"]


class Family(StrEnum):
    """What a pattern describes."""

    CANDLE = "candle"
    """The shape of one to three bars."""
    LIQUIDITY = "liquidity"
    """Gaps, sweeps, order blocks and the phases of a move."""
    SESSION = "session"
    """The opening of each session: needs intraday bars and session labels."""
    ZONE = "zone"
    """Where the price stands in the recent swing: a state, not an event."""


class Direction(StrEnum):
    """The way a pattern's definition points: mirror patterns have opposite directions.

    It is part of the definition (an engulfing that rises), not a forecast.
    """

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


type Bars = Mapping[str, pd.Series]
type Sessions = Sequence[Hashable]
type Detect = Callable[[Bars, Mapping[str, float], Sessions | None], pd.Series]


@dataclass(frozen=True, slots=True)
class Pattern:
    """One pattern of the catalogue.

    Attributes:
        name: CryptoWorld's name.
        family: What it describes.
        direction: The way its definition points.
        columns: Price columns it reads.
        parameters: Parameters by name.
        compute: Flags for the bars, the parameters and, for session patterns, the sessions.
        warmup: Bars it needs before it can fire, over its whole search range.
        grammar: Whether CryptoWorld's strategy grammar has it (else only its screen did).
    """

    name: str
    family: Family
    direction: Direction
    columns: frozenset[Column]
    parameters: Mapping[str, Parameter]
    compute: Detect = field(repr=False)
    warmup: int
    grammar: bool = True

    @property
    def defaults(self) -> dict[str, float]:
        """The default value of every parameter."""
        return {name: parameter.default for name, parameter in self.parameters.items()}

    @property
    def state(self) -> bool:
        """Whether it is a state that lasts (a zone) rather than an event on one bar."""
        return self.family is Family.ZONE


OHLC: Final = frozenset({Column.OPEN, Column.HIGH, Column.LOW, Column.CLOSE})
HL: Final = frozenset({Column.HIGH, Column.LOW})
HLC: Final = frozenset({Column.HIGH, Column.LOW, Column.CLOSE})

_WICK: Final = {"wick_ratio": Parameter(1.5, 3.5, 2.0, integer=False)}


def _ohlc(function: Callable[..., pd.Series]) -> Detect:
    return lambda b, p, _s: function(b["open"], b["high"], b["low"], b["close"], **p)


def _hl(function: Callable[..., pd.Series]) -> Detect:
    return lambda b, p, _s: function(b["high"], b["low"], **p)


def _hlc(function: Callable[..., pd.Series]) -> Detect:
    return lambda b, p, _s: function(b["high"], b["low"], b["close"], **p)


def _session(function: Callable[..., pd.Series]) -> Detect:
    def detect(bars: Bars, params: Mapping[str, float], labels: Sessions | None) -> pd.Series:
        if labels is None:
            raise ValueError("needs the session of every bar")
        return function(bars["high"], bars["low"], bars["close"], labels, **params)

    return detect


def _entries() -> list[Pattern]:
    bull, bear, neutral = Direction.BULLISH, Direction.BEARISH, Direction.NEUTRAL
    candle, flow, session, zone = Family.CANDLE, Family.LIQUIDITY, Family.SESSION, Family.ZONE
    sweep = {"window": Parameter(10, 60, 20)}
    block = {"impulse": Parameter(2, 6, 3)}
    amd = {"window": Parameter(6, 24, 6)}
    opening = {"bars": Parameter(2, 12, 6)}
    swing = {"window": Parameter(30, 120, 60)}
    return [
        Pattern("BULL_ENGULF", candle, bull, OHLC, {}, _ohlc(candles.bullish_engulfing), 2),
        Pattern("BEAR_ENGULF", candle, bear, OHLC, {}, _ohlc(candles.bearish_engulfing), 2),
        Pattern("HAMMER", candle, bull, OHLC, _WICK, _ohlc(candles.hammer), 1),
        Pattern("SHOOTING_STAR", candle, bear, OHLC, _WICK, _ohlc(candles.shooting_star), 1),
        Pattern(
            "DOJI",
            candle,
            neutral,
            OHLC,
            {"max_body_pct": Parameter(0.05, 0.2, 0.1, integer=False)},
            _ohlc(candles.doji),
            1,
        ),
        Pattern("INSIDE_BAR", candle, neutral, HL, {}, _hl(candles.inside_bar), 2),
        Pattern("OUTSIDE_BAR", candle, neutral, HL, {}, _hl(candles.outside_bar), 2),
        Pattern(
            "INV_HAMMER", candle, bull, OHLC, {}, _ohlc(candles.inverted_hammer), 1, grammar=False
        ),
        Pattern(
            "MORNING_STAR", candle, bull, OHLC, {}, _ohlc(candles.morning_star), 3, grammar=False
        ),
        Pattern(
            "EVENING_STAR", candle, bear, OHLC, {}, _ohlc(candles.evening_star), 3, grammar=False
        ),
        Pattern(
            "THREE_SOLDIERS",
            candle,
            bull,
            OHLC,
            {},
            _ohlc(candles.three_white_soldiers),
            3,
            grammar=False,
        ),
        Pattern(
            "THREE_CROWS",
            candle,
            bear,
            OHLC,
            {},
            _ohlc(candles.three_black_crows),
            3,
            grammar=False,
        ),
        Pattern("FVG_BULL", flow, bull, HL, {}, _hl(liquidity.bullish_fair_value_gap), 3),
        Pattern("FVG_BEAR", flow, bear, HL, {}, _hl(liquidity.bearish_fair_value_gap), 3),
        Pattern("SWEEP_LOW", flow, bull, HLC, sweep, _hlc(liquidity.low_sweep), 61),
        Pattern("SWEEP_HIGH", flow, bear, HLC, sweep, _hlc(liquidity.high_sweep), 61),
        Pattern("OB_BULL", flow, bull, OHLC, block, _ohlc(liquidity.bullish_order_block), 10),
        Pattern("OB_BEAR", flow, bear, OHLC, block, _ohlc(liquidity.bearish_order_block), 10),
        Pattern("CRT", flow, neutral, HLC, {}, _hlc(liquidity.candle_range_theory), 2),
        Pattern("PO3_BULL", flow, bull, HLC, amd, _hlc(liquidity.bullish_power_of_three), 25),
        Pattern("PO3_BEAR", flow, bear, HLC, amd, _hlc(liquidity.bearish_power_of_three), 25),
        Pattern(
            "ORB_UP", session, bull, HLC, opening, _session(sessions.opening_range_breakout), 13
        ),
        Pattern(
            "ORB_DOWN",
            session,
            bear,
            HLC,
            opening,
            _session(sessions.opening_range_breakdown),
            13,
        ),
        Pattern("FIB_DISCOUNT", zone, bull, HLC, swing, _hlc(zones.fibonacci_discount), 121),
        Pattern("FIB_PREMIUM", zone, bear, HLC, swing, _hlc(zones.fibonacci_premium), 121),
    ]


PATTERNS: Final[Mapping[str, Pattern]] = MappingProxyType(
    {pattern.name: pattern for pattern in _entries()}
)
"""Every pattern of the catalogue by name."""

MIRRORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        name: mirror
        for pair in (
            ("BULL_ENGULF", "BEAR_ENGULF"),
            ("HAMMER", "SHOOTING_STAR"),
            ("MORNING_STAR", "EVENING_STAR"),
            ("THREE_SOLDIERS", "THREE_CROWS"),
            ("FVG_BULL", "FVG_BEAR"),
            ("SWEEP_LOW", "SWEEP_HIGH"),
            ("OB_BULL", "OB_BEAR"),
            ("PO3_BULL", "PO3_BEAR"),
            ("ORB_UP", "ORB_DOWN"),
            ("FIB_DISCOUNT", "FIB_PREMIUM"),
        )
        for name, mirror in (pair, pair[::-1])
    }
)
"""The pattern each one becomes on the price turned upside down (DOJI, CRT... are their own)."""


def detect(name: str, bars: Bars, labels: Sessions | None = None, /, **params: float) -> pd.Series:
    """Flags of pattern ``name`` over ``bars`` (columns by name), defaults filled in.

    Args:
        name: A pattern of the catalogue.
        bars: Price columns by name.
        labels: The session of each bar; session patterns need it.
        **params: Parameters of the pattern.

    Raises:
        KeyError: An unknown pattern, or a price column it needs is missing.
        ValueError: An unknown or invalid parameter, or a session pattern without sessions.
    """
    pattern = PATTERNS.get(name)
    if pattern is None:
        raise KeyError(f"unknown pattern {name!r}; known: {sorted(PATTERNS)}")
    missing = sorted(column.value for column in pattern.columns if column.value not in bars)
    if missing:
        raise KeyError(f"{name} needs the {missing} columns")
    unknown = sorted(set(params) - set(pattern.parameters))
    if unknown:
        raise ValueError(f"{name} has no parameters {unknown}")
    values = {
        key: parameter.check(key, params.get(key, parameter.default))
        for key, parameter in pattern.parameters.items()
    }
    return pattern.compute(bars, values, labels).rename(name)


def occurred_within(flags: pd.Series, lookback: int) -> pd.Series:
    """Whether the pattern happened on this bar or on one of the ``lookback - 1`` before.

    Two patterns rarely complete on the same bar; with a window, a sequence such as "a sweep
    and then an engulfing" can be expressed. The window only looks back.

    Raises:
        ValueError: If ``lookback`` is below 1.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be at least 1, got {lookback}")
    if lookback == 1:
        return flags.astype(bool)
    return flags.astype(float).rolling(lookback, min_periods=1).max().astype(bool)
