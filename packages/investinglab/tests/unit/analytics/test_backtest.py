"""The backtest engine, bar by bar, on hand-made prices with every figure worked out."""

from __future__ import annotations

import numpy as np
import pytest

from investinglab.analytics.backtest import (
    CostModel,
    ExitReason,
    RiskModel,
    Side,
    SizingMode,
    SizingModel,
    simulate,
)

OPEN = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
CLOSE = OPEN + 0.5
HIGH, LOW = CLOSE + 1.0, OPEN - 1.0


def _run(signals: list[int], **options: object):  # type: ignore[no-untyped-def]
    return simulate(OPEN, HIGH, LOW, CLOSE, signals, **options)  # type: ignore[arg-type]


def test_a_signal_fills_at_the_next_open_and_the_last_is_never_acted_on() -> None:
    simulation = _run([1, 0, 0, -1, 0, 1])

    (trade,) = simulation.trades
    assert (trade.entry_index, trade.exit_index) == (1, 4)
    assert (trade.entry_fill, trade.exit_fill) == (101.0, 104.0)
    assert trade.exit_reason is ExitReason.SIGNAL
    assert trade.pnl == pytest.approx(10_000 * (104 / 101 - 1))
    assert simulation.equity[0] == 10_000  # signal seen at this close, nothing filled yet
    assert simulation.bars_in_market == 3
    assert simulation.final_capital == pytest.approx(10_000 * 104 / 101)


def test_an_open_position_is_closed_at_the_last_close() -> None:
    simulation = _run([1, 0, 0, 0, 0, 0])

    (trade,) = simulation.trades
    assert (trade.exit_index, trade.exit_fill) == (5, 105.5)
    assert trade.exit_reason is ExitReason.END_OF_DATA


def test_at_the_close_only_to_compare_with_the_optimistic_engines() -> None:
    (trade,) = _run([1, 0, -1, 0, 0, 0], fill_next_bar=False).trades
    (short,) = _run([0] * 6, short_signals=[0, 1, 0, -1, 0, 0], fill_next_bar=False).trades

    assert (trade.entry_index, trade.entry_fill, trade.exit_fill) == (0, 100.5, 102.5)
    assert (short.entry_index, short.entry_fill, short.exit_fill) == (1, 101.5, 103.5)


def test_commission_and_slippage_of_a_round_trip() -> None:
    costs = CostModel(commission_bps=10, slippage_bps=20)

    simulation = _run([1, 0, -1, 0, 0, 0], costs=costs)

    (trade,) = simulation.trades
    entry_fill, exit_fill = 101 * 1.002, 103 * 0.998
    fee_in = 10_000 * 0.001
    units = (10_000 - fee_in) / entry_fill
    fee_out = units * exit_fill * 0.001
    assert (trade.entry_fill, trade.exit_fill) == pytest.approx((entry_fill, exit_fill))
    assert trade.commission == pytest.approx(fee_in + fee_out)
    assert trade.slippage == pytest.approx(units * (entry_fill - 101) + units * (103 - exit_fill))
    assert trade.pnl == pytest.approx(units * exit_fill - fee_out - 10_000)
    assert simulation.commission == pytest.approx(trade.commission)
    assert simulation.turnover == pytest.approx((10_000 + units * exit_fill) / 10_000)


def test_a_minimum_commission_and_an_order_it_would_swallow() -> None:
    minimum = CostModel(commission_bps=1, minimum_commission=4.0)

    (trade,) = _run([1, 0, -1, 0, 0, 0], costs=minimum).trades
    swallowed = _run([1, 0, -1, 0, 0, 0], costs=minimum, initial_capital=3.0)

    assert trade.commission == pytest.approx(8.0)  # 1 bp of 10 000 is 1, less than 4
    assert swallowed.trades == ()
    assert swallowed.final_capital == 3.0
    short = _run([0] * 6, short_signals=[1, 0, -1, 0, 0, 0], costs=minimum, initial_capital=3.0)
    assert short.trades == ()


def test_the_tax_is_paid_on_purchases_only() -> None:
    tax = CostModel(transaction_tax_bps=20)

    (long,) = _run([1, 0, -1, 0, 0, 0], costs=tax).trades
    (short,) = _run([0] * 6, short_signals=[1, 0, -1, 0, 0, 0], costs=tax).trades

    bought = 10_000 / 1.002  # what the shares cost, the tax on top
    assert long.tax == pytest.approx(bought * 0.002)
    assert long.quantity == pytest.approx(bought / 101)
    units = 10_000 / 101  # a short sells first: no tax on the sale...
    assert short.tax == pytest.approx(units * 103 * 0.002)  # ...but on the cover
    assert short.pnl == pytest.approx(10_000 - units * 103 * 1.002)


