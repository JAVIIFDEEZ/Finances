"""Properties of the backtest engine on SYNTHETIC random paths and random signals.

Whatever the prices, the signals and the barriers: the cash balances with the trades, costs
never help, a long position without leverage never loses more than it took, and the position
is only ever on one side.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics.backtest import (
    CostModel,
    RiskModel,
    Simulation,
    SizingMode,
    SizingModel,
    simulate,
)

BARS = 60


@st.composite
def paths(draw: st.DrawFn) -> dict[str, np.ndarray]:
    """A random OHLC path and random long and short signals (SYNTHETIC)."""
    seed = draw(st.integers(0, 2**32 - 1))
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.03, BARS)))
    open_ = close * np.exp(rng.normal(0.0, 0.01, BARS))
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0, 0.03, BARS))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0, 0.03, BARS))

    def signals(rate: float) -> np.ndarray:
        draws = rng.random(BARS)
        return np.where(draws < rate, 1, np.where(draws > 1 - rate, -1, 0))

    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "longs": signals(0.15),
        "shorts": signals(0.1),
    }


risks = st.builds(
    RiskModel,
    stop_loss_pct=st.none() | st.floats(0.01, 0.3),
    take_profit_pct=st.none() | st.floats(0.01, 0.5),
    trailing_stop_pct=st.none() | st.floats(0.01, 0.3),
    max_bars=st.none() | st.integers(1, 20),
)
costs = st.builds(
    CostModel,
    commission_bps=st.floats(0, 50),
    minimum_commission=st.floats(0, 5),
    slippage_bps=st.floats(0, 50),
    transaction_tax_bps=st.floats(0, 40),
)


def _run(path: dict[str, np.ndarray], **options: Any) -> Simulation:
    return simulate(
        path["open"], path["high"], path["low"], path["close"], path["longs"], **options
    )


@settings(max_examples=80, deadline=None)
@given(path=paths(), risk=risks, cost=costs, shorts=st.booleans())
def test_the_cash_balances_with_the_trades(
    path: dict[str, np.ndarray], risk: RiskModel, cost: CostModel, shorts: bool
) -> None:
    simulation = _run(path, risk=risk, costs=cost, short_signals=path["shorts"] if shorts else None)

    pnl = sum(trade.pnl for trade in simulation.trades)
    assert np.isclose(simulation.final_capital, simulation.initial_capital + pnl, rtol=1e-9)
    assert np.isclose(simulation.commission, sum(t.commission for t in simulation.trades))
    assert all(t.entry_index <= t.exit_index for t in simulation.trades)
    for earlier, later in zip(simulation.trades, simulation.trades[1:], strict=False):
        assert earlier.exit_index <= later.entry_index  # one position at a time


@settings(max_examples=80, deadline=None)
@given(path=paths(), risk=risks, cost=costs, fraction=st.floats(0.05, 1.0))
def test_costs_never_help(
    path: dict[str, np.ndarray], risk: RiskModel, cost: CostModel, fraction: float
) -> None:
    sizing = SizingModel(SizingMode.FRACTION, fraction=fraction)
    free = _run(path, risk=risk, sizing=sizing)
    paid = _run(path, risk=risk, sizing=sizing, costs=cost)

    # Entries, stops and targets are set by prices only: the same trades at the same bars.
    def bars(simulation: Simulation) -> list[tuple[int, int]]:
        return [(t.entry_index, t.exit_index) for t in simulation.trades]

    assert bars(paid) == bars(free)
    assert paid.final_capital <= free.final_capital * (1 + 1e-12)


@settings(max_examples=80, deadline=None)
@given(path=paths(), risk=risks, cost=costs)
def test_a_long_without_leverage_never_loses_more_than_it_took(
    path: dict[str, np.ndarray], risk: RiskModel, cost: CostModel
) -> None:
    simulation = _run(path, risk=risk, costs=cost)

    assert (simulation.equity > 0).all()
    assert all(trade.return_ >= -1.0 for trade in simulation.trades)
    assert (simulation.position >= 0).all()
