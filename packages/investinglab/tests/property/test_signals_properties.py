"""Property-based tests: what holds for the signal panel and the confluence on any input.

* **Units.** Rescaling the prices (a share split, another currency) changes no rule, no
  score and no trend.
* **Accounting.** Every rule is read or skipped; the score is the net of the rules read.
* **Confluence.** The alignment is a weighted mean (within the scores, unchanged when every
  weight is rescaled); turning every score upside down turns the verdict; a frame that could
  not be read changes nothing.

Bars are SYNTHETIC: seeded random walks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics.technical.signals import (
    RULES,
    Bias,
    ConfluenceVerdict,
    confluence,
    signal_panel,
    trend_state,
)

MIRROR = {
    ConfluenceVerdict.ALIGNED_BULLISH: ConfluenceVerdict.ALIGNED_BEARISH,
    ConfluenceVerdict.ALIGNED_BEARISH: ConfluenceVerdict.ALIGNED_BULLISH,
}


@st.composite
def bars(draw: st.DrawFn) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Closes, highs and lows of a seeded random walk (closes within each range)."""
    n = draw(st.integers(min_value=5, max_value=320))
    seed = draw(st.integers(min_value=0, max_value=2**32 - 1))
    rng = np.random.default_rng(seed)
    centre = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    high = centre * (1 + rng.uniform(0, 0.02, n))
    low = centre * (1 - rng.uniform(0, 0.02, n))
    close = low + rng.uniform(0, 1, n) * (high - low)
    return pd.Series(close), pd.Series(high), pd.Series(low)


frames = st.lists(
    st.tuples(
        st.floats(min_value=0.1, max_value=10),
        st.one_of(st.none(), st.floats(min_value=-1, max_value=1)),
    ),
    max_size=7,
)


@settings(max_examples=60, deadline=None)
@given(bars(), st.sampled_from([0.25, 4.0, 1024.0]))
def test_rescaling_the_prices_changes_no_rule_and_no_trend(
    sample: tuple[pd.Series, pd.Series, pd.Series], factor: float
) -> None:
    close, high, low = sample
    panel = signal_panel(close, high, low)
    scaled = signal_panel(close * factor, high * factor, low * factor)

    assert [(r.name, r.bias) for r in panel.rules] == [(r.name, r.bias) for r in scaled.rules]
    assert dict(panel.skipped) == dict(scaled.skipped)
    trend, rescaled = trend_state(close), trend_state(close * factor)
    assert (trend is None) == (rescaled is None)
    if trend is not None and rescaled is not None:
        assert trend.direction is rescaled.direction
        assert abs(trend.ema_slope_pct - rescaled.ema_slope_pct) <= 1e-9
        assert abs(trend.price_vs_sma_pct - rescaled.price_vs_sma_pct) <= 1e-9


@settings(max_examples=60, deadline=None)
@given(bars())
def test_every_rule_is_read_or_skipped_and_the_score_is_their_net(
    sample: tuple[pd.Series, pd.Series, pd.Series],
) -> None:
    close, high, low = sample
    panel = signal_panel(close, high, low)

    assert {rule.name for rule in panel.rules} | set(panel.skipped) == set(RULES)
    assert {rule.name for rule in panel.rules}.isdisjoint(panel.skipped)
    counts = [panel.count(bias) for bias in Bias]
    assert sum(counts) == panel.total
    if panel.total:
        net = panel.count(Bias.BULLISH) - panel.count(Bias.BEARISH)
        assert panel.score == net / panel.total
        assert -1.0 <= panel.score <= 1.0
    else:
        assert panel.score is None


@settings(max_examples=200, deadline=None)
@given(frames)
def test_the_alignment_is_a_weighted_mean_of_the_frames_read(
    sample: list[tuple[float, float | None]],
) -> None:
    found = confluence(sample)
    scores = [score for _, score in sample if score is not None]

    assert found.frames == len(scores)
    if not scores:
        assert found.alignment is None
        return
    assert found.alignment is not None
    assert min(scores) - 1e-12 <= found.alignment <= max(scores) + 1e-12
    if found.agreement is not None:
        assert 0.0 <= found.agreement <= 1.0
    assert (found.verdict is ConfluenceVerdict.INSUFFICIENT) == (len(scores) < 2)


@settings(max_examples=200, deadline=None)
@given(frames, st.sampled_from([0.5, 2.0, 8.0]))
def test_rescaling_weights_and_dropping_unread_frames_changes_nothing(
    sample: list[tuple[float, float | None]], factor: float
) -> None:
    found = confluence(sample)
    rescaled = confluence([(weight * factor, score) for weight, score in sample])
    only_read = confluence([(weight, score) for weight, score in sample if score is not None])

    assert (rescaled.verdict, rescaled.agreement, rescaled.frames) == (
        found.verdict,
        found.agreement,
        found.frames,
    )
    if found.alignment is not None and rescaled.alignment is not None:
        assert abs(rescaled.alignment - found.alignment) <= 1e-12
    assert only_read == found


@settings(max_examples=200, deadline=None)
@given(frames)
def test_turning_every_score_upside_down_turns_the_verdict(
    sample: list[tuple[float, float | None]],
) -> None:
    found = confluence(sample)
    turned = confluence([(w, None if score is None else -score) for w, score in sample])

    assert turned.verdict is MIRROR.get(found.verdict, found.verdict)
    assert turned.agreement == found.agreement
    if found.alignment is not None and turned.alignment is not None:
        assert turned.alignment == -found.alignment
