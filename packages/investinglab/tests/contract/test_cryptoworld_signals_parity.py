"""Parity with CryptoWorld: the same rules pointing the same way on real candles (ADR-0038).

``fixtures/parity/cryptoworld_signals.json`` holds what CryptoWorld's own code said
(``scripts/record_parity.py`` ran it) on cuts of two recorded Binance cassettes: its signals
dashboard (eleven rules, their counts and their net) and the trend of its confluence card.
Every rule must point the same way, with the same figures within CryptoWorld's rounding
(six decimals; two for the trend's percentages and prices).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from investinglab.analytics.technical.signals import RULES, Bias, signal_panel, trend_state
from support.cassettes import load_cassette

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "cryptoworld_signals.json"
PARITY: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
NAMES = {
    "RSI (14)": ("RSI", "rsi"),
    "MACD (12,26,9)": ("MACD", "macd"),
    "SMA (20)": ("SMA_20", "average"),
    "SMA (50)": ("SMA_50", "average"),
    "EMA (12)": ("EMA_12", "average"),
    "EMA (26)": ("EMA_26", "average"),
    "Bollinger (20,2)": ("BOLLINGER", None),
    "Stoch RSI": ("STOCH_RSI", "k"),
    "ADX (14)": ("ADX", "adx"),
    "CCI (20)": ("CCI", "cci"),
    "Williams %R": ("WILLR", "willr"),
}
"""CryptoWorld's rule names, ours, and the figure each one reports."""
BIAS = {"COMPRA": Bias.BULLISH, "VENTA": Bias.BEARISH, "NEUTRAL": Bias.NEUTRAL}
VERDICTS = {
    "COMPRA_FUERTE": "strong_bullish",
    "COMPRA": "bullish",
    "NEUTRAL": "neutral",
    "VENTA": "bearish",
    "VENTA_FUERTE": "strong_bearish",
}
TRENDS = {"ALCISTA": "up", "BAJISTA": "down", "LATERAL": "sideways"}
SHOWN = 0.005 + 1e-9
"""Half a hundredth: what rounding to two decimals can move a value."""


def _bars(series: dict[str, Any]) -> pd.DataFrame:
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
    return frame


SERIES = {series["candles"]: (series, _bars(series)) for series in PARITY["series"]}


def _cases(kind: str) -> list[tuple[str, dict[str, Any]]]:
    return [(name, case) for name, (series, _) in SERIES.items() for case in series[kind]]


def _id(name: str, case: dict[str, Any]) -> str:
    return f"{'hourly' if '1h' in name else 'daily'}-{case['end']}"


PANELS = _cases("panels")
TRENDS_CASES = _cases("trends")


def test_the_fixture_covers_every_rule_verdict_and_trend() -> None:
    assert {NAMES[rule["name"]][0] for _, case in PANELS for rule in case["rules"]} == set(RULES)
    assert {case["summary"]["verdict"] for _, case in PANELS} == set(VERDICTS)
    assert {case["trend"] for _, case in TRENDS_CASES} == set(TRENDS)
    for ours in RULES:  # every rule pointed each way at some cut
        seen = {
            rule["signal"]
            for _, case in PANELS
            for rule in case["rules"]
            if NAMES[rule["name"]][0] == ours
        }
        assert {"COMPRA", "VENTA"} <= seen, ours


@pytest.mark.parametrize(("name", "case"), PANELS, ids=[_id(n, c) for n, c in PANELS])
def test_the_panel_equals_cryptoworlds_dashboard(name: str, case: dict[str, Any]) -> None:
    bars = SERIES[name][1].iloc[: case["end"]]

    panel = signal_panel(bars["close"], bars["high"], bars["low"])

    assert dict(panel.skipped) == {}
    assert [rule.name for rule in panel.rules] == [NAMES[r["name"]][0] for r in case["rules"]]
    for mine, theirs in zip(panel.rules, case["rules"], strict=True):
        assert mine.bias is BIAS[theirs["signal"]], mine.name
        figure = NAMES[theirs["name"]][1]
        if figure is None:  # Bollinger: "lower - upper", two decimals each
            lower, upper = (float(part) for part in theirs["value"].split(" - "))
            assert abs(mine.values["lower"] - lower) <= SHOWN
            assert abs(mine.values["upper"] - upper) <= SHOWN
        else:
            assert mine.values[figure] == pytest.approx(theirs["value"], abs=1e-4)
    summary = case["summary"]
    assert panel.count(Bias.BULLISH) == summary["buy_count"]
    assert panel.count(Bias.BEARISH) == summary["sell_count"]
    assert panel.count(Bias.NEUTRAL) == summary["neutral_count"]
    assert panel.total == summary["total"]
    assert panel.score is not None
    assert abs(panel.score - summary["score"]) <= SHOWN
    assert panel.verdict == VERDICTS[summary["verdict"]]


@pytest.mark.parametrize(("name", "case"), TRENDS_CASES, ids=[_id(n, c) for n, c in TRENDS_CASES])
def test_the_trend_equals_cryptoworlds(name: str, case: dict[str, Any]) -> None:
    bars = SERIES[name][1].iloc[: case["end"]]

    trend = trend_state(bars["close"])

    assert trend is not None
    assert trend.direction == TRENDS[case["trend"]]
    assert (trend.sma_window, trend.ema_window) == (case["sma_period"], case["ema_period"])
    assert abs(trend.sma - case["sma_value"]) <= SHOWN
    assert abs(trend.price_vs_sma_pct - case["price_vs_sma_pct"]) <= SHOWN
    assert abs(trend.ema_slope_pct - case["ema_slope_pct"]) <= SHOWN
