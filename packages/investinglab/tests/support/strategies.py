"""Hypothesis strategies producing synthetic, valid domain inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from hypothesis import assume
from hypothesis import strategies as st

from investinglab.analytics.backtest import RiskModel
from investinglab.analytics.patterns import PATTERNS, Family
from investinglab.analytics.search import (
    MIN_NEGATED_LOOKBACK,
    Block,
    Combine,
    Compare,
    Condition,
    Cross,
    Leg,
    PatternCondition,
    Regime,
    Slope,
    StrategyDirection,
    StrategySpec,
    Threshold,
)
from investinglab.analytics.technical import CATALOGUE
from support.factories import make_series

if TYPE_CHECKING:
    from collections.abc import Mapping

    from investinglab.analytics.technical import Parameter
    from investinglab.domain import PriceSeries

positive_prices = st.lists(
    st.floats(min_value=1e-2, max_value=1e5, allow_nan=False, allow_infinity=False),
    min_size=3,
    max_size=120,
)
"""Lists of strictly positive, finite prices long enough to build a series."""

scale_factors = st.floats(min_value=1e-3, max_value=1e3, allow_nan=False, allow_infinity=False)


@st.composite
def price_series(draw: st.DrawFn) -> PriceSeries:
    """A synthetic daily price series with arbitrary positive prices."""
    return make_series(np.asarray(draw(positive_prices)))


# ── Strategies of the grammar (ADR-0050) ───────────────────────────


def _parameters(draw: st.DrawFn, declared: Mapping[str, Parameter]) -> dict[str, float]:
    return {
        name: draw(st.integers(int(p.low), int(p.high)))
        if p.integer
        else draw(st.floats(p.low, p.high).map(lambda v: round(v, 2)))
        for name, p in declared.items()
    }


@st.composite
def legs(draw: st.DrawFn, *, levels: bool | None = None) -> Leg:
    """An indicator of the catalogue with parameters in its search range."""
    names = sorted(
        name
        for name, entry in CATALOGUE.items()
        if levels is None or (entry.threshold is None) == levels
    )
    name = draw(st.sampled_from(names))
    return Leg(name, _parameters(draw, CATALOGUE[name].parameters))


@st.composite
def conditions(draw: st.DrawFn) -> Condition:
    """Any of the five kinds of condition (no session patterns: the bars are daily)."""
    kind = draw(st.sampled_from(("threshold", "cross", "compare", "slope", "pattern")))
    negate = draw(st.booleans())
    if kind == "threshold":
        leg = draw(legs(levels=False))
        low, high = leg.entry.threshold or (0.0, 1.0)
        value = draw(st.floats(low, high).map(lambda v: round(v, 2)))
        return Threshold(leg, draw(st.sampled_from(Threshold.OPERATORS)), value, negate=negate)
    if kind in {"cross", "compare"}:
        a, b = draw(legs(levels=True)), draw(legs(levels=True))
        assume(a != b)
        if kind == "cross":
            return Cross(a, b, draw(st.sampled_from(Cross.OPERATORS)))
        return Compare(a, b, draw(st.sampled_from(Compare.OPERATORS)), negate=negate)
    if kind == "slope":
        op = draw(st.sampled_from(Slope.OPERATORS))
        return Slope(draw(legs()), op, draw(st.integers(2, 10)), negate=negate)
    names = sorted(n for n, p in PATTERNS.items() if p.family is not Family.SESSION)
    name = draw(st.sampled_from(names))
    lookback = draw(st.integers(1, 8))
    return PatternCondition(
        name,
        _parameters(draw, PATTERNS[name].parameters),
        lookback,
        negate=negate and lookback >= MIN_NEGATED_LOOKBACK,
    )


@st.composite
def blocks(draw: st.DrawFn) -> Block:
    """One to three conditions, with ``AND``, ``OR`` or two of three."""
    found = tuple(draw(st.lists(conditions(), min_size=1, max_size=3)))
    if len(found) == 3 and draw(st.booleans()):
        return Block(found, Combine.K_OF_N, k=2)
    return Block(found, draw(st.sampled_from((Combine.AND, Combine.OR))))


@st.composite
def strategy_specs(draw: st.DrawFn) -> StrategySpec:
    """A random strategy of the grammar: any direction, with or without a regime filter."""
    direction = draw(st.sampled_from(StrategyDirection))
    both = direction is StrategyDirection.BOTH
    regime = draw(st.none() | st.floats(15.0, 35.0).map(lambda v: Regime(round(v, 1))))
    risk = draw(
        st.none()
        | st.builds(RiskModel, stop_loss_pct=st.floats(0.02, 0.15), max_bars=st.integers(5, 60))
    )
    return StrategySpec(
        entry=draw(blocks()),
        exit=draw(blocks()),
        direction=direction,
        short_entry=draw(blocks()) if both else None,
        short_exit=draw(blocks()) if both else None,
        risk=risk,
        regime=regime,
    )
