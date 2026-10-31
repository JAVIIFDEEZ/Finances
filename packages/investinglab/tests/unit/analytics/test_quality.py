from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.quality import (
    missing_sessions,
    ohlc_violations,
    robust_zscores,
    split_like_jumps,
    stale_runs,
    unexpected_sessions,
)


def test_robust_zscores_resist_the_outlier_they_measure() -> None:
    values = pd.Series([0.01, -0.01, 0.02, -0.02, 0.0, 0.015, -0.015, 0.5])

    z = robust_zscores(values)

    assert z.iloc[-1] > 20
    assert z.iloc[:-1].abs().max() < 2


def test_robust_zscores_fall_back_when_mad_is_zero() -> None:
    values = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0, 0.3])

    z = robust_zscores(values)

    assert np.isfinite(z).all()
    assert z.iloc[-1] > 4


def test_robust_zscores_of_constant_or_empty_input() -> None:
    assert (robust_zscores(pd.Series([1.0, 1.0, 1.0])) == 0).all()
    assert robust_zscores(pd.Series([], dtype=float)).empty


def test_split_like_jumps() -> None:
    prices = pd.Series([400.0, 404.0, 101.0, 102.0, 1020.0, 900.0])

    jumps = split_like_jumps(prices)

    assert jumps.round(3).tolist() == [0.25, 10.0]
    assert list(jumps.index) == [2, 4]


def test_stale_runs() -> None:
    prices = pd.Series(
        [1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 3.0, 3.0], index=pd.bdate_range("2024-01-01", periods=8)
    )

    runs = stale_runs(prices, min_length=5)

    assert runs == [(prices.index[1], prices.index[5], 5)]
    assert stale_runs(pd.Series([], dtype=float)) == []


def test_ohlc_violations() -> None:
    bars = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0, 10.0],
            "high": [11.0, 9.0, 11.0, 11.0],
            "low": [9.0, 8.0, 10.5, 12.0],
            "close": [10.5, 8.5, 10.6, 11.5],
        },
        index=pd.bdate_range("2024-01-01", periods=4),
    )

    assert list(ohlc_violations(bars)) == list(bars.index[1:])
    assert ohlc_violations(bars[["close"]]).empty
    assert len(ohlc_violations(bars[["high", "low"]])) == 1  # only high < low


def test_missing_and_unexpected_sessions() -> None:
    expected = pd.bdate_range("2024-01-01", periods=10)
    observed = pd.DatetimeIndex(
        expected.delete([3, 4]).append(pd.DatetimeIndex(["2024-01-06"]))
    ).sort_values()

    assert list(missing_sessions(observed, expected)) == list(expected[[3, 4]])
    assert list(unexpected_sessions(observed, expected)) == [pd.Timestamp("2024-01-06")]
    assert missing_sessions(pd.DatetimeIndex([]), expected).empty


@pytest.mark.parametrize("ratio", [0.9, 1.1, 0.6])
def test_ordinary_moves_are_not_splits(ratio: float) -> None:
    assert split_like_jumps(pd.Series([100.0, 100.0 * ratio])).empty
