"""Price patterns on hand-built bars: each definition, its edge cases and the catalogue."""

from __future__ import annotations

import pandas as pd
import pytest

from investinglab.analytics.patterns import (
    PATTERNS,
    Direction,
    Family,
    candles,
    detect,
    liquidity,
    occurred_within,
    sessions,
    zones,
)


def _bars(*rows: tuple[float, float, float, float]) -> dict[str, pd.Series]:
    """Bars from (open, high, low, close) rows."""
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"], dtype=float)
    return {column: frame[column] for column in frame.columns}


def _hits(flags: pd.Series) -> list[int]:
    return [int(i) for i in flags.index[flags.to_numpy()]]


def _ohlc(bars: dict[str, pd.Series]) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    return bars["open"], bars["high"], bars["low"], bars["close"]


# ── Candles ──────────────────────────────────────────────────────────


def test_an_engulfing_covers_the_body_before_and_needs_one() -> None:
    bars = _bars((10, 10.5, 8.5, 9), (8.8, 10.6, 8.7, 10.2), (10, 10, 10, 10), (10, 11, 9, 10.5))

    assert _hits(candles.bullish_engulfing(*_ohlc(bars))) == [1]  # not 3: bar 2 has no body
    bearish = _bars((9, 10.5, 8.5, 10), (10.2, 10.6, 8.7, 8.8))
    assert _hits(candles.bearish_engulfing(*_ohlc(bearish))) == [1]


def test_hammer_and_shooting_star_measure_the_wick_against_the_body() -> None:
    bars = _bars((10, 10.2, 7, 10.1), (10, 13, 9.9, 9.9), (10, 10, 10, 10))

    assert _hits(candles.hammer(*_ohlc(bars))) == [0]
    assert _hits(candles.shooting_star(*_ohlc(bars))) == [1]
    assert _hits(candles.hammer(*_ohlc(bars), wick_ratio=40)) == []  # 2.9 is not 40 bodies
    with pytest.raises(ValueError, match="wick_ratio"):
        candles.hammer(*_ohlc(bars), wick_ratio=0)


def test_a_doji_closes_where_it_opened_and_a_flat_bar_is_one() -> None:
    bars = _bars((10, 11, 9, 10.1), (10, 11, 9, 10.5), (10, 10, 10, 10))

    assert _hits(candles.doji(*_ohlc(bars))) == [0, 2]
    assert _hits(candles.doji(*_ohlc(bars), max_body_pct=0.3)) == [0, 1, 2]


def test_inside_and_outside_bars_compare_ranges() -> None:
    bars = _bars((10, 12, 8, 11), (10, 11, 9, 10), (10, 13, 7, 12))

    assert _hits(candles.inside_bar(bars["high"], bars["low"])) == [1]
    assert _hits(candles.outside_bar(bars["high"], bars["low"])) == [2]


def test_the_screen_candles() -> None:
    inverted = _bars((10, 13, 9.95, 10.5))
    assert _hits(candles.inverted_hammer(*_ohlc(inverted))) == [0]

    morning = _bars((12, 12.1, 9.9, 10), (10, 10.5, 9.5, 10.1), (10.1, 12.3, 10, 12.2))
    assert _hits(candles.morning_star(*_ohlc(morning))) == [2]
    assert _hits(candles.evening_star(*_ohlc(morning))) == []

    evening = _bars((10, 12.1, 9.9, 12), (12, 12.5, 11.5, 11.9), (11.9, 12, 9.7, 9.8))
    assert _hits(candles.evening_star(*_ohlc(evening))) == [2]

    rising = _bars((10, 11.1, 9.9, 11), (10.5, 12.1, 10.4, 12), (11, 13.1, 10.9, 13))
    assert _hits(candles.three_white_soldiers(*_ohlc(rising))) == [2]
    falling = _bars((13, 13.1, 11.9, 12), (12.5, 12.6, 10.9, 11), (12, 12.1, 9.9, 10))
    assert _hits(candles.three_black_crows(*_ohlc(falling))) == [2]


