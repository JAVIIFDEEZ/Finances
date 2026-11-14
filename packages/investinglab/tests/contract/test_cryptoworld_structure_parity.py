"""Parity with CryptoWorld: the same price structure on the same real candles (ADR-0036).

``fixtures/parity/cryptoworld_structure.json`` holds what CryptoWorld's own code found
(``scripts/record_parity.py`` ran it) on cuts of two recorded Binance cassettes: its support
and resistance levels with two parameter sets, its RSI divergences and the Fibonacci levels
of its confluence card with two look-backs. CryptoWorld rounds what it shows (levels to 8
decimals and distances to 2; Fibonacci prices and RSI values to 2), so the comparison
allows that rounding and nothing more.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.structure import divergences, fibonacci_swing, support_resistance
from investinglab.analytics.technical import rsi
from support.cassettes import load_cassette

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "cryptoworld_structure.json"
PARITY: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
SHOWN = 0.005 + 1e-9
"""Half a hundredth: what rounding to two decimals can move a value."""


def _bars(series: dict[str, Any]) -> dict[str, np.ndarray]:
    rows = [
        row for exchange in load_cassette(series["candles"]).exchanges for row in exchange.payload
    ]
    frame = pd.DataFrame(
        {
            "open_time": [int(row[0]) for row in rows],
            "high": [float(row[2]) for row in rows],
            "low": [float(row[3]) for row in rows],
            "close": [float(row[4]) for row in rows],
        }
    ).drop_duplicates("open_time")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    assert frame["open_time"].tolist() == series["open_times"]  # the very same candles
    bars = {column: frame[column].to_numpy(dtype=float) for column in ("high", "low", "close")}
    bars["rsi"] = rsi(frame["close"], 14).to_numpy(dtype=float)
    return bars


SERIES = {series["candles"]: (series, _bars(series)) for series in PARITY["series"]}


def _cases(kind: str) -> list[tuple[str, dict[str, Any]]]:
    return [(name, case) for name, (series, _) in SERIES.items() for case in series[kind]]


def _id(name: str, case: dict[str, Any]) -> str:
    return f"{'hourly' if '1h' in name else 'daily'}-{case['end']}"


LEVELS = _cases("levels")
DIVERGENCES = _cases("divergences")
FIBONACCI = _cases("fibonacci")


def test_the_fixture_has_something_to_compare() -> None:
    assert len(SERIES) == 2
    assert sum(bool(case["levels"]) for _, case in LEVELS) > 0.9 * len(LEVELS)
    assert sum(bool(case["divergences"]) for _, case in DIVERGENCES) >= 10
    kinds = {d["type"] for _, case in DIVERGENCES for d in case["divergences"]}
    assert kinds == {"bearish", "bullish"}
    assert {case["direction"] for _, case in FIBONACCI} == {"ALCISTA", "BAJISTA"}


@pytest.mark.parametrize(
    ("name", "case"), LEVELS, ids=[_id(n, c) + f"-k{c['params'].get('k', 3)}" for n, c in LEVELS]
)
def test_support_and_resistance_equal_cryptoworlds(name: str, case: dict[str, Any]) -> None:
    bars = SERIES[name][1]
    end, params = case["end"], case["params"]

    ours = support_resistance(
        bars["high"][:end],
        bars["low"][:end],
        bars["close"][:end],
        params.get("k", 3),
        tolerance_pct=params.get("tolerance_pct", 0.6),
        max_levels=params.get("max_levels", 8),
    )

    assert len(ours) == len(case["levels"])
    for mine, theirs in zip(ours, case["levels"], strict=True):
        assert mine.price == pytest.approx(theirs["price"], abs=1e-8)
        assert mine.touches == theirs["touches"]
        assert mine.kind == theirs["kind"]
        assert abs(mine.distance_pct - theirs["distance_pct"]) <= SHOWN + 1e-6
        assert len(mine.positions) == mine.touches


@pytest.mark.parametrize(("name", "case"), DIVERGENCES, ids=[_id(n, c) for n, c in DIVERGENCES])
def test_divergences_equal_cryptoworlds(name: str, case: dict[str, Any]) -> None:
    bars = SERIES[name][1]
    end = case["end"]

    ours = divergences(bars["close"][:end], bars["rsi"][:end], 3, lookback=80)

    assert [d.kind for d in ours] == [d["type"] for d in case["divergences"]]
    for mine, theirs in zip(ours, case["divergences"], strict=True):
        assert mine.price_first == pytest.approx(theirs["price_from"], abs=1e-8)
        assert mine.price_second == pytest.approx(theirs["price_to"], abs=1e-8)
        assert abs(mine.oscillator_first - theirs["rsi_from"]) <= SHOWN
        assert abs(mine.oscillator_second - theirs["rsi_to"]) <= SHOWN
        assert mine.confirmed == mine.second + 3 <= end - 1  # known by the last bar, not later


@pytest.mark.parametrize(
    ("name", "case"), FIBONACCI, ids=[_id(n, c) + f"-{c['lookback']}" for n, c in FIBONACCI]
)
def test_fibonacci_levels_equal_cryptoworlds(name: str, case: dict[str, Any]) -> None:
    bars = SERIES[name][1]
    end = case["end"]

    swing = fibonacci_swing(bars["high"][:end], bars["low"][:end], case["lookback"])

    assert swing is not None
    assert abs(swing.high - case["swing_high"]) <= SHOWN
    assert abs(swing.low - case["swing_low"]) <= SHOWN
    assert swing.rising == (case["direction"] == "ALCISTA")
    assert [ratio for ratio, _ in swing.levels] == [level["ratio"] for level in case["levels"]]
    for (_, price), theirs in zip(swing.levels, case["levels"], strict=True):
        assert abs(price - theirs["price"]) <= SHOWN
    nearest = swing.nearest(float(bars["close"][end - 1]))
    assert nearest is not None
    assert nearest[0] == case["nearest_level"]["ratio"]
