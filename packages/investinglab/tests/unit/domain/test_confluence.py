"""The confluence of an instrument across timeframes (SYNTHETIC bars)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.technical.signals import ConfluenceVerdict, confluence, signal_panel
from investinglab.domain import (
    DomainError,
    FrameIssue,
    Frequency,
    PriceSeries,
    timeframe_confluence,
)
from investinglab.domain.instruments import EXCHANGES
from support.factories import SYNTHETIC_SOURCE, business_days, make_instrument, make_series

DAYS = business_days(1500, start="2019-01-01")


def _walk(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    centre = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    high = centre * (1 + rng.uniform(0, 0.01, n))
    low = centre * (1 - rng.uniform(0, 0.01, n))
    close = low + rng.uniform(0, 1, n) * (high - low)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=DAYS[:n])


DAILY = PriceSeries(
    instrument=make_instrument("SYN.MC", exchange=EXCHANGES["XMAD"]),
    frequency=Frequency.DAY_1,
    source=SYNTHETIC_SOURCE,
    data=_walk(1500, 3),
)
WEEKLY = DAILY.resample(Frequency.WEEK_1)
MONTHLY = DAILY.resample(Frequency.MONTH_1)


def test_coarser_frames_weigh_more_and_each_is_read_on_its_own_bars() -> None:
    found = timeframe_confluence(
        {Frequency.MONTH_1: MONTHLY, Frequency.DAY_1: DAILY, Frequency.WEEK_1: WEEKLY},
        derived=[Frequency.WEEK_1, Frequency.MONTH_1],
    )

    assert [(f.frequency, f.weight, f.derived) for f in found.frames] == [
        (Frequency.DAY_1, 1.0, False),
        (Frequency.WEEK_1, 2.0, True),
        (Frequency.MONTH_1, 3.0, True),
    ]
    weekly = found.frame(Frequency.WEEK_1)
    bars = WEEKLY.bars
    assert weekly.panel == signal_panel(bars["close"], bars["high"], bars["low"])
    assert (weekly.bars, weekly.last_at, weekly.issue) == (len(bars), bars.index[-1], None)
    assert weekly.trend is not None
    assert weekly.trend.sma_window == 200
    assert found.summary == confluence([(f.weight, f.score) for f in found.frames])
    assert found.summary.frames == 3
    assert (found.instrument, found.source) == (DAILY.instrument, SYNTHETIC_SOURCE)


def test_a_frame_without_data_or_with_too_few_bars_neither_counts_nor_weighs() -> None:
    short = MONTHLY.with_bars(MONTHLY.bars.iloc[-40:])

    found = timeframe_confluence(
        {
            Frequency.HOUR_1: None,
            Frequency.DAY_1: DAILY,
            Frequency.WEEK_1: WEEKLY,
            Frequency.MONTH_1: short,
        }
    )

    hourly, monthly = found.frame(Frequency.HOUR_1), found.frame(Frequency.MONTH_1)
    assert (hourly.issue, hourly.bars, hourly.score, hourly.last_at) == (
        FrameIssue.NO_DATA,
        0,
        None,
        None,
    )
    assert (monthly.issue, monthly.bars, monthly.panel) == (FrameIssue.TOO_FEW_BARS, 40, None)
    daily, weekly = found.frame(Frequency.DAY_1), found.frame(Frequency.WEEK_1)
    assert (daily.weight, weekly.weight) == (2.0, 3.0)  # their rank among the frames asked for
    assert found.summary == confluence([(2.0, daily.score), (3.0, weekly.score)])
    assert found.summary.frames == 2


def test_one_readable_frame_is_not_a_consensus() -> None:
    found = timeframe_confluence({Frequency.DAY_1: DAILY, Frequency.HOUR_1: None})

    assert found.summary.verdict is ConfluenceVerdict.INSUFFICIENT
    assert found.summary.alignment == found.frame(Frequency.DAY_1).score


def test_a_series_of_closes_skips_the_rules_that_need_highs_and_lows() -> None:
    closes = make_series(DAILY.bars["close"].to_numpy(), symbol="SYN.MC", index=DAYS)

    found = timeframe_confluence({Frequency.DAY_1: closes, Frequency.WEEK_1: closes.resample("1w")})

    panel = found.frame(Frequency.DAY_1).panel
    assert panel is not None
    assert set(panel.skipped) == {"ADX", "CCI", "WILLR"}
    assert panel.total == 8


def test_wrong_frames_are_refused() -> None:
    other = make_series(DAILY.bars["close"].to_numpy(), symbol="OTHER.MC", index=DAYS)

    with pytest.raises(DomainError, match="No frame has bars"):
        timeframe_confluence({Frequency.DAY_1: None})
    with pytest.raises(DomainError, match="1w frame got 1d bars"):
        timeframe_confluence({Frequency.WEEK_1: DAILY})
    with pytest.raises(DomainError, match="different instruments"):
        timeframe_confluence({Frequency.DAY_1: DAILY, Frequency.WEEK_1: other.resample("1w")})
    with pytest.raises(KeyError, match="4h was not read"):
        timeframe_confluence({Frequency.DAY_1: DAILY}).frame(Frequency.HOUR_4)
