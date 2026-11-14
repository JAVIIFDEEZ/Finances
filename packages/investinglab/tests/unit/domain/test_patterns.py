"""Price patterns of a price series, for any asset class (SYNTHETIC bars)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.patterns import PATTERNS, detect
from investinglab.domain import DomainError, PricePatterns, PriceSeries, price_patterns
from investinglab.domain.instruments import EXCHANGES
from investinglab.domain.time import Frequency
from support.factories import SYNTHETIC_SOURCE, business_days, make_instrument, make_series

SESSION = frozenset({"ORB_UP", "ORB_DOWN"})


def _ohlc(n: int, seed: int) -> pd.DataFrame:
    """Random-walk bars whose open and close lie within each bar's range."""
    rng = np.random.default_rng(seed)
    centre = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = centre * (1 + rng.uniform(0, 0.01, n))
    low = centre * (1 - rng.uniform(0, 0.01, n))
    open_ = low + rng.uniform(0, 1, n) * (high - low)
    close = low + rng.uniform(0, 1, n) * (high - low)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


def _series(
    frame: pd.DataFrame, index: pd.DatetimeIndex, *, exchange: str, freq: Frequency
) -> PriceSeries:
    return PriceSeries(
        instrument=make_instrument("SYN", exchange=EXCHANGES[exchange]),
        frequency=freq,
        source=SYNTHETIC_SOURCE,
        data=frame.set_axis(index),
    )


DAYS = business_days(300)
DAILY = _series(_ohlc(300, 1), DAYS, exchange="XMAD", freq=Frequency.DAY_1)


def test_the_whole_catalogue_on_daily_bars_but_the_session_patterns() -> None:
    patterns = price_patterns(DAILY)

    assert set(patterns.names) == set(PATTERNS) - SESSION
    assert dict(patterns.unavailable) == {"ORB_UP": ("intraday",), "ORB_DOWN": ("intraday",)}
    assert patterns.flags.index.equals(DAILY.bars.index)
    assert patterns.parameters["SWEEP_LOW"] == {"window": 20}
    bars = {c: DAILY.bars[c] for c in ("open", "high", "low", "close")}
    assert patterns["BULL_ENGULF"].equals(detect("BULL_ENGULF", bars))
    assert patterns.pattern("HAMMER") is PATTERNS["HAMMER"]
    assert patterns.instrument == DAILY.instrument
    assert patterns.source == SYNTHETIC_SOURCE


def test_patterns_needing_what_the_series_lacks_are_left_out_with_it() -> None:
    closes = make_series(np.linspace(100, 120, 60), symbol="CLOSE.MC", index=business_days(60))

    patterns = price_patterns(closes)

    assert patterns.names == ()  # every pattern reads at least the high and the low
    assert patterns.unavailable["DOJI"] == ("high", "low", "open")
    assert patterns.unavailable["FVG_BULL"] == ("high", "low")
    assert patterns.unavailable["ORB_UP"] == ("high", "low", "intraday")
    assert set(patterns.unavailable) == set(PATTERNS)


def test_a_session_runs_from_the_market_opening_not_from_midnight_utc() -> None:
    """Sydney opens at 10:00, 23:00 UTC the day before: the opening bar is in the session."""
    local = pd.DatetimeIndex(
        [
            pd.Timestamp(f"2026-11-{day} {hour:02d}:00", tz="Australia/Sydney")
            for day in (16, 17)
            for hour in range(10, 16)
        ]
    )
    frame = pd.DataFrame(
        {
            "open": [10.0, 10, 10, 10, 10, 10] * 2,
            "high": [11.0, 10.4, 10.4, 10.4, 10.4, 10.9] * 2,  # a spike at the opening
            "low": [9.5, 9.6, 9.6, 9.6, 9.6, 9.9] * 2,
            "close": [10.6, 10, 10, 10, 10, 10.8] * 2,
        }
    )
    hourly = _series(frame, local.tz_convert("UTC"), exchange="XASX", freq=Frequency.HOUR_1)

    patterns = price_patterns(hourly, ["ORB_UP"], {"ORB_UP": {"bars": 2}})

    # the opening range includes the 10:00 spike (11.0): the 15:00 close (10.8) is no breakout
    assert patterns.count("ORB_UP") == 0
    # cut at midnight UTC, each 10:00 bar falls in the previous "day" and each 15:00 bar
    # breaks the range of the 11:00 and 12:00 bars
    utc_days = list(local.tz_convert("UTC").date)
    bars = {column: hourly.bars[column] for column in frame.columns}
    by_utc = detect("ORB_UP", bars, utc_days, bars=2)
    breakouts = [local[5], local[11]]  # 15:00 of both days
    assert by_utc.index[by_utc.to_numpy()].tolist() == [t.tz_convert("UTC") for t in breakouts]