# ── Structure and liquidity ──────────────────────────────────────────


def test_a_fair_value_gap_is_flagged_on_the_bar_that_leaves_it() -> None:
    bars = _bars((10, 10.5, 9.5, 10.4), (10.4, 12, 10.3, 11.9), (11.9, 13, 11, 12.8))

    assert _hits(liquidity.bullish_fair_value_gap(bars["high"], bars["low"])) == [2]
    assert _hits(liquidity.bearish_fair_value_gap(bars["high"], bars["low"])) == []


def test_a_sweep_closes_back_inside_and_a_breakdown_does_not() -> None:
    rows = [(10, 11, 9, 10)] * 3
    swept = _bars(*rows, (10, 10.5, 8.5, 9.5))
    broken = _bars(*rows, (10, 10.5, 8.5, 8.8))

    assert _hits(liquidity.low_sweep(swept["high"], swept["low"], swept["close"], 3)) == [3]
    assert _hits(liquidity.low_sweep(broken["high"], broken["low"], broken["close"], 3)) == []
    high = _bars(*rows, (10, 11.5, 9.5, 10.5))
    assert _hits(liquidity.high_sweep(high["high"], high["low"], high["close"], 3)) == [3]


def test_an_order_block_fires_when_the_price_comes_back_to_it() -> None:
    bars = _bars(
        (10, 10.5, 9.6, 9.7),  # 0: a falling bar...
        (10.6, 11, 10.55, 10.9),  # 1: ...whose high the next bar breaks: a block, not touched
        (10.9, 11.3, 10.8, 11.2),  # 2: away from it
        (11.2, 11.25, 10.3, 10.4),  # 3: back into it (low 10.3 <= 10.5): mitigated
        (10.4, 10.45, 10.0, 10.1),  # 4: inside it again, but the block is spent
    )

    assert _hits(liquidity.bullish_order_block(*_ohlc(bars), impulse=1)) == [3]
    # bar 3 also breaks the low of the rising bar 2, a bearish block it touches at once
    assert _hits(liquidity.bearish_order_block(*_ohlc(bars), impulse=1)) == [3]


def test_a_short_series_has_no_block_yet_and_the_same_flags_as_a_longer_one() -> None:
    rows = [(10, 10.5, 9, 9.2), (9.2, 9.5, 9.0, 9.1), (9.1, 10.8, 9.0, 10.0)]
    short = _bars(*rows)
    longer = _bars(*rows, (10, 10.1, 9.9, 10))

    flags = liquidity.bullish_order_block(*_ohlc(short), impulse=2)
    assert flags.tolist() == liquidity.bullish_order_block(*_ohlc(longer), impulse=2)[:3].tolist()


def test_crt_takes_the_bar_before_and_closes_back_inside() -> None:
    bars = _bars((10, 11, 9, 10), (10, 11.5, 9.5, 10.5), (10.5, 12, 10, 11.8))

    assert _hits(liquidity.candle_range_theory(bars["high"], bars["low"], bars["close"])) == [1]


def test_power_of_three_needs_compression_a_fake_move_and_the_opposite_close() -> None:
    bars = _bars(
        (10, 10.2, 9.9, 10.1),  # accumulation (first third of a 6-bar window)
        (10.1, 10.2, 10, 10.1),
        (10.1, 10.1, 9.0, 9.2),  # manipulation: below the accumulation's low
        (9.2, 9.5, 8.8, 9.4),
        (9.4, 9.8, 9.3, 9.7),
        (9.7, 10.0, 9.6, 9.9),
        (9.9, 10.6, 9.8, 10.5),  # distribution: a close above the accumulation's high
    )
    h, lo, c = bars["high"], bars["low"], bars["close"]

    assert _hits(liquidity.bullish_power_of_three(h, lo, c, 6)) == [6]
    assert _hits(liquidity.bearish_power_of_three(h, lo, c, 6)) == []


# ── Sessions and zones ───────────────────────────────────────────────


