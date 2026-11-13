"""Property-based tests: what holds for every indicator on any SYNTHETIC price path.

* **No look-ahead.** Cutting the series never changes the values before the cut.
* **Units.** Oscillators do not change when prices are rescaled (a share split, another
  currency); averages, bands and levels scale with them.
* **Bounds.** Each oscillator stays within its range.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics.technical import CATALOGUE, compute

SCALE_FREE = frozenset(
    {"RSI", "STOCHRSI", "CCI", "WILLR", "ADX", "MFI", "CMF", "VOLRATIO", "STOCH", "ROC"}
    | {"ATR_PCT", "AROON", "TRIX"}
)
BOUNDS = {
    "RSI": (0, 100),
    "STOCHRSI": (0, 100),
    "WILLR": (-100, 0),
    "ADX": (0, 100),
    "MFI": (0, 100),
    "CMF": (-1, 1),
    "STOCH": (0, 100),
    "AROON": (-100, 100),
    "ATR_PCT": (0, None),
    "VOLRATIO": (0, None),
}


@st.composite
def bars(draw: st.DrawFn) -> dict[str, pd.Series]:
    """A seeded random walk with positive highs, lows and volumes around it."""
    n = draw(st.integers(min_value=40, max_value=160))
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    wick = close * rng.uniform(0, 0.02, (2, n))
    return {
        "high": pd.Series(close + wick[0]),
        "low": pd.Series(close - wick[1]),
        "close": pd.Series(close),
        "volume": pd.Series(rng.uniform(1, 1_000, n)),
    }


@settings(max_examples=40, deadline=None)
@given(data=bars(), cut=st.floats(min_value=0.3, max_value=0.9))
def test_no_indicator_looks_ahead(data: dict[str, pd.Series], cut: float) -> None:
    keep = int(len(data["close"]) * cut)
    head = {column: values.iloc[:keep] for column, values in data.items()}
    for name in CATALOGUE:
        whole = compute(name, data).iloc[:keep].to_numpy()
        part = compute(name, head).to_numpy()
        np.testing.assert_allclose(part, whole, rtol=1e-9, atol=1e-9, err_msg=name)


@settings(max_examples=30, deadline=None)
@given(data=bars(), factor=st.floats(min_value=0.01, max_value=100.0))
def test_units_change_nothing_but_price_levels(data: dict[str, pd.Series], factor: float) -> None:
    scaled = {c: (v * factor if c != "volume" else v) for c, v in data.items()}
    for name in CATALOGUE:
        base = compute(name, data).to_numpy()
        moved = compute(name, scaled).to_numpy()
        expected = base if name in SCALE_FREE else base * factor
        np.testing.assert_allclose(moved, expected, rtol=1e-6, atol=1e-6, err_msg=name)


@settings(max_examples=40, deadline=None)
@given(data=bars())
def test_oscillators_stay_in_their_range(data: dict[str, pd.Series]) -> None:
    for name, (low, high) in BOUNDS.items():
        values = compute(name, data).dropna()
        assert (values >= low - 1e-9).all(), name
        if high is not None:
            assert (values <= high + 1e-9).all(), name
