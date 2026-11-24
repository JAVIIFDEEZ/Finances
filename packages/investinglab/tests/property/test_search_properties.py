"""Properties of the strategy grammar on SYNTHETIC random paths and random strategies.

Whatever the strategy: its JSON form reads back as itself with the same hash; its signals
are events on exactly the bars, on the sides it trades; and they never see the future (the
signals on the first bars do not change when later bars arrive).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics.search import StrategyDirection, StrategySpec, compile_sides
from support.factories import gbm_prices
from support.strategies import strategy_specs

BARS = 140


def _bars(seed: int) -> dict[str, pd.Series]:
    """A SYNTHETIC random walk with coherent open, high, low, close and volume."""
    close = gbm_prices(BARS, sigma=0.5, seed=seed)
    rng = np.random.default_rng(seed)
    open_ = close * np.exp(rng.normal(0.0, 0.01, BARS))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.0, 0.02, BARS))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.0, 0.02, BARS))
    volume = rng.uniform(1e3, 5e3, BARS)
    index = pd.date_range("2024-01-01", periods=BARS, freq="D", tz="UTC")
    columns = {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    return {name: pd.Series(values, index=index) for name, values in columns.items()}


@settings(max_examples=60, deadline=None)
@given(spec=strategy_specs())
def test_the_json_form_reads_back_as_the_same_strategy(spec: StrategySpec) -> None:
    again = StrategySpec.from_dict(spec.to_dict())

    assert again == spec
    assert again.definition_hash == spec.definition_hash
    assert again.to_dict() == spec.to_dict()


@settings(max_examples=60, deadline=None)
@given(spec=strategy_specs(), seed=st.integers(0, 2**16), cut=st.integers(20, BARS - 1))
def test_signals_are_causal_events_on_the_sides_it_trades(
    spec: StrategySpec, seed: int, cut: int
) -> None:
    bars = _bars(seed)

    sides = compile_sides(spec, bars)
    early = compile_sides(spec, {name: values.iloc[:cut] for name, values in bars.items()})

    for signals in (sides.long, sides.short):
        if signals is not None:
            assert signals.index.equals(bars["close"].index)
            assert set(np.unique(signals)) <= {-1.0, 0.0, 1.0}
    assert (sides.short is None) == (spec.direction is StrategyDirection.LONG)
    if spec.direction is StrategyDirection.SHORT:
        assert not sides.long.any()
    assert 0 <= sides.ready <= BARS
    assert early.long.equals(sides.long.iloc[:cut])  # what came later changed nothing
    if sides.short is not None:
        assert early.short is not None
        assert early.short.equals(sides.short.iloc[:cut])
    assert min(early.ready, cut) == min(sides.ready, cut)
