"""Japanese candle patterns as causal flags, one per bar (ADR-0035).

Each function marks the bars that complete a pattern, looking only at that bar and the ones
before it. Definitions follow CryptoWorld: the engulfings, hammer, shooting star, doji and
inside and outside bars of its strategy grammar (``price_patterns``), whose thresholds are
proportional to each bar's own range; and the inverted hammer, the morning and evening stars
and the three soldiers and crows of its screen (``detect_candle_patterns``), with that
screen's fixed ratios. A pattern says what the bars did, not what they will do: whether it
anticipates anything is for the validation of a strategy to measure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "bearish_engulfing",
    "bullish_engulfing",
    "doji",
    "evening_star",
    "hammer",
    "inside_bar",
    "inverted_hammer",
    "morning_star",
    "outside_bar",
    "shooting_star",
    "three_black_crows",
    "three_white_soldiers",
]

_EPS = float(np.finfo(float).eps)
_SOLID_BODY = 0.1
"""Share of its range a bar's body must reach to be engulfed: a body-less bar is not."""
_MIN_WICK_BODY = 0.05
"""Floor of the body, as a share of the range, when measuring a wick against it."""


def _float(series: pd.Series) -> np.ndarray:
    return series.to_numpy(dtype=float)


def _span(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """The bar's range, floored above zero so that flat bars divide without error."""
    span = high - low
    return np.where(span > 0, span, _EPS)


def _before(values: np.ndarray, bars: int = 1) -> np.ndarray:
    """The value ``bars`` bars before (``NaN`` where there is none: comparisons are false)."""
    out = np.full(values.shape, np.nan)
    if bars < values.size:
        out[bars:] = values[: values.size - bars]
    return out


def _flags(values: np.ndarray, like: pd.Series) -> pd.Series:
    return pd.Series(values, index=like.index, dtype=bool)


def _engulfing(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, *, bullish: bool
) -> pd.Series:
    o, h, lo, c = _float(open_), _float(high), _float(low), _float(close)
    o1, c1 = _before(o), _before(c)
    with np.errstate(invalid="ignore"):
        solid = np.abs(c1 - o1) >= _SOLID_BODY * _span(_before(h), _before(lo))
        if bullish:
            shape = (c > o) & (c1 < o1) & (c >= o1) & (o <= c1)
        else:
            shape = (c < o) & (c1 > o1) & (c <= o1) & (o >= c1)
    return _flags(shape & solid, close)


def bullish_engulfing(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """A rising bar whose body covers the falling body before it.

    The bar before needs a real body (at least 10 % of its range): a bar without one is
    engulfed by anything, and the pattern would fire in every sideways market.
    """
    return _engulfing(open_, high, low, close, bullish=True)


def bearish_engulfing(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """Mirror of :func:`bullish_engulfing`: a falling bar covering the rising body before."""
    return _engulfing(open_, high, low, close, bullish=False)


def _wicks(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Body, range (floored), lower wick and upper wick of every bar."""
    o, h, lo, c = _float(open_), _float(high), _float(low), _float(close)
    return np.abs(c - o), _span(h, lo), np.minimum(o, c) - lo, h - np.maximum(o, c)


def _check_ratio(name: str, value: float) -> None:
    if not value > 0:
        raise ValueError(f"{name} must be positive, got {value}")


def hammer(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    wick_ratio: float = 2.0,
) -> pd.Series:
    """Hammer (bullish pin bar): a lower wick ``wick_ratio`` times the body, at most.

    The upper wick is no longer than the body. It describes a rejection: the price fell and
    was brought back within the bar. The body is floored at 5 % of the range, so that a
    near doji does not count as a hammer with any wick.

    Raises:
        ValueError: If ``wick_ratio`` is not positive.
    """
    _check_ratio("wick_ratio", wick_ratio)
    body, span, lower, upper = _wicks(open_, high, low, close)
    shape = (lower >= wick_ratio * np.maximum(body, span * _MIN_WICK_BODY)) & (upper <= body)
    return _flags(shape & (body > 0), close)


def shooting_star(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    wick_ratio: float = 2.0,
) -> pd.Series:
    """Mirror of :func:`hammer`: a long upper wick, the body below.

    Raises:
        ValueError: If ``wick_ratio`` is not positive.
    """
    _check_ratio("wick_ratio", wick_ratio)
    body, span, lower, upper = _wicks(open_, high, low, close)
    shape = (upper >= wick_ratio * np.maximum(body, span * _MIN_WICK_BODY)) & (lower <= body)
    return _flags(shape & (body > 0), close)


def doji(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    max_body_pct: float = 0.1,
) -> pd.Series:
    """A body of at most ``max_body_pct`` of the range: the bar closed where it opened.

    A bar without any range (high equal to low) is a doji too.

    Raises:
        ValueError: If ``max_body_pct`` is not positive.
    """
    _check_ratio("max_body_pct", max_body_pct)
    body, span, _, _ = _wicks(open_, high, low, close)
    return _flags(body <= max_body_pct * span, close)


def inside_bar(high: pd.Series, low: pd.Series) -> pd.Series:
    """A bar within the range of the bar before: the market stops expanding."""
    h, lo = _float(high), _float(low)
    with np.errstate(invalid="ignore"):
        return _flags((h <= _before(h)) & (lo >= _before(lo)), high)


def outside_bar(high: pd.Series, low: pd.Series) -> pd.Series:
    """A bar whose range covers the bar before's on both sides: expansion."""
    h, lo = _float(high), _float(low)
    with np.errstate(invalid="ignore"):
        return _flags((h >= _before(h)) & (lo <= _before(lo)), high)


def _screen(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Open, close, body share of the range and whether the bar has a range, as the screen.

    CryptoWorld's screen skips bars without range, and divides the earlier bars' bodies
    by their range or, without one, by 1.
    """
    o, h, lo, c = _float(open_), _float(high), _float(low), _float(close)
    span = h - lo
    body = np.abs(c - o)
    share = body / np.where(span != 0, span, 1.0)
    return o, c, body, share, span != 0


def inverted_hammer(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """A rising bar with an upper wick over twice its body and almost no lower wick."""
    o, c, body, share, ranged = _screen(open_, high, low, close)
    upper = _float(high) - np.maximum(o, c)
    lower = np.minimum(o, c) - _float(low)
    shape = (c > o) & (upper > 2 * body) & (lower < 0.5 * body) & (share > 0.05)  # noqa: PLR2004
    return _flags(ranged & shape, close)


def _star(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, *, morning: bool
) -> pd.Series:
    o, c, _, share, ranged = _screen(open_, high, low, close)
    falling, rising = c < o, c > o
    first = _before(falling.astype(float), 2) if morning else _before(rising.astype(float), 2)
    last = rising if morning else falling
    with np.errstate(invalid="ignore"):
        shape = (
            (first == 1)
            & (_before(share, 2) > 0.5)  # noqa: PLR2004 - a large first body
            & (_before(share, 1) < 0.3)  # noqa: PLR2004 - a small middle body
            & last
            & (share > 0.5)  # noqa: PLR2004 - a large last body
        )
    return _flags(ranged & shape, close)


def morning_star(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Three bars: a large falling body, a small one and a large rising body."""
    return _star(open_, high, low, close, morning=True)


def evening_star(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Mirror of :func:`morning_star`: large rising, small, large falling."""
    return _star(open_, high, low, close, morning=False)


def _three(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, *, rising: bool
) -> pd.Series:
    o, c, _, _, ranged = _screen(open_, high, low, close)
    o1, o2, c1, c2 = _before(o), _before(o, 2), _before(c), _before(c, 2)
    with np.errstate(invalid="ignore"):
        if rising:
            shape = (c > o) & (c1 > o1) & (c2 > o2) & (c > c1) & (c1 > c2) & (o > o1) & (o1 > o2)
        else:
            shape = (c < o) & (c1 < o1) & (c2 < o2) & (c < c1) & (c1 < c2) & (o < o1) & (o1 < o2)
    return _flags(ranged & shape, close)


def three_white_soldiers(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """Three rising bars in a row, each opening and closing above the one before."""
    return _three(open_, high, low, close, rising=True)


def three_black_crows(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.Series:
    """Three falling bars in a row, each opening and closing below the one before."""
    return _three(open_, high, low, close, rising=False)
