"""Readings of the indicators: conventional zones, zero lines, levels and percentiles."""

from __future__ import annotations

import numpy as np
import pytest

from investinglab.analytics.technical import CATALOGUE
from investinglab.analytics.technical.readings import (
    CENTRED,
    FAMILIES,
    LEVELS,
    RELATIVE,
    ZONES,
    Reading,
    percentile,
    read,
)


def test_every_indicator_has_a_family_and_a_rule() -> None:
    assert set(FAMILIES) == set(CATALOGUE)
    assert set(CATALOGUE) == set(ZONES) | CENTRED | LEVELS | RELATIVE | {"PRICE"}
    assert all(lower < upper for lower, upper in ZONES.values())


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("RSI", 75.0, Reading.HIGH),
        ("RSI", 25.0, Reading.LOW),
        ("RSI", 50.0, Reading.NEUTRAL),
        ("RSI", 70.0, Reading.NEUTRAL),  # on the bound is not beyond it
        ("WILLR", -10.0, Reading.HIGH),
        ("ADX", 30.0, Reading.HIGH),  # a trend
        ("CMF", -0.1, Reading.LOW),  # selling pressure
        ("ROC", 2.5, Reading.ABOVE),
        ("MACD_LINE", -1.0, Reading.BELOW),
        ("TRIX", 0.0, Reading.NEUTRAL),
    ],
)
def test_oscillators(name: str, value: float, expected: Reading) -> None:
    assert read(name, value) == (expected, None)


def test_levels_are_read_by_the_side_of_the_close() -> None:
    assert read("SMA", 100.0, close=105.0) == (Reading.ABOVE, None)
    assert read("BB_LOWER", 100.0, close=95.0) == (Reading.BELOW, None)
    assert read("SMA", 100.0) == (None, None)  # no close, nothing to read


def test_relative_measures_are_read_against_their_history() -> None:
    history = np.arange(1.0, 101.0)

    assert read("ATR_PCT", 95.0, history=history) == (Reading.HIGH, 0.95)
    assert read("VOLRATIO", 10.0, history=history) == (Reading.LOW, 0.10)
    assert read("VOLRATIO", 50.0, history=history)[0] is Reading.NEUTRAL
    assert percentile(np.array([np.nan, np.nan]), 1.0) is None


def test_nothing_is_read_while_warming_up_or_for_the_price() -> None:
    assert read("RSI", None) == (None, None)
    assert read("RSI", float("nan")) == (None, None)
    assert read("PRICE", 100.0, close=100.0) == (None, None)
