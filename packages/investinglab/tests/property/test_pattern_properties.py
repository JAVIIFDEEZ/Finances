"""Property-based tests: what holds for every price pattern on any SYNTHETIC bars.

* **No look-ahead.** Cutting the series never changes the flags before the cut.
* **Units.** Rescaling the prices (a share split, another currency) changes no flag.
* **Mirror.** Turning the prices upside down turns each pattern into its mirror (a bullish
  engulfing into a bearish one) and leaves the symmetric ones (doji, inside bar, CRT) as
  they were: the definitions treat both directions alike.

Prices are whole numbers, so that rescaling by a power of two and mirroring are exact.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics.patterns import MIRRORS, PATTERNS, detect

SYMMETRIC = frozenset({"DOJI", "INSIDE_BAR", "OUTSIDE_BAR", "CRT"})
CEILING = 1_000


@st.composite
def bars(draw: st.DrawFn) -> tuple[dict[str, pd.Series], list[int]]:
    """Bars with whole-number prices (open and close within each bar's range), in sessions."""
    n = draw(st.integers(min_value=30, max_value=150))
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    session = draw(st.integers(min_value=4, max_value=24))
    rng = np.random.default_rng(seed)
    centre = np.clip(500 + np.cumsum(rng.integers(-30, 31, n)), 50, CEILING - 50)
    low = centre - rng.integers(0, 40, n)
    high = centre + rng.integers(0, 40, n)
    open_ = low + (rng.random(n) * (high - low + 1)).astype(int).clip(0, high - low)
    close = low + (rng.random(n) * (high - low + 1)).astype(int).clip(0, high - low)
    index = pd.RangeIndex(n)
    frame = {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }
    sessions = [i // session for i in range(n)]
    return {k: pd.Series(v, index=index, dtype=float) for k, v in frame.items()}, sessions


def _flags(name: str, data: dict[str, pd.Series], sessions: list[int]) -> np.ndarray:
    return detect(name, data, sessions).to_numpy()


@settings(max_examples=40, deadline=None)
@given(bars(), st.data())
def test_no_pattern_looks_ahead(
    sample: tuple[dict[str, pd.Series], list[int]], data: st.DataObject
) -> None:
    full, sessions = sample
    cut = data.draw(st.integers(min_value=1, max_value=len(sessions) - 1))
    head = {k: v.iloc[:cut] for k, v in full.items()}
    for name in PATTERNS:
        before = _flags(name, head, sessions[:cut])
        assert np.array_equal(before, _flags(name, full, sessions)[:cut]), name


@settings(max_examples=40, deadline=None)
@given(bars(), st.sampled_from([0.25, 4.0, 1024.0]))
def test_rescaling_the_prices_changes_no_flag(
    sample: tuple[dict[str, pd.Series], list[int]], factor: float
) -> None:
    data, sessions = sample
    scaled = {k: v * factor for k, v in data.items()}
    for name in PATTERNS:
        assert np.array_equal(_flags(name, data, sessions), _flags(name, scaled, sessions)), name


@settings(max_examples=40, deadline=None)
@given(bars())
def test_upside_down_prices_flag_the_mirror_pattern(
    sample: tuple[dict[str, pd.Series], list[int]],
) -> None:
    data, sessions = sample
    mirrored = {
        "open": 2 * CEILING - data["open"],
        "high": 2 * CEILING - data["low"],
        "low": 2 * CEILING - data["high"],
        "close": 2 * CEILING - data["close"],
    }
    for name, mirror in MIRRORS.items():
        assert np.array_equal(_flags(name, data, sessions), _flags(mirror, mirrored, sessions)), (
            name
        )
    for name in SYMMETRIC:
        assert np.array_equal(_flags(name, data, sessions), _flags(name, mirrored, sessions)), name


def test_every_pattern_is_its_own_mirror_or_has_one() -> None:
    """Only the screen's inverted hammer lacks a mirror: its mirror is not in the catalogue."""
    assert set(PATTERNS) - set(MIRRORS) - SYMMETRIC == {"INV_HAMMER"}
    assert all(PATTERNS[name].direction != PATTERNS[MIRRORS[name]].direction for name in MIRRORS)
