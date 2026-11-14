"""Technical indicators of a price series, for any asset class (SYNTHETIC bars)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.technical import CATALOGUE, rsi
from investinglab.domain import DomainError, TechnicalIndicators, technical_indicators
from support.factories import SYNTHETIC_SOURCE, business_days, gbm_prices, make_series

DAYS = business_days(260)
FULL = make_series(
    gbm_prices(260, seed=5), symbol="FULL.MC", index=DAYS, ohlc=True, volume=[1_000.0] * 260
)
CLOSES = make_series(gbm_prices(260, seed=6), symbol="CLOSE.MC", index=DAYS)


def test_the_whole_catalogue_on_full_bars() -> None:
    indicators = technical_indicators(FULL)

    assert indicators.names == tuple(CATALOGUE)
    assert dict(indicators.unavailable) == {}
    assert indicators.values.index.equals(FULL.bars.index)
    assert indicators.parameters["RSI"] == {"window": 14}
    expected = rsi(FULL.bars["close"], 14)
    np.testing.assert_allclose(indicators["RSI"], expected)
    assert indicators.latest()["RSI"] == pytest.approx(expected.iloc[-1])
    assert indicators.instrument == FULL.instrument
    assert indicators.source == SYNTHETIC_SOURCE


def test_indicators_needing_columns_the_series_lacks_are_left_out_with_the_reason() -> None:
    indicators = technical_indicators(CLOSES)

    assert "RSI" in indicators.names
    assert "ADX" not in indicators.names
    assert indicators.unavailable["ADX"] == "the series has no high, low"
    assert indicators.unavailable["VOLRATIO"] == "the series has no volume"
    assert set(indicators.names) | set(indicators.unavailable) == set(CATALOGUE)


def test_a_selection_with_its_own_parameters() -> None:
    indicators = technical_indicators(FULL, ["SMA", "RSI", "SMA"], {"SMA": {"window": 10}})

    assert indicators.names == ("SMA", "RSI")
    assert indicators.parameters["SMA"] == {"window": 10}
    assert indicators.values["SMA"].first_valid_index() == DAYS[9]


def test_warm_up_shows_as_none_on_the_last_bar_only_when_too_short() -> None:
    short = make_series(gbm_prices(20, seed=7), symbol="SHORT.MC", index=business_days(20))

    latest = technical_indicators(short, ["SMA", "RSI"]).latest()

    assert latest["SMA"] is None  # 50 bars needed, 20 available
    assert latest["RSI"] is not None


def test_a_window_cut_after_computing_keeps_the_indicators_warm() -> None:
    indicators = technical_indicators(FULL, ["SMA"], {"SMA": {"window": 50}})

    window = indicators.between(DAYS[200], None)

    assert len(window.values) == 60
    assert not window.values["SMA"].isna().any()
    assert window.latest() == indicators.latest()
    assert indicators.between(DAYS[-1] + pd.Timedelta(days=5), None).latest() == {"SMA": None}


@pytest.mark.parametrize(
    ("names", "parameters", "message"),
    [
        (["NOPE"], None, "Unknown indicators"),
        (["RSI"], {"SMA": {"window": 5}}, "not requested"),
        (["RSI"], {"RSI": {"window": 0}}, "RSI: window must be positive"),
    ],
    ids=["unknown", "stray-parameters", "invalid-parameter"],
)
def test_invalid_requests_are_refused(
    names: list[str], parameters: dict[str, dict[str, float]] | None, message: str
) -> None:
    with pytest.raises(DomainError, match=message):
        technical_indicators(FULL, names, parameters)


def test_the_value_object_checks_its_parts() -> None:
    frame = pd.DataFrame({"RSI": [1.0]}, index=DAYS[:1])
    args = (FULL.instrument, FULL.frequency, SYNTHETIC_SOURCE)

    with pytest.raises(DomainError, match="Unknown indicators"):
        TechnicalIndicators(*args, pd.DataFrame({"NOPE": [1.0]}), {"NOPE": {}})
    with pytest.raises(DomainError, match="needs its parameters"):
        TechnicalIndicators(*args, frame, {})
    built = TechnicalIndicators(*args, frame, {"RSI": {"window": 14}})
    copy = built.values
    copy.iloc[0, 0] = 99.0
    assert built["RSI"].iloc[0] == 1.0


def test_oscillators_carry_their_threshold_range_and_levels_none() -> None:
    indicators = technical_indicators(FULL, ["RSI", "SMA"])

    assert indicators.threshold("RSI") == (15.0, 85.0)
    assert indicators.threshold("SMA") is None
    with pytest.raises(KeyError, match="was not computed"):
        indicators.threshold("ADX")
