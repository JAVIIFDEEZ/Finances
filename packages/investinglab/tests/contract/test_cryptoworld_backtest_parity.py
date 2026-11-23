"""Parity with CryptoWorld: the same trades and equity from the same signals (ADR-0049).

``fixtures/parity/cryptoworld_backtest.json`` holds what CryptoWorld's own engine
(``backtest_execution.simulate``) did on the recorded Binance cassette
``binance/btc_usdt_1d_2025``, in scenarios that take every path it has: costs, the fill at the
next open and at the close, stops, targets, trailing stops, the triple barrier in ATRs, exits
by time, shorts, funding and every sizing. The inputs it was given are recorded with it, so
InvestingLab's engine is fed exactly the same.

The equity, the totals and every trade must be CryptoWorld's, with one difference on purpose:
CryptoWorld's ``pnl_pct`` of a short leaves out the commission of the sale that opened it
(its cash does not), so a short's return here is lower by exactly that commission.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from investinglab.analytics.backtest import (
    BPS,
    CostModel,
    RiskModel,
    Side,
    Simulation,
    SizingMode,
    SizingModel,
    simulate,
)
from support.cassettes import load_cassette

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "cryptoworld_backtest.json"
PARITY: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
RELATIVE = 1e-10
"""Floating-point noise only: the recorded values keep 15 significant digits."""
PRICE = 5e-5 + 1e-9
"""CryptoWorld rounds a trade's prices to four decimals."""
PERCENT = 5e-3 + 1e-9
"""...and its ``pnl_pct`` to two."""


def _bars() -> dict[str, np.ndarray]:
    rows = {
        int(row[0]): row
        for exchange in load_cassette(PARITY["candles"]).exchanges
        for row in exchange.payload
    }
    times = sorted(rows)
    assert times == PARITY["open_times"]  # the very same candles
    return {
        name: np.array([float(rows[t][column]) for t in times])
        for name, column in (("open", 1), ("high", 2), ("low", 3), ("close", 4))
    }


BARS = _bars()
INPUTS: dict[str, list[float]] = PARITY["inputs"]
SCENARIOS: list[dict[str, Any]] = PARITY["scenarios"]


def _run(scenario: dict[str, Any]) -> Simulation:
    n = len(BARS["close"])
    longs = INPUTS[scenario["signals"]] if scenario["signals"] else [0] * n
    shorts = scenario.get("shorts")
    commission, slippage = scenario.get("costs", [0.0, 0.0])
    sizing = scenario.get("sizing")
    conviction = None
    if scenario.get("conviction"):
        # CryptoWorld keys a signal's size by the bar it fills at, the one after the signal.
        sizes = [
            INPUTS["conviction"][bar] if value == 1 else np.nan for bar, value in enumerate(longs)
        ]
        conviction = [np.nan, *sizes[:-1]]
    return simulate(
        BARS["open"],
        BARS["high"],
        BARS["low"],
        BARS["close"],
        longs,
        short_signals=INPUTS[shorts] if shorts else None,
        initial_capital=10_000.0,
        costs=CostModel(commission_bps=commission, slippage_bps=slippage),
        risk=RiskModel(**scenario["risk"]) if "risk" in scenario else None,
        sizing=SizingModel(
            mode=SizingMode(sizing["mode"]),
            fraction=sizing.get("fraction", 1.0),
            risk_pct=sizing.get("risk_pct", 0.02),
        )
        if sizing
        else None,
        atr=INPUTS["atr"] if scenario.get("atr") else None,
        conviction=conviction,
        funding=INPUTS["funding"] if scenario.get("funding") else None,
        fill_next_bar=scenario.get("next_bar", True),
    )


def test_the_scenarios_take_every_path_of_the_engine() -> None:
    reasons = {trade["exit_reason"] for s in SCENARIOS for trade in s["trades"]}
    sides = {trade["side"] for s in SCENARIOS for trade in s["trades"]}

    assert reasons == {
        "signal",
        "stop_loss",
        "trailing_stop",
        "atr_stop",
        "take_profit",
        "time_exit",
        "end_of_data",
    }
    assert sides == {"long", "short"}
    assert {s["sizing"]["mode"] for s in SCENARIOS if "sizing" in s} == {
        "fraction",
        "risk",
        "conviction",
    }
    assert PARITY["versions"]["numpy"] == "1.26.4"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_the_equity_and_the_totals_are_cryptoworlds(scenario: dict[str, Any]) -> None:
    simulation = _run(scenario)

    # CryptoWorld's curve starts with the capital before the first bar.
    np.testing.assert_allclose(simulation.equity, scenario["equity"][1:], rtol=RELATIVE)
    assert scenario["equity"][0] == simulation.initial_capital
    assert simulation.bars_in_market == scenario["in_market_bars"]
    assert simulation.commission == pytest.approx(scenario["commission"], rel=RELATIVE, abs=1e-9)
    assert simulation.funding == pytest.approx(scenario["funding_paid"], rel=RELATIVE, abs=1e-9)
    assert simulation.final_capital == pytest.approx(scenario["final_capital"], rel=RELATIVE)
    capital = simulation.initial_capital + sum(trade.pnl for trade in simulation.trades)
    assert capital == pytest.approx(simulation.final_capital, rel=RELATIVE)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_every_trade_is_cryptoworlds(scenario: dict[str, Any]) -> None:
    simulation = _run(scenario)
    commission = scenario.get("costs", [0.0, 0.0])[0] / BPS

    assert len(simulation.trades) == len(scenario["trades"])
    for ours, theirs in zip(simulation.trades, scenario["trades"], strict=True):
        assert (ours.entry_index, ours.exit_index) == (theirs["entry_index"], theirs["exit_index"])
        assert ours.side is (Side.LONG if theirs["side"] == "long" else Side.SHORT)
        assert ours.exit_reason.value == theirs["exit_reason"]
        assert ours.entry_price == pytest.approx(theirs["entry_price"], abs=PRICE)
        assert ours.exit_fill == pytest.approx(theirs["exit_price"], abs=PRICE)
        assert ours.carry == pytest.approx(theirs["funding_paid"], abs=5e-7)
        # A short's result here also pays the commission of the sale that opened it.
        left_out = commission if ours.side is Side.SHORT else 0.0
        assert (ours.return_ + left_out) * 100 == pytest.approx(theirs["pnl_pct"], abs=PERCENT)
