"""A strategy's signals on a series' bars: CryptoWorld's causal compiler (ADR-0050).

Every condition is computed from its bar and the bars before (rolling indicators, crosses
between the bar before and this one, pattern windows that only look back), so the signals
never see the future. They are events for the backtest engine: ``1`` opens, ``-1`` closes,
``0`` holds. A bar where the exit holds closes even if the entry holds too (no whipsaw); the
regime filter holds back entries only.

**An unknown condition holds no signal.** CryptoWorld's ``ta`` made up values while an
indicator warmed up (zeros, partial windows) and could fire on them; here an indicator is
``NaN`` until its window is full, and a condition that reads a ``NaN`` is unknown: it neither
holds nor, negated, fails to hold. An ``OR`` with one condition known to hold still holds, as
it would whatever the other said. From :attr:`Sides.ready`, the first bar from which every
condition is known, the signals are CryptoWorld's (the parity tests check it).
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from investinglab.analytics.patterns import detect, occurred_within
from investinglab.analytics.search.grammar import (
    Block,
    Combine,
    Compare,
    Condition,
    Cross,
    Leg,
    Operator,
    PatternCondition,
    Slope,
    StrategyDirection,
    StrategySpec,
    Threshold,
)
from investinglab.analytics.technical import compute

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = ["Sides", "compile_sides"]

type Bars = Mapping[str, pd.Series]
type Sessions = Sequence[Hashable]
type Flags = NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class Sides:
    """The signals of both sides of a strategy, on the same bars.

    Attributes:
        long: Signals of the long side (all ``0`` for a strategy that only trades short).
        short: Signals of the short side; ``None`` for a strategy that only trades long, so
            the engine takes the path it always took.
        ready: Position of the first bar from which every condition is known whatever the
            prices do: its indicators have values and its patterns are past their warm-up
            (the number of bars if never). Before it, something was still warming up.
    """

    long: pd.Series
    short: pd.Series | None
    ready: int = field(default=0)


class _Evaluator:
    """Each condition's truth on the bars, every indicator and pattern computed once."""

    def __init__(self, bars: Bars, sessions: Sessions | None) -> None:
        self._bars = bars
        self._sessions = sessions
        self._values: dict[object, NDArray[np.float64]] = {}
        self._flags: dict[object, pd.Series] = {}
        self._size = len(next(iter(bars.values())))
        self.settled = np.ones(self._size, dtype=bool)
        """Bars where every condition evaluated so far is known by construction: its
        indicators have values, its patterns are past their warm-up."""

    def series(self, leg: Leg) -> NDArray[np.float64]:
        key = leg.key()
        if key not in self._values:
            values = compute(leg.indicator, self._bars, **leg.params)
            self._values[key] = values.to_numpy(dtype=np.float64)
        return self._values[key]

    def truth(self, condition: Condition) -> Flags:
        """Where ``condition`` holds and is known (negated, where it fails and is known)."""
        holds, known, settled = self._evaluate(condition)
        self.settled &= settled
        return (~holds if condition.negate else holds) & known

    def _evaluate(self, condition: Condition) -> tuple[Flags, Flags, Flags]:
        """Where it holds, where that is known, and where it is known whatever happens."""
        if isinstance(condition, PatternCondition):
            return self._pattern(condition)
        if isinstance(condition, Threshold):
            values = self.series(condition.leg)
            with np.errstate(invalid="ignore"):
                above = values > condition.threshold
                below = values < condition.threshold
            known = ~np.isnan(values)
            return (above if condition.op is Operator.GT else below), known, known
        if isinstance(condition, Slope):
            values = self.series(condition.leg)
            before = _shifted(values, condition.bars)
            with np.errstate(invalid="ignore"):
                rising, falling = values > before, values < before
            known = ~np.isnan(values) & ~np.isnan(before)
            return (rising if condition.op is Operator.RISING else falling), known, known
        gap = self.series(condition.a) - self.series(condition.b)
        if isinstance(condition, Compare):
            with np.errstate(invalid="ignore"):
                above, below = gap > 0, gap < 0
            known = ~np.isnan(gap)
            return (above if condition.op is Operator.ABOVE else below), known, known
        return _cross(gap, condition)

    def _pattern(self, condition: PatternCondition) -> tuple[Flags, Flags, Flags]:
        key = (condition.pattern, tuple(sorted(condition.params.items())))
        if key not in self._flags:
            self._flags[key] = detect(
                condition.pattern, self._bars, self._sessions, **condition.params
            )
        within = occurred_within(self._flags[key], condition.lookback).to_numpy(dtype=bool)
        # Having fired is a fact whenever it fires; not having fired is known once the whole
        # window is past the warm-up.
        past = np.arange(self._size) >= condition.warmup + condition.lookback - 2
        return within, within | past, past

    def block(self, block: Block) -> Flags:
        truths = np.vstack([self.truth(condition) for condition in block.conditions])
        if block.combine is Combine.K_OF_N:
            return np.asarray(truths.sum(axis=0) >= (block.k or 1))
        if block.combine is Combine.AND:
            return np.asarray(truths.all(axis=0))
        return np.asarray(truths.any(axis=0))


