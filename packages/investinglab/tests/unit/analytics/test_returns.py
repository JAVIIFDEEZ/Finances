from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import cumulative_returns, log_returns, simple_returns, total_return


def _prices(values: list[float], dates: list[str] | None = None) -> pd.Series:
    index = pd.DatetimeIndex(dates) if dates else pd.bdate_range("2024-01-01", periods=len(values))
    return pd.Series(values, index=index, name="X")


def test_simple_returns_are_measured_between_consecutive_prices() -> None:
    result = simple_returns(_prices([100.0, 110.0, 99.0]))

    assert result.tolist() == pytest.approx([0.10, -0.10])
    assert list(result.index) == list(_prices([100.0, 110.0, 99.0]).index[1:])


def test_log_returns_add_up_to_the_log_of_the_total_growth() -> None:
    prices = _prices([100.0, 110.0, 99.0, 120.0])

    assert log_returns(prices).sum() == pytest.approx(np.log(120.0 / 100.0))


def test_missing_prices_are_skipped_not_treated_as_zero_returns() -> None:
    prices = _prices([100.0, np.nan, 121.0])

    result = simple_returns(prices)

    assert len(result) == 1
    assert result.iloc[0] == pytest.approx(0.21)


def test_dataframe_columns_use_their_own_calendar() -> None:
    frame = pd.DataFrame(
        {"A": [100.0, 110.0, 121.0], "B": [50.0, np.nan, 55.0]},
        index=pd.bdate_range("2024-01-01", periods=3),
    )

    result = simple_returns(frame)

    assert result["A"].dropna().tolist() == pytest.approx([0.10, 0.10])
    # B was not observed on the second day: its move is attributed to the third day.
    assert np.isnan(result.loc[frame.index[1], "B"])
    assert result.loc[frame.index[2], "B"] == pytest.approx(0.10)


def test_empty_dataframe_keeps_its_columns() -> None:
    frame = pd.DataFrame({"A": []}, index=pd.DatetimeIndex([]), dtype="float64")

    assert list(simple_returns(frame).columns) == ["A"]
    assert list(log_returns(frame).columns) == ["A"]
    assert simple_returns(pd.DataFrame(index=pd.DatetimeIndex([]))).empty


def test_cumulative_returns_compound() -> None:
    returns = pd.Series([0.10, -0.10])

    assert cumulative_returns(returns).tolist() == pytest.approx([0.10, -0.01])


def test_total_return() -> None:
    assert total_return(_prices([100.0, 90.0, 125.0])) == pytest.approx(0.25)
    assert np.isnan(total_return(_prices([100.0])))
