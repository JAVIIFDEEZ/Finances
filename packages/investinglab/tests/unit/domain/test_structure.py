"""Price structure of a price series, for any asset class (SYNTHETIC bars)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.structure import support_resistance
from investinglab.domain import DomainError, PriceSeries, price_structure
from investinglab.domain.instruments import EXCHANGES
from investinglab.domain.time import Frequency
from support.factories import SYNTHETIC_SOURCE, business_days, make_instrument, make_series

DAYS = business_days(250)


def _walk(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    centre = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    high = centre * (1 + rng.uniform(0, 0.01, n))
    low = centre * (1 - rng.uniform(0, 0.01, n))
    close = low + rng.uniform(0, 1, n) * (high - low)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=DAYS[:n])


BARS = PriceSeries(
    instrument=make_instrument("SYN.MC", exchange=EXCHANGES["XMAD"]),
    frequency=Frequency.DAY_1,
    source=SYNTHETIC_SOURCE,
    data=_walk(250, 7),
)


def test_levels_and_swing_come_from_the_highs_and_lows_with_their_dates() -> None:
    structure = price_structure(BARS)

    assert structure.basis == "range"
    assert structure.last_at == DAYS[-1]
    assert structure.last_close == pytest.approx(BARS.bars["close"].iloc[-1])
    found = support_resistance(BARS.bars["high"], BARS.bars["low"], BARS.bars["close"])
    assert [level.price for level in structure.levels] == [level.price for level in found]
    for level, raw in zip(structure.levels, found, strict=True):
        assert level.touched_at == tuple(DAYS[list(raw.positions)])
    support, resistance = structure.nearest_support, structure.nearest_resistance
    last = structure.last_close
    assert last is not None
    assert support is None or support.price < last
    assert resistance is None or resistance.price >= last
    swing = structure.fibonacci
    assert swing is not None
    assert swing.high == BARS.bars["high"].iloc[-180:].max()
    assert swing.high_at == BARS.bars["high"].iloc[-180:].idxmax()
    assert swing.nearest in {ratio for ratio, _ in swing.levels}
    assert structure.parameters["k"] == 3


def test_a_divergence_says_when_it_became_known() -> None:
    days = business_days(120)
    found = []
    for seed in range(40):  # a few synthetic walks have one
        series = make_series(
            100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.02, 120))),
            index=days,
        )
        found += [(series, d) for d in price_structure(series).divergences]
    assert found
    for series, divergence in found:
        index = list(series.bars.index)
        assert divergence.confirmed_at == index[index.index(divergence.second_at) + 3]
        assert divergence.first_at < divergence.second_at


def test_a_series_of_closes_uses_its_closes_and_says_so() -> None:
    closes = make_series(np.linspace(100, 120, 60) + np.sin(np.arange(60)), index=business_days(60))

    structure = price_structure(closes)

    assert structure.basis == "close"
    assert structure.fibonacci is not None
    assert structure.fibonacci.high == closes.bars["close"].max()


def test_parameters_out_of_range_are_refused() -> None:
    with pytest.raises(DomainError, match="k must be"):
        price_structure(BARS, k=0)
    with pytest.raises(DomainError, match="tolerance_pct"):
        price_structure(BARS, tolerance_pct=0)
    with pytest.raises(DomainError, match="lookback"):
        price_structure(BARS, fibonacci_lookback=0)
