from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import drawdown, drawdown_episodes, max_drawdown


def test_drawdown_measures_the_decline_from_the_running_peak() -> None:
    prices = pd.Series([100.0, 120.0, 90.0, 130.0, 117.0])

    assert drawdown(prices).tolist() == pytest.approx([0.0, 0.0, -0.25, 0.0, -0.10])
    assert max_drawdown(prices) == pytest.approx(-0.25)


def test_max_drawdown_of_an_increasing_series_is_zero() -> None:
    assert max_drawdown(pd.Series([1.0, 2.0, 3.0])) == 0.0


def test_max_drawdown_of_an_empty_series_is_nan() -> None:
    assert np.isnan(max_drawdown(pd.Series([], dtype="float64")))


DATES = pd.bdate_range("2024-01-01", periods=9)


def test_drawdown_episodes_from_peak_to_recovery() -> None:
    # Peak 120 → trough 90 (-25 %) → recovery at 125; peak 125 → trough 100 (-20 %), open.
    prices = pd.Series([100.0, 120.0, 100.0, 90.0, 110.0, 125.0, 110.0, 100.0, 105.0], index=DATES)

    episodes = drawdown_episodes(prices)

    assert list(episodes.columns) == [
        "peak",
        "trough",
        "recovery",
        "depth",
        "decline_periods",
        "recovery_periods",
        "duration_periods",
    ]
    first, second = episodes.iloc[0], episodes.iloc[1]
    assert (first["peak"], first["trough"], first["recovery"]) == (DATES[1], DATES[3], DATES[5])
    assert first["depth"] == pytest.approx(-0.25)
    assert (first["decline_periods"], first["recovery_periods"], first["duration_periods"]) == (
        2,
        2.0,
        4,
    )
    assert (second["peak"], second["trough"]) == (DATES[5], DATES[7])
    assert pd.isna(second["recovery"])
    assert second["depth"] == pytest.approx(-0.2)
    assert np.isnan(second["recovery_periods"])
    assert second["duration_periods"] == 3


def test_deepest_episode_matches_the_maximum_drawdown() -> None:
    prices = pd.Series([100.0, 120.0, 100.0, 90.0, 110.0, 125.0, 110.0, 100.0, 105.0], index=DATES)

    assert drawdown_episodes(prices)["depth"].iloc[0] == pytest.approx(max_drawdown(prices))


def test_top_keeps_the_deepest_episodes() -> None:
    prices = pd.Series([100.0, 90.0, 100.0, 80.0, 100.0, 95.0, 100.0, 99.0, 100.0], index=DATES)

    episodes = drawdown_episodes(prices, top=2)

    assert episodes["depth"].tolist() == pytest.approx([-0.2, -0.1])


def test_series_without_drawdowns_have_no_episodes() -> None:
    episodes = drawdown_episodes(pd.Series([1.0, 2.0, 3.0], index=DATES[:3]))

    assert episodes.empty
    assert "depth" in episodes.columns


def test_top_must_be_positive() -> None:
    with pytest.raises(ValueError, match="top must be at least 1"):
        drawdown_episodes(pd.Series([1.0, 2.0]), top=0)
