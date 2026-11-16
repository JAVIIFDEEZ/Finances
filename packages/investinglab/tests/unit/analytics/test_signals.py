"""The signal panel, the trend state and the confluence across timeframes, by hand."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.technical.signals import (
    RULES,
    UNDEFINED,
    Bias,
    ConfluenceVerdict,
    PanelVerdict,
    RuleReading,
    SignalPanel,
    Style,
    TrendDirection,
    confluence,
    signal_panel,
    trend_state,
)


def _growing(bars: int, rate: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Closes compounding at ``rate`` per bar, with highs and lows 1 % around them."""
    close = pd.Series(100.0 * (1.0 + rate) ** np.arange(bars))
    return close, close * 1.01, close * 0.99


def _panel(*biases: tuple[Bias, Style]) -> SignalPanel:
    return SignalPanel(
        tuple(RuleReading(f"R{i}", style, bias, {}, {}) for i, (bias, style) in enumerate(biases))
    )


# ── The panel ────────────────────────────────────────────────────────


def test_a_steady_rise_has_every_trend_rule_bullish_and_the_rsi_fading_it() -> None:
    close, high, low = _growing(260, 0.01)

    panel = signal_panel(close, high, low)

    # An RSI pinned at 100 has no range of its own: its stochastic is undefined, not guessed.
    assert dict(panel.skipped) == {"STOCH_RSI": (UNDEFINED,)}
    assert [rule.name for rule in panel.rules] == [name for name in RULES if name != "STOCH_RSI"]
    trend = {rule.name: rule.bias for rule in panel.rules if rule.style is Style.TREND}
    assert set(trend.values()) == {Bias.BULLISH}
    assert panel.score_of(Style.TREND) == 1.0
    rsi = next(rule for rule in panel.rules if rule.name == "RSI")
    assert (rsi.bias, rsi.values["rsi"]) == (Bias.BEARISH, 100.0)  # the reversal reading
    assert panel.count(Bias.BEARISH, Style.REVERSAL) >= 1
    assert panel.count(Bias.BULLISH) + panel.count(Bias.BEARISH) + panel.count(Bias.NEUTRAL) == 10
    assert panel.verdict in {PanelVerdict.BULLISH, PanelVerdict.STRONG_BULLISH}


def test_a_steady_fall_mirrors_it() -> None:
    close, high, low = _growing(260, -0.01)

    panel = signal_panel(close, high, low)
    bias = {rule.name: rule.bias for rule in panel.rules}

    assert {bias[name] for name in ("SMA_20", "SMA_50", "EMA_12", "EMA_26", "ADX")} == {
        Bias.BEARISH
    }
    assert bias["RSI"] is Bias.BULLISH  # oversold
    # At a constant rate of fall the absolute falls shrink, so the MACD climbs towards zero
    # above its signal: a trend rule that already points up while the price still falls.
    assert bias["MACD"] is Bias.BULLISH


def test_rules_needing_highs_and_lows_are_skipped_without_them() -> None:
    close, _, _ = _growing(260, 0.01)

    panel = signal_panel(close)

    assert {k: v for k, v in panel.skipped.items() if v == ("high", "low")} == dict.fromkeys(
        ("ADX", "CCI", "WILLR"), ("high", "low")
    )
    assert panel.total + len(panel.skipped) == len(RULES)


def test_rules_without_a_value_yet_are_skipped_and_named() -> None:
    close, high, low = _growing(30, 0.01)

    panel = signal_panel(close, high, low)

    assert panel.skipped["SMA_50"] == (UNDEFINED,)
    assert panel.skipped["MACD"] == (UNDEFINED,)  # 26 bars and 9 of signal
    assert "SMA_20" not in panel.skipped
    assert panel.total + len(panel.skipped) == len(RULES)
    empty = signal_panel(pd.Series(dtype=float))
    assert (empty.total, empty.score, empty.verdict) == (0, None, None)


def test_a_price_that_never_moves_points_nowhere() -> None:
    flat = pd.Series([50.0] * 120)

    panel = signal_panel(flat, flat, flat)

    assert {rule.bias for rule in panel.rules} == {Bias.NEUTRAL}  # exact ties are neutral
    assert set(panel.skipped) == {"RSI", "STOCH_RSI", "CCI", "WILLR"}  # 0/0: undefined
    assert (panel.score, panel.verdict) == (0.0, PanelVerdict.NEUTRAL)


