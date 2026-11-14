"""Price structure on hand-built bars: pivots, levels, divergences and Fibonacci levels."""

from __future__ import annotations

import numpy as np
import pytest

from investinglab.analytics.structure import (
    FIBONACCI_RATIOS,
    cluster_levels,
    divergences,
    fibonacci_swing,
    pivots,
    support_resistance,
)


def _a(*values: float) -> np.ndarray:
    return np.array(values, dtype=float)


def test_a_pivot_dominates_strictly_and_needs_k_bars_after_it() -> None:
    high = _a(1, 2, 5, 2, 1, 3, 3, 1, 0, 9)
    low = _a(5, 4, 3, 4, 5, 2, 6, 7, 8, 9)

    tops, bottoms = pivots(high, low, 2)

    assert tops.tolist() == [2]  # the 3s at 5 and 6 tie: no pivot; 9 has no bars after it
    assert bottoms.tolist() == [2, 5]
    assert pivots(high[:3], low[:3], 2)[0].size == 0  # bar 2 is not confirmed yet
    with pytest.raises(ValueError, match="k must be"):
        pivots(high, low, 0)


def test_pivots_within_the_tolerance_make_one_level() -> None:
    levels = cluster_levels(_a(100.0, 100.4, 110.0, 99.8), np.array([3, 9, 5, 1]), 0.6)

    assert [(round(lv.price, 4), lv.touches) for lv in levels] == [(100.0667, 3), (110.0, 1)]
    # 100.5 would be 0.6 away from the mean so far (99.9), just over 0.6 % of it: a new level
    split = cluster_levels(_a(99.8, 100.0, 100.5), np.array([0, 1, 2]), 0.6)
    assert [lv.touches for lv in split] == [2, 1]
    assert levels[0].positions == (1, 3, 9)  # in time order
    assert cluster_levels(_a(), np.array([], dtype=int)) == []


def test_levels_are_supports_below_the_close_and_resistances_above() -> None:
    # a range between 90 and 110 touched twice each, the last close at 100
    high = _a(100, 105, 110, 105, 100, 104, 110.2, 104, 100, 101, 100, 99, 100)
    low = _a(95, 92, 95, 92, 90, 93, 95, 92, 90.3, 93, 95, 96, 97)
    close = _a(97, 100, 105, 100, 95, 100, 106, 100, 95, 98, 99, 98, 100)

    levels = support_resistance(high, low, close, 2)

    by_kind = {lv.kind: lv for lv in levels}
    assert by_kind["resistance"].price == pytest.approx(110.1)
    assert by_kind["resistance"].touches == 2
    assert by_kind["support"].price == pytest.approx(90.15)
    assert by_kind["support"].distance_pct == pytest.approx(-9.85)
    assert support_resistance(high, low, close, 2, max_levels=1) == levels[:1]
    assert support_resistance(high[:5], low[:5], close[:5], 2) == []  # too short to tell
    with pytest.raises(ValueError, match="max_levels"):
        support_resistance(high, low, close, 2, max_levels=0)


def test_a_higher_high_with_a_lower_oscillator_is_a_bearish_divergence() -> None:
    close = _a(10, 11, 12, 15, 12, 11, 10, 11, 12, 16, 12, 11, 10, 11)
    oscillator = _a(50, 55, 60, 75, 60, 55, 50, 55, 60, 70, 60, 55, 50, 55)

    (found,) = divergences(close, oscillator, 2, lookback=60)

    assert (found.kind, found.first, found.second, found.confirmed) == ("bearish", 3, 9, 11)
    assert (found.price_first, found.price_second) == (15.0, 16.0)
    assert (found.oscillator_first, found.oscillator_second) == (75.0, 70.0)
    assert divergences(close, oscillator, 2, lookback=60, min_gap=6) == []  # 5 points is noise
    assert divergences(close, oscillator, 2, lookback=6) == []  # the first pivot is too old


def test_a_lower_low_with_a_higher_oscillator_is_a_bullish_divergence() -> None:
    close = _a(16, 15, 14, 11, 14, 15, 16, 15, 14, 10, 14, 15, 16, 15)
    oscillator = _a(50, 45, 40, 25, 40, 45, 50, 45, 40, 30, 40, 45, 50, 45)

    (found,) = divergences(close, oscillator, 2)

    assert found.kind == "bullish"
    assert divergences(close, np.full(close.size, np.nan), 2) == []  # undefined: no comparison
    with pytest.raises(ValueError, match="oscillator values"):
        divergences(close, oscillator[:-1], 2)


def test_fibonacci_levels_retrace_from_the_last_extreme() -> None:
    rising = fibonacci_swing(_a(10, 12, 20, 18), _a(8, 9, 15, 16))
    falling = fibonacci_swing(_a(20, 18, 12, 11), _a(15, 12, 9, 8))

    assert rising is not None
    assert falling is not None
    assert (rising.high, rising.low, rising.high_at, rising.low_at, rising.rising) == (
        20.0,
        8.0,
        2,
        0,
        True,
    )
    assert dict(rising.levels)[0.5] == pytest.approx(14.0)
    assert dict(rising.levels)[0.236] == pytest.approx(20 - 12 * 0.236)  # down from the high
    assert dict(falling.levels)[0.236] == pytest.approx(8 + 12 * 0.236)  # up from the low
    assert [ratio for ratio, _ in rising.levels] == list(FIBONACCI_RATIOS)
    nearest = rising.nearest(14.2)
    assert nearest is not None
    assert nearest[0] == 0.5
    assert nearest[1] == pytest.approx(14.0)
    flat = fibonacci_swing(_a(5, 5), _a(5, 5))
    assert flat is not None
    assert flat.levels == ()
    assert flat.nearest(5.0) is None
    assert fibonacci_swing(_a(), _a()) is None
    last = fibonacci_swing(_a(1, 9, 2), _a(0.5, 1, 1.5), lookback=1)
    assert last is not None
    assert last.high == 2.0
