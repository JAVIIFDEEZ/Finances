"""Parity with CryptoWorld: the same strategies, the same hashes, the same signals (ADR-0050).

``fixtures/parity/cryptoworld_strategies.json`` holds what CryptoWorld's own code did
(``scripts/record_parity.py`` ran it): its seven classic strategies (``seed_specs``) and sixty
drawn by its generator (``random_spec``, long, short and both ways, with negations,
"k of n" blocks, regime filters and every family of patterns), each with its definition hash
and the signals its compiler gave on two recorded Binance cassettes (daily and hourly).

Every strategy must read as the same JSON, hash the same, and give the same signals from
the first bar its conditions are known (:attr:`Sides.ready`). Before it, CryptoWorld's
``ta`` made up indicator values and could fire on them; here those bars hold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.search import CLASSICS, StrategyDirection, StrategySpec, compile_sides
from support.cassettes import load_cassette

if TYPE_CHECKING:
    from datetime import date

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "cryptoworld_strategies.json"
)
PARITY: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
COLUMNS = ("open", "high", "low", "close", "volume")


def _bars(name: str) -> tuple[dict[str, pd.Series], list[date]]:
    rows = [row for exchange in load_cassette(name).exchanges for row in exchange.payload]
    frame = pd.DataFrame(
        {
            "open_time": [int(row[0]) for row in rows],
            **{column: [float(row[i + 1]) for row in rows] for i, column in enumerate(COLUMNS)},
        }
    ).drop_duplicates("open_time")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    assert frame["open_time"].tolist() == PARITY["series"][name]  # the very same candles
    days = pd.to_datetime(frame["open_time"], unit="ms", utc=True).dt.date.tolist()
    return {column: frame[column] for column in COLUMNS}, days


SERIES = {name: _bars(name) for name in PARITY["series"]}
CASES = [
    pytest.param(case, name, id=f"{number:02d}-{case['origin']}-{name.split('/')[-1]}")
    for number, case in enumerate(PARITY["strategies"])
    for name in SERIES
]


def _dense(events: dict[str, list[int]], size: int) -> np.ndarray:
    signals = np.zeros(size)
    signals[events["opens"]] = 1.0
    signals[events["closes"]] = -1.0
    return signals


def test_the_classics_are_cryptoworlds_seeds() -> None:
    seeds = [case for case in PARITY["strategies"] if case["origin"] == "classic"]

    assert [spec.to_dict() for spec in CLASSICS.values()] == [case["spec"] for case in seeds]
    assert [spec.definition_hash for spec in CLASSICS.values()] == [c["hash"] for c in seeds]


def test_the_set_takes_every_path_of_the_grammar() -> None:
    specs = [StrategySpec.from_dict(case["spec"]) for case in PARITY["strategies"]]
    conditions = [condition for spec in specs for condition in spec.conditions]

    assert {spec.direction for spec in specs} == set(StrategyDirection)
    assert {str(condition.kind) for condition in conditions} == {
        "threshold",
        "cross",
        "compare",
        "slope",
        "pattern",
    }
    assert any(condition.negate for condition in conditions)
    assert {str(b.combine) for s in specs for b in s.blocks.values()} == {"AND", "OR", "K_OF_N"}
    assert any(spec.regime for spec in specs)
    assert any(spec.risk for spec in specs)
    assert any(spec.sizing for spec in specs)
    families = {c.entry.family for c in conditions if str(c.kind) == "pattern"}  # type: ignore[union-attr]
    assert {str(family) for family in families} == {"candle", "liquidity", "session", "zone"}


@pytest.mark.parametrize(("case", "name"), CASES)
def test_signals_equal_cryptoworlds(case: dict[str, Any], name: str) -> None:
    spec = StrategySpec.from_dict(case["spec"])
    bars, sessions = SERIES[name]

    sides = compile_sides(spec, bars, sessions)

    assert spec.to_dict() == case["spec"]  # the same JSON, so the same hash
    assert spec.definition_hash == case["hash"]
    size = len(bars["close"])
    assert sides.ready < size - size // 4  # most of the series is compared
    recorded = case["signals"][name]
    ready = sides.ready
    long = _dense(recorded["long"], size)
    np.testing.assert_array_equal(sides.long.to_numpy()[ready:], long[ready:])
    if recorded["short"] is None:
        assert sides.short is None
    else:
        assert sides.short is not None
        short = _dense(recorded["short"], size)
        np.testing.assert_array_equal(sides.short.to_numpy()[ready:], short[ready:])