@pytest.mark.parametrize(
    ("bullish", "bearish", "neutral", "verdict"),
    [
        (9, 1, 1, PanelVerdict.STRONG_BULLISH),
        (6, 4, 1, PanelVerdict.BULLISH),
        (5, 5, 1, PanelVerdict.NEUTRAL),
        (3, 6, 2, PanelVerdict.BEARISH),
        (1, 8, 2, PanelVerdict.STRONG_BEARISH),
        (8, 2, 1, PanelVerdict.STRONG_BULLISH),  # 6/11 = 0.545 > 0.5
        (7, 2, 2, PanelVerdict.BULLISH),  # 5/11 = 0.4545: not strong
    ],
)
def test_the_verdict_is_the_net_of_the_rules(
    bullish: int, bearish: int, neutral: int, verdict: PanelVerdict
) -> None:
    panel = _panel(
        *[(Bias.BULLISH, Style.TREND)] * bullish,
        *[(Bias.BEARISH, Style.REVERSAL)] * bearish,
        *[(Bias.NEUTRAL, Style.TREND)] * neutral,
    )

    assert panel.score == pytest.approx((bullish - bearish) / 11)
    assert panel.verdict is verdict
    assert panel.count(Bias.BULLISH, Style.TREND) == bullish
    assert panel.count(Bias.BULLISH, Style.REVERSAL) == 0
    assert panel.score_of(Style.REVERSAL) == (-1.0 if bearish else None)
    assert (panel.bullish, panel.bearish, panel.neutral) == (bullish, bearish, neutral)
    assert panel.reversal_score == panel.score_of(Style.REVERSAL)
    assert panel.trend_score == pytest.approx(bullish / (bullish + neutral))


# ── The trend ────────────────────────────────────────────────────────


def test_the_trend_reads_the_long_average_and_the_slope_of_the_medium_one() -> None:
    up = trend_state(_growing(260, 0.005)[0])
    down = trend_state(_growing(260, -0.005)[0])
    flat = trend_state(pd.Series([50.0] * 260))

    assert up is not None
    assert down is not None
    assert flat is not None
    assert (up.direction, up.sma_window, up.ema_window) == (TrendDirection.UP, 200, 50)
    assert up.price_vs_sma_pct > 0
    assert up.ema_slope_pct == pytest.approx((1.005**10 - 1) * 100, rel=1e-3)  # the rate itself
    assert down.direction is TrendDirection.DOWN
    assert (flat.direction, flat.ema_slope_pct, flat.price_vs_sma_pct) == (
        TrendDirection.SIDEWAYS,
        0.0,
        0.0,
    )


def test_a_rise_too_slow_to_count_is_sideways() -> None:
    slow = trend_state(_growing(260, 0.0001)[0])  # 0.1 % in ten bars

    assert slow is not None
    assert slow.direction is TrendDirection.SIDEWAYS
    assert slow.price_vs_sma_pct > 0


def test_short_series_use_shorter_averages_and_say_so() -> None:
    short = trend_state(_growing(45, 0.01)[0])

    assert short is not None
    assert (short.sma_window, short.ema_window) == (22, 15)
    assert trend_state(_growing(19, 0.01)[0]) is None  # under 20 bars there is no average
    assert trend_state(pd.Series(dtype=float)) is None


# ── The confluence ───────────────────────────────────────────────────


def test_frames_pointing_the_same_way_are_aligned() -> None:
    found = confluence([(1, 0.4), (2, 0.6), (3, 0.5)])

    assert found.verdict is ConfluenceVerdict.ALIGNED_BULLISH
    assert found.alignment == pytest.approx((0.4 + 1.2 + 1.5) / 6)
    assert (found.agreement, found.frames) == (1.0, 3)
    assert confluence([(1, -0.4), (2, -0.6)]).verdict is ConfluenceVerdict.ALIGNED_BEARISH


def test_a_fine_frame_against_the_coarse_ones_makes_them_mixed() -> None:
    found = confluence([(1, -0.8), (2, 0.5), (3, 0.6)])

    assert found.alignment == pytest.approx((-0.8 + 1.0 + 1.8) / 6)
    assert found.agreement == pytest.approx(2 / 3)  # under three quarters
    assert found.verdict is ConfluenceVerdict.MIXED


def test_scores_near_zero_have_no_direction() -> None:
    assert confluence([(1, 0.1), (2, -0.05), (3, 0.2)]).verdict is ConfluenceVerdict.NEUTRAL
    balanced = confluence([(1, 0.5), (1, -0.5)])
    assert (balanced.verdict, balanced.alignment, balanced.agreement) == (
        ConfluenceVerdict.NEUTRAL,
        0.0,
        0.0,
    )


def test_one_frame_is_not_a_consensus_and_unread_frames_do_not_count() -> None:
    alone = confluence([(1, 0.9), (2, None), (3, None)])

    assert (alone.verdict, alone.alignment, alone.agreement, alone.frames) == (
        ConfluenceVerdict.INSUFFICIENT,
        0.9,
        None,
        1,
    )
    assert confluence([]).verdict is ConfluenceVerdict.INSUFFICIENT
    assert confluence([(1, None)]).alignment is None
    assert confluence([(1, 0.5), (9, None), (2, 0.5)]) == confluence([(1, 0.5), (2, 0.5)])


def test_weights_and_scores_out_of_range_are_refused() -> None:
    with pytest.raises(ValueError, match="weights"):
        confluence([(0, 0.5), (1, 0.5)])
    with pytest.raises(ValueError, match="scores"):
        confluence([(1, 1.5), (1, 0.5)])
