"""Parity with CryptoWorld: the same bars flagged by the same price patterns (ADR-0035).

``fixtures/parity/cryptoworld_patterns.json`` holds what CryptoWorld's own code flagged
(``scripts/record_parity.py`` ran it) on two recorded Binance cassettes: thirteen months of
daily bars and two weeks of hourly ones. Its strategy grammar's twenty patterns must flag
exactly the same bars, with both parameter sets; the five candles only its screen had, too,
from the fifth bar on (the screen needs five bars to look at, so it says nothing before).
The session patterns get each bar's UTC date as its session, CryptoWorld's convention for a
market that never closes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.patterns import PATTERNS, detect
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from datetime import date

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "cryptoworld_patterns.json"
PARITY: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
SCREEN = {
    "Inverted Hammer": "INV_HAMMER",
    "Morning Star": "MORNING_STAR",
    "Evening Star": "EVENING_STAR",
    "Three White Soldiers": "THREE_SOLDIERS",
    "Three Black Crows": "THREE_CROWS",
}
"""CryptoWorld's screen names and the catalogue's."""


def _bars(series: dict[str, Any]) -> tuple[dict[str, pd.Series], list[date]]:
    rows = [
        row for exchange in load_cassette(series["candles"]).exchanges for row in exchange.payload
    ]
    frame = pd.DataFrame(
        {
            "open_time": [int(row[0]) for row in rows],
            "open": [float(row[1]) for row in rows],
            "high": [float(row[2]) for row in rows],
            "low": [float(row[3]) for row in rows],
            "close": [float(row[4]) for row in rows],
        }
    ).drop_duplicates("open_time")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    assert frame["open_time"].tolist() == series["open_times"]  # the very same candles
    days = pd.to_datetime(frame["open_time"], unit="ms", utc=True).dt.date.tolist()
    return {column: frame[column] for column in ("open", "high", "low", "close")}, days


SERIES = {series["candles"]: (series, *_bars(series)) for series in PARITY["series"]}
CASES = [
    (candles, item["name"], item["params"], 0, item["hits"])
    for candles, (series, _, _) in SERIES.items()
    for item in series["grammar"]
] + [
    (candles, SCREEN[item["name"]], {}, item["from"], item["hits"])
    for candles, (series, _, _) in SERIES.items()
    for item in series["screen"]
]


def test_the_fixture_covers_the_whole_catalogue() -> None:
    assert {name for _, name, _, _, _ in CASES} == set(PATTERNS)
    grammar = {item["name"] for series in PARITY["series"] for item in series["grammar"]}
    assert grammar == {name for name, pattern in PATTERNS.items() if pattern.grammar}
    assert len(SERIES) == 2  # daily and hourly bars


def test_every_case_has_something_to_compare() -> None:
    """A pattern that never fires on either series would make its parity case vacuous."""
    fired = {name for _, name, _, _, hits in CASES if hits}

    assert fired == set(PATTERNS)


@pytest.mark.parametrize(
    ("candles", "name", "params", "start", "recorded"),
    CASES,
    ids=[
        f"{'hourly' if '1h' in candles else 'daily'}-{name}"
        + "".join(f"-{v:g}" for v in params.values())
        for candles, name, params, _, _ in CASES
    ],
)
def test_flags_equal_cryptoworlds(
    candles: str, name: str, params: dict[str, float], start: int, recorded: list[int]
) -> None:
    _, bars, days = SERIES[candles]

    flags = detect(name, bars, days, **params).to_numpy()

    assert [int(i) for i in np.flatnonzero(flags) if i >= start] == recorded
