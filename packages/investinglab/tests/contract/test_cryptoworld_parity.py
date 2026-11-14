"""Parity with CryptoWorld: the same indicator values on the same real candles (ADR-0034).

``fixtures/parity/cryptoworld_indicators.json`` holds what CryptoWorld's strategy grammar
computed (with ``ta`` 0.11.0) on the recorded Binance cassette ``binance/btc_usdt_1d_2025``;
``scripts/record_parity.py`` wrote it by running CryptoWorld's own code. Every value
InvestingLab defines must equal CryptoWorld's; the only values CryptoWorld has and we do not
are warm-up values ``ta`` makes up (zeros, partial windows, the close as a first SAR).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.technical import CATALOGUE, compute
from support.cassettes import load_cassette

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "cryptoworld_indicators.json"
)
PARITY: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
RELATIVE = 1e-10
"""Tolerance: floating-point noise only (the recorded values keep 15 significant digits)."""


def _bars() -> dict[str, pd.Series]:
    rows = [
        row for exchange in load_cassette(PARITY["candles"]).exchanges for row in exchange.payload
    ]
    frame = pd.DataFrame(
        {
            "open_time": [int(row[0]) for row in rows],
            "high": [float(row[2]) for row in rows],
            "low": [float(row[3]) for row in rows],
            "close": [float(row[4]) for row in rows],
            "volume": [float(row[5]) for row in rows],
        }
    ).drop_duplicates("open_time")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    assert frame["open_time"].tolist() == PARITY["open_times"]  # the very same candles
    return {column: frame[column] for column in ("high", "low", "close", "volume")}


BARS = _bars()
CASES = [(item["name"], item["params"], item["values"]) for item in PARITY["indicators"]]


def test_the_fixture_covers_the_whole_catalogue() -> None:
    assert {name for name, _, _ in CASES} == set(CATALOGUE)
    assert PARITY["versions"]["ta"] == "0.11.0"


@pytest.mark.parametrize(
    ("name", "params", "recorded"),
    CASES,
    ids=[f"{name}-{'-'.join(f'{v:g}' for v in params.values())}" for name, params, _ in CASES],
)
def test_values_equal_cryptoworlds(
    name: str, params: dict[str, float], recorded: list[float | None]
) -> None:
    ours = compute(name, BARS, **params).to_numpy(dtype=float)
    theirs = np.array([np.nan if v is None else v for v in recorded], dtype=float)

    defined = ~np.isnan(ours)
    np.testing.assert_allclose(ours[defined], theirs[defined], rtol=RELATIVE, atol=1e-12)
    first = int(np.argmax(defined))
    assert defined.any()
    assert defined[first:].all()  # once defined, never a gap again
    made_up = np.flatnonzero(~defined & ~np.isnan(theirs))
    assert (made_up < first).all(), "CryptoWorld defines values after our warm-up"