def test_the_opening_range_breaks_once_per_session_on_the_given_sessions() -> None:
    bars = _bars(
        (10, 11, 9, 10),
        (10, 10.5, 9.5, 10),
        (10, 11.5, 10, 11.2),  # breaks the 2-bar opening range
        (11.2, 12, 11, 11.8),  # again: not a new breakout
        (12, 12.5, 11.5, 12),  # a new session
        (12, 12.2, 11.8, 12),
        (12, 12.1, 11, 11.2),  # breaks it down
    )
    labels = ["mon"] * 4 + ["tue"] * 3
    h, lo, c = bars["high"], bars["low"], bars["close"]

    assert _hits(sessions.opening_range_breakout(h, lo, c, labels, 2)) == [2]
    assert _hits(sessions.opening_range_breakdown(h, lo, c, labels, 2)) == [6]
    assert _hits(sessions.opening_range_breakout(h, lo, c, ["one"] * 7, 2)) == [2]
    with pytest.raises(ValueError, match="session labels"):
        sessions.opening_range_breakout(h, lo, c, labels[:3], 2)
    with pytest.raises(ValueError, match="bars"):
        sessions.opening_range_breakout(h, lo, c, labels, 0)


def test_fibonacci_zones_are_bands_of_the_swing_before() -> None:
    bars = _bars((0, 110, 100, 105), (0, 120, 108, 110), (0, 115, 105, 106), (0, 118, 110, 115))
    h, lo, c = bars["high"], bars["low"], bars["close"]

    # swing of the two bars before bar 2: 100-120; 106 is 0.7 of the way down from 120
    assert _hits(zones.fibonacci_discount(h, lo, c, 2)) == [2]
    # swing before bar 3: 105-120; 115 is 0.667 up from 105
    assert _hits(zones.fibonacci_premium(h, lo, c, 2)) == [3]
    with pytest.raises(ValueError, match="lower <= upper"):
        zones.fibonacci_discount(h, lo, c, 2, lower=0.8, upper=0.7)


# ── Catalogue ────────────────────────────────────────────────────────


def test_the_catalogue_describes_every_pattern() -> None:
    assert len(PATTERNS) == 25
    assert sum(pattern.grammar for pattern in PATTERNS.values()) == 20
    assert PATTERNS["FIB_DISCOUNT"].state
    assert not PATTERNS["HAMMER"].state
    assert PATTERNS["ORB_UP"].family is Family.SESSION
    assert PATTERNS["DOJI"].direction is Direction.NEUTRAL
    assert PATTERNS["SWEEP_LOW"].defaults == {"window": 20}


def test_detect_fills_in_defaults_and_names_the_flags() -> None:
    bars = _bars((10, 10.2, 7, 10.1), (10, 10.2, 9.8, 10))

    flags = detect("HAMMER", bars)
    assert flags.name == "HAMMER"
    assert _hits(flags) == [0]
    assert _hits(detect("HAMMER", bars, None, wick_ratio=1.5)) == [0]


def test_detect_refuses_what_it_cannot_compute() -> None:
    bars = _bars((10, 11, 9, 10))
    closes = {"close": bars["close"]}

    with pytest.raises(KeyError, match="unknown pattern"):
        detect("NOPE", bars)
    with pytest.raises(KeyError, match="open"):
        detect("DOJI", closes)  # never computed from substitutes
    with pytest.raises(ValueError, match="no parameters"):
        detect("DOJI", bars, None, window=3)
    with pytest.raises(ValueError, match="whole number"):
        detect("SWEEP_LOW", bars, None, window=2.5)
    with pytest.raises(ValueError, match="session"):
        detect("ORB_UP", bars)


def test_occurred_within_looks_back_only() -> None:
    flags = pd.Series([False, True, False, False, False, True])

    assert occurred_within(flags, 1).tolist() == flags.tolist()
    assert occurred_within(flags, 3).tolist() == [False, True, True, True, False, True]
    with pytest.raises(ValueError, match="lookback"):
        occurred_within(flags, 0)