def _shifted(values: NDArray[np.float64], bars: int) -> NDArray[np.float64]:
    before = np.full_like(values, np.nan)
    if bars < len(values):
        before[bars:] = values[:-bars]
    return before


def _cross(gap: NDArray[np.float64], condition: Cross) -> tuple[Flags, Flags, Flags]:
    before = _shifted(gap, 1)
    with np.errstate(invalid="ignore"):
        if condition.op is Operator.CROSS_ABOVE:
            crossed = (before <= 0) & (gap > 0)
        else:
            crossed = (before >= 0) & (gap < 0)
    known = ~np.isnan(gap) & ~np.isnan(before)
    return crossed, known, known


def _side(
    evaluator: _Evaluator, entry: Block, exit_: Block, trending: Flags | None, index: pd.Index
) -> NDArray[np.float64]:
    opens = evaluator.block(entry)
    closes = evaluator.block(exit_)
    if trending is not None:
        opens &= trending
    signals = np.zeros(len(index))
    signals[closes] = -1.0
    signals[opens & ~closes] = 1.0
    return signals


def compile_sides(spec: StrategySpec, bars: Bars, sessions: Sessions | None = None) -> Sides:
    """The signals of ``spec`` on ``bars``.

    Args:
        spec: The strategy.
        bars: Price columns by name (``open``, ``high``, ``low``, ``close``, ``volume``), on
            one index.
        sessions: The session of each bar, for the session patterns (an opening range).

    Raises:
        KeyError: A price column an indicator or a pattern of the strategy needs is missing.
        ValueError: A session pattern without the sessions.
    """
    index = bars["close"].index
    evaluator = _Evaluator(bars, sessions)
    trending = None
    if spec.regime is not None:
        adx = evaluator.series(spec.regime.leg)
        with np.errstate(invalid="ignore"):
            trending = adx >= spec.regime.adx_min
        evaluator.settled &= ~np.isnan(adx)
    direction = spec.direction
    if direction is StrategyDirection.SHORT:
        long = np.zeros(len(index))
        short = _side(evaluator, spec.entry, spec.exit, trending, index)
    else:
        long = _side(evaluator, spec.entry, spec.exit, trending, index)
        short = None
        if direction is StrategyDirection.BOTH:
            assert spec.short_entry is not None  # noqa: S101 - validated by StrategySpec
            assert spec.short_exit is not None  # noqa: S101 - validated by StrategySpec
            short = _side(evaluator, spec.short_entry, spec.short_exit, trending, index)
    unknown = np.flatnonzero(~evaluator.settled)
    return Sides(
        long=pd.Series(long, index=index, name="long"),
        short=None if short is None else pd.Series(short, index=index, name="short"),
        ready=int(unknown[-1]) + 1 if unknown.size else 0,
    )
