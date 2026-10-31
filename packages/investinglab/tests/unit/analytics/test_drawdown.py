from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import drawdown, max_drawdown


def test_drawdown_measures_the_decline_from_the_running_peak() -> None:
    prices = pd.Series([100.0, 120.0, 90.0, 130.0, 117.0])

    assert drawdown(prices).tolist() == pytest.approx([0.0, 0.0, -0.25, 0.0, -0.10])
    assert max_drawdown(prices) == pytest.approx(-0.25)


def test_max_drawdown_of_an_increasing_series_is_zero() -> None:
    assert max_drawdown(pd.Series([1.0, 2.0, 3.0])) == 0.0


def test_max_drawdown_of_an_empty_series_is_nan() -> None:
    assert np.isnan(max_drawdown(pd.Series([], dtype="float64")))
