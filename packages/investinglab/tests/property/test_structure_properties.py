"""Property-based tests: what holds for the price structure of any SYNTHETIC bars.

* **Pivots are what they claim.** Each strictly dominates the ``k`` bars on each side, and
  the last ``k`` bars are never pivots (they are not confirmed yet).
* **No look-ahead.** A pivot confirmed before a cut is found with the bars up to the cut.
* **Units.** Rescaling the prices rescales the levels and keeps their touches, sides and
  distances; the Fibonacci levels lie within the swing, in order.
"""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics.structure import fibonacci_swing, pivots, support_resistance


@st.composite
def bars(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Highs, lows and closes of a seeded random walk (closes within each range)."""
    n = draw(st.integers(min_value=20, max_value=200))
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    rng = np.random.default_rng(seed)
    centre = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    high = centre * (1 + rng.uniform(0, 0.02, n))
    low = centre * (1 - rng.uniform(0, 0.02, n))
    close = low + rng.uniform(0, 1, n) * (high - low)
    return high, low, close


@settings(max_examples=60, deadline=None)
@given(bars(), st.integers(min_value=1, max_value=6))
def test_pivots_dominate_their_neighbours(sample: tuple[np.ndarray, ...], k: int) -> None:
    high, low, _ = sample
    tops, bottoms = pivots(high, low, k)

    for i in tops:
        assert k <= i < len(high) - k
        assert all(high[i] > high[j] for j in range(i - k, i + k + 1) if j != i)
    for i in bottoms:
        assert k <= i < len(low) - k
        assert all(low[i] < low[j] for j in range(i - k, i + k + 1) if j != i)


@settings(max_examples=60, deadline=None)
@given(bars(), st.integers(min_value=1, max_value=5), st.data())
def test_a_confirmed_pivot_needs_no_later_bar(
    sample: tuple[np.ndarray, ...], k: int, data: st.DataObject
) -> None:
    high, low, _ = sample
    cut = data.draw(st.integers(min_value=1, max_value=len(high)))
    tops, bottoms = pivots(high, low, k)
    early_tops, early_bottoms = pivots(high[:cut], low[:cut], k)

    assert set(early_tops) == {int(i) for i in tops if i + k < cut}
    assert set(early_bottoms) == {int(i) for i in bottoms if i + k < cut}


@settings(max_examples=60, deadline=None)
@given(bars(), st.sampled_from([0.25, 4.0, 1024.0]))
def test_levels_scale_with_the_prices(sample: tuple[np.ndarray, ...], factor: float) -> None:
    high, low, close = sample
    levels = support_resistance(high, low, close)
    scaled = support_resistance(high * factor, low * factor, close * factor)

    assert [(lv.touches, lv.kind, lv.positions) for lv in levels] == [
        (lv.touches, lv.kind, lv.positions) for lv in scaled
    ]
    for mine, theirs in zip(levels, scaled, strict=True):
        assert (
            theirs.price == np.float64(mine.price * factor)
            or abs(theirs.price - mine.price * factor) <= 1e-9 * theirs.price
        )
        assert abs(theirs.distance_pct - mine.distance_pct) <= 1e-9


@settings(max_examples=60, deadline=None)
@given(bars(), st.integers(min_value=1, max_value=250))
def test_fibonacci_levels_lie_within_the_swing_in_order(
    sample: tuple[np.ndarray, ...], lookback: int
) -> None:
    high, low, _ = sample
    swing = fibonacci_swing(high, low, lookback)

    assert swing is not None
    prices = [price for _, price in swing.levels]
    assert all(swing.low <= price <= swing.high for price in prices)
    assert prices == sorted(prices, reverse=swing.rising)
    window = slice(max(0, len(high) - lookback), None)
    assert swing.high == high[window].max()
    assert swing.low == low[window].min()