def test_a_tax_whose_rate_changed_is_paid_at_the_rate_of_the_fill() -> None:
    rates = np.array([0.0, 0.0, 0.003, 0.003, 0.003, 0.004])  # it starts at bar 2, rises at 5
    signals = [1, -1, 0, 1, -1, 0]
    covers = [0, 0, 0, 1, -1, 0]

    before, during = _run(signals, tax=rates).trades
    (short,) = _run([0] * 6, short_signals=covers, tax=rates).trades

    assert before.tax == 0.0  # bought at bar 1, before the tax existed
    assert during.tax == pytest.approx(during.notional / 1.003 * 0.003)  # bought at bar 4
    assert short.tax == pytest.approx(short.quantity * 105 * 0.004)  # covered at bar 5


def test_a_short_gains_when_the_price_falls_and_pays_to_borrow() -> None:
    falling = OPEN[::-1].copy()
    borrow = np.full(6, 0.001)

    simulation = simulate(
        falling, falling + 1, falling - 1, falling, [0] * 6,
        short_signals=[1, 0, 0, -1, 0, 0], borrow=borrow,
    )  # fmt: skip

    (trade,) = simulation.trades
    units = 10_000 / 104
    held = units * (falling[1:4] * 0.001).sum()  # three closes with the short open
    assert trade.side is Side.SHORT
    assert trade.carry == pytest.approx(held)
    assert simulation.borrow == pytest.approx(held)
    assert trade.pnl == pytest.approx(units * (104 - 101) - held)
    assert (simulation.position[1:4] < 0).all()


def test_funding_is_paid_by_a_long_and_received_by_a_short() -> None:
    funding = np.full(6, 0.0005)

    (long,) = _run([1, 0, -1, 0, 0, 0], funding=funding).trades
    (short,) = _run([0] * 6, short_signals=[1, 0, -1, 0, 0, 0], funding=funding).trades

    assert long.carry > 0
    assert short.carry < 0
    assert long.carry == pytest.approx(10_000 / 101 * (CLOSE[1] + CLOSE[2]) * 0.0005)


def test_the_stop_is_taken_when_a_bar_touches_both_barriers() -> None:
    risk = RiskModel(stop_loss_pct=0.02, take_profit_pct=0.02)
    wide_high, wide_low = HIGH + 10, LOW - 10  # every bar spans both

    simulation = simulate(OPEN, wide_high, wide_low, CLOSE, [1, 0, 0, 0, 0, 0], risk=risk)

    (trade,) = simulation.trades
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_index == 2
    assert trade.exit_fill == pytest.approx(101 * 0.98)


def test_a_target_and_a_trailing_stop() -> None:
    target = _run([1, 0, 0, 0, 0, 0], risk=RiskModel(take_profit_pct=0.02)).trades[0]
    trailing = simulate(
        OPEN, HIGH, np.array([99, 100, 101, 96, 103, 104.0]), CLOSE, [1, 0, 0, 0, 0, 0],
        risk=RiskModel(trailing_stop_pct=0.05),
    ).trades[0]  # fmt: skip

    assert (target.exit_reason, target.exit_fill) == (ExitReason.TAKE_PROFIT, 101 * 1.02)
    assert trailing.exit_reason is ExitReason.TRAILING_STOP
    # From the best high so far, this bar's included: it assumes the high came before the low.
    assert trailing.exit_fill == pytest.approx(HIGH[3] * 0.95)


def test_the_nearest_target_binds() -> None:
    near_in_percent = RiskModel(take_profit_pct=0.01, atr_target_mult=5.0)
    near_in_atrs = RiskModel(take_profit_pct=0.5, atr_target_mult=1.0)
    atr = np.full(6, 2.0)

    (first,) = _run([1, 0, 0, 0, 0, 0], risk=near_in_percent, atr=atr).trades
    (second,) = _run([1, 0, 0, 0, 0, 0], risk=near_in_atrs, atr=atr).trades
    (short,) = _run([0] * 6, short_signals=[1, 0, 0, 0, 0, 0], risk=near_in_percent, atr=atr).trades

    assert first.exit_fill == pytest.approx(101 * 1.01)
    assert second.exit_fill == pytest.approx(103.0)  # one ATR above the entry
    assert short.exit_reason is ExitReason.END_OF_DATA  # rising prices never reach a short's target