def test_events_list_the_occurrences_and_zones_are_counted_instead() -> None:
    patterns = price_patterns(DAILY)

    events = patterns.events()
    assert list(events.columns) == ["time", "pattern"]
    assert not events["pattern"].isin(["FIB_DISCOUNT", "FIB_PREMIUM"]).any()
    assert events["time"].is_monotonic_increasing
    for name in ("BULL_ENGULF", "CRT"):
        assert (events["pattern"] == name).sum() == patterns.count(name)
        assert events.loc[events["pattern"] == name, "time"].iloc[-1] == patterns.last(name)
    last = patterns.flags.iloc[-1]
    assert patterns.active() == tuple(name for name in patterns.names if last[name])


def test_a_pattern_that_never_fired_has_no_last_bar() -> None:
    flat = _series(
        pd.DataFrame({"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2}, index=range(30)),
        business_days(30),
        exchange="XMAD",
        freq=Frequency.DAY_1,
    )

    patterns = price_patterns(flat, ["BULL_ENGULF", "HAMMER"])

    assert patterns.last("BULL_ENGULF") is None
    assert patterns.count("BULL_ENGULF") == 0
    assert patterns.events().empty


def test_cutting_keeps_what_the_earlier_bars_set_up() -> None:
    patterns = price_patterns(DAILY, ["OB_BULL", "SWEEP_LOW"])

    tail = patterns.between(DAYS[200])

    assert tail.flags.index[0] == DAYS[200]
    assert tail["OB_BULL"].equals(patterns["OB_BULL"].loc[DAYS[200] :])
    assert price_patterns(DAILY, ["OB_BULL"]).between(DAYS[200], DAYS[210]).flags.shape == (11, 1)
    assert isinstance(tail, PricePatterns)


def test_a_selection_with_its_own_parameters() -> None:
    patterns = price_patterns(
        DAILY, ["SWEEP_LOW", "DOJI", "SWEEP_LOW"], {"DOJI": {"max_body_pct": 0.2}}
    )

    assert patterns.names == ("SWEEP_LOW", "DOJI")
    assert patterns.parameters["DOJI"] == {"max_body_pct": 0.2}
    assert patterns.count("DOJI") >= price_patterns(DAILY, ["DOJI"]).count("DOJI")


def test_wrong_requests_are_refused() -> None:
    with pytest.raises(DomainError, match="Unknown patterns"):
        price_patterns(DAILY, ["NOPE"])
    with pytest.raises(DomainError, match="not requested"):
        price_patterns(DAILY, ["DOJI"], {"HAMMER": {"wick_ratio": 2}})
    with pytest.raises(DomainError, match="SWEEP_LOW"):
        price_patterns(DAILY, ["SWEEP_LOW"], {"SWEEP_LOW": {"window": 0}})
    with pytest.raises(KeyError, match="was not evaluated"):
        price_patterns(DAILY, ["DOJI"]).pattern("HAMMER")
    with pytest.raises(DomainError, match="Unknown patterns"):
        PricePatterns(
            DAILY.instrument, DAILY.frequency, DAILY.source, pd.DataFrame({"X": []}), {"X": {}}
        )
    with pytest.raises(DomainError, match="its parameters"):
        PricePatterns(
            DAILY.instrument, DAILY.frequency, DAILY.source, pd.DataFrame({"DOJI": []}), {}
        )


def test_an_empty_cut_has_nothing_active() -> None:
    patterns = price_patterns(DAILY, ["DOJI"]).between("2030-01-01")

    assert patterns.active() == ()
    assert patterns.events().empty