def test_barriers_in_atrs_need_an_atr_at_the_entry() -> None:
    risk = RiskModel(atr_stop_mult=1.0)
    lows = np.array([99, 100, 99.5, 98, 103, 104.0])

    def run(atr: float) -> object:
        signals = [1, 0, 0, 0, 0, 0]
        return simulate(OPEN, HIGH, lows, CLOSE, signals, risk=risk, atr=np.full(6, atr)).trades[0]

    measured, unmeasured = run(2.0), run(np.nan)
    assert measured.exit_reason is ExitReason.ATR_STOP  # type: ignore[attr-defined]
    assert (measured.exit_index, measured.exit_fill) == (3, 99.0)  # type: ignore[attr-defined]
    assert unmeasured.exit_reason is ExitReason.END_OF_DATA  # type: ignore[attr-defined]


def test_an_exit_by_time_fills_at_the_open() -> None:
    (trade,) = _run([1, 0, 0, 0, 0, 0], risk=RiskModel(max_bars=2)).trades

    assert (trade.exit_index, trade.exit_fill) == (3, 103.0)
    assert trade.exit_reason is ExitReason.TIME_EXIT
    assert trade.bars == 2


@pytest.mark.parametrize(
    ("sizing", "risk", "conviction", "notional"),
    [
        (SizingModel(SizingMode.FRACTION, fraction=0.4), None, None, 4_000.0),
        (SizingModel(SizingMode.RISK, risk_pct=0.01), RiskModel(stop_loss_pct=0.05), None, 2_000.0),
        (SizingModel(SizingMode.RISK, risk_pct=0.5), RiskModel(stop_loss_pct=0.05), None, 10_000.0),
        # Keyed by the bar the order fills at: the signal of bar 0 fills at bar 1.
        (
            SizingModel(SizingMode.CONVICTION, fraction=0.3),
            None,
            [np.nan, 0.6] + [np.nan] * 4,
            6_000.0,
        ),
        (SizingModel(SizingMode.CONVICTION, fraction=0.3), None, [np.nan] * 6, 3_000.0),
        (SizingModel(SizingMode.CONVICTION, fraction=0.3), None, None, 3_000.0),
    ],
    ids=["fraction", "risk", "risk-capped", "conviction", "no-conviction", "without-model"],
)
def test_each_sizing_takes_its_share_of_the_equity(
    sizing: SizingModel, risk: RiskModel | None, conviction: list[float] | None, notional: float
) -> None:
    (trade,) = _run([1, 0, -1, 0, 0, 0], sizing=sizing, risk=risk, conviction=conviction).trades

    assert trade.notional == pytest.approx(notional)


def test_a_zero_conviction_opens_nothing() -> None:
    sizing = SizingModel(SizingMode.CONVICTION)

    assert _run([1, 0, -1, 0, 0, 0], sizing=sizing, conviction=[0.0] * 6).trades == ()


def test_one_position_at_a_time_and_closing_wins() -> None:
    both = _run([1, 0, -1, 0, 0, 0], short_signals=[1, 0, 1, 0, 1, 0])

    long, short = both.trades
    assert long.side is Side.LONG  # the long signal is read first on the same bar
    assert (long.entry_index, long.exit_index) == (1, 3)
    assert both.position[2] > 0  # bar 2's short signal is not acted on: a long is open
    assert (short.side, short.entry_index) == (Side.SHORT, 5)  # bar 4's, once it is flat


def test_the_returns_start_from_the_capital() -> None:
    simulation = _run([1, 0, -1, 0, 0, 0])

    expected = simulation.equity / np.concatenate(([10_000.0], simulation.equity[:-1])) - 1
    np.testing.assert_allclose(simulation.returns, expected)
    assert simulation.returns[0] == 0.0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"signals": [1, 0, 0]}, "signals has 3 values for 6 bars"),
        ({"signals": [2, 0, 0, 0, 0, 0]}, "1 \\(open\\), -1 \\(close\\) or 0"),
        ({"signals": [np.nan, 0, 0, 0, 0, 0]}, "1 \\(open\\)"),
        ({"funding": [0.0]}, "funding has 1 values"),
    ],
)
def test_inputs_of_another_length_or_other_signals_are_refused(
    change: dict[str, object], message: str
) -> None:
    arguments: dict[str, object] = {"signals": [0] * 6} | change
    signals = arguments.pop("signals")

    with pytest.raises(ValueError, match=message):
        _run(signals, **arguments)  # type: ignore[arg-type]
