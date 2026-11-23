"""A backtest in the domain: validated configuration, dated trades, calendar-aware metrics."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    USD,
    AssetClass,
    BacktestConfig,
    CostModel,
    DomainError,
    ExitReason,
    Frequency,
    PriceSeries,
    RiskModel,
    SizingMode,
    SizingModel,
    TradeStatistics,
    run_backtest,
)
from support.factories import (
    SYNTHETIC_SOURCE,
    business_days,
    make_bars,
    make_instrument,
    make_series,
)

PRICES = (100.0, 101.0, 103.0, 102.0, 105.0, 104.0, 106.0, 108.0)


def _series(prices: tuple[float, ...] = PRICES, **changes: object) -> PriceSeries:
    return make_series(prices, ohlc=True, **changes)  # type: ignore[arg-type]


def _signals(series: PriceSeries, values: list[int]) -> pd.Series:
    return pd.Series(values, index=series.bars.index, dtype=float)


def test_a_backtest_dates_its_trades_and_its_equity() -> None:
    series = _series()
    signals = _signals(series, [1, 0, 0, -1, 0, 0, 0, 0])

    result = run_backtest(series, signals)

    (trade,) = result.trades
    index = series.bars.index
    assert (trade.entry_time, trade.exit_time) == (index[1], index[4])
    assert trade.entry_fill == pytest.approx(101.0 * 0.995)  # the synthetic open
    assert result.equity.index.equals(index)
    assert result.returns.iloc[0] == 0.0
    assert result.total_return == pytest.approx(trade.return_)
    assert result.exposure == pytest.approx(3 / 8)
    assert result.buy_and_hold == pytest.approx(108 / 100 - 1)
    assert result.instrument == series.instrument


def test_the_metrics_follow_the_markets_calendar() -> None:
    spanish = _series()
    bitcoin = _series(symbol="BTC-USD", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
    signals = [1, 0, 0, 0, 0, 0, -1, 0]

    shares = run_backtest(spanish, _signals(spanish, signals))
    coins = run_backtest(bitcoin, _signals(bitcoin, signals))

    assert shares.periods_per_year == 252
    assert coins.periods_per_year == 365
    assert shares.metrics().periods_per_year == 252
    assert shares.metrics().total_return == pytest.approx(shares.total_return)


def test_an_open_position_is_closed_with_its_costs_in_the_last_value() -> None:
    series = _series()
    costs = CostModel(commission_bps=10, slippage_bps=10)

    result = run_backtest(
        series, _signals(series, [1, 0, 0, 0, 0, 0, 0, 0]), config=BacktestConfig(costs=costs)
    )

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.END_OF_DATA
    assert result.equity.iloc[-1] == pytest.approx(10_000 + trade.pnl)  # after the close's costs
    assert result.costs.total == pytest.approx(trade.commission + trade.slippage)
    assert result.costs.commission > 0


def test_adjusted_prices_are_traded_so_the_result_is_a_total_return() -> None:
    bars = make_bars(PRICES, ohlc=True)
    paid = np.where(np.arange(len(PRICES)) < 4, 0.97, 1.0)  # a 3 % dividend before bar 4
    bars["adj_close"] = bars["close"] * paid
    instrument = make_instrument("TEST.MC")
    series = PriceSeries(instrument, Frequency.DAY_1, SYNTHETIC_SOURCE, bars)
    raw = _series()
    signals = [1, 0, 0, 0, 0, 0, -1, 0]

    adjusted = run_backtest(series, _signals(series, signals))
    unadjusted = run_backtest(raw, _signals(raw, signals))

    assert adjusted.trades[0].entry_fill == pytest.approx(101.0 * 0.995 * 0.97)
    assert adjusted.total_return > unadjusted.total_return  # the dividend is in it


def test_barriers_in_atrs_are_measured_with_the_series_atr() -> None:
    days = 40
    rising = tuple(100.0 + i for i in range(days))
    series = make_series(rising, ohlc=True, index=business_days(days))
    values = [0] * days
    values[20] = 1
    risk = RiskModel(atr_target_mult=1.0)

    result = run_backtest(series, _signals(series, values), config=BacktestConfig(risk=risk))

    (trade,) = result.trades
    assert trade.exit_reason is ExitReason.TAKE_PROFIT


def test_conviction_sizes_the_entry_of_the_signal_it_was_known_with() -> None:
    series = _series()
    signals = _signals(series, [1, 0, -1, 0, 1, 0, -1, 0])
    conviction = pd.Series(
        [0.6, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan], index=series.bars.index
    )
    sizing = SizingModel(SizingMode.CONVICTION, fraction=0.25)

    result = run_backtest(
        series, signals, config=BacktestConfig(sizing=sizing), conviction=conviction
    )

    first, second = result.trades
    assert first.notional == pytest.approx(6_000.0)
    assert second.notional == pytest.approx(0.25 * (10_000 + first.pnl))


def test_carry_is_charged_bar_by_bar() -> None:
    series = _series()
    index = series.bars.index
    funding = pd.Series(0.001, index=index)
    borrow = pd.Series(0.0005, index=index)
    flat = _signals(series, [0] * 8)
    shorts = _signals(series, [1, 0, 0, -1, 0, 0, 0, 0])

    result = run_backtest(series, flat, short_signals=shorts, funding=funding, borrow=borrow)

    assert result.costs.funding < 0  # a short receives a positive funding rate
    assert result.costs.borrow > 0


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"initial_capital": 0.0}, "initial capital"),
        ({"costs": CostModel(commission_bps=-1)}, "commission_bps"),
        ({"costs": CostModel(slippage_bps=10_000)}, "slippage_bps must be below"),
        ({"costs": CostModel(minimum_commission=float("nan"))}, "minimum_commission"),
        ({"risk": RiskModel(stop_loss_pct=1.5)}, "stop_loss_pct must be between 0 and 1"),
        ({"risk": RiskModel(stop_loss_pct=5.0)}, "a decimal: 0.05 is 5 %"),
        ({"risk": RiskModel(take_profit_pct=0.0)}, "take_profit_pct must be positive"),
        ({"risk": RiskModel(trailing_stop_pct=-0.1)}, "trailing_stop_pct"),
        ({"risk": RiskModel(max_bars=0)}, "at least one bar"),
        ({"risk": RiskModel(max_bars=2.5)}, "whole number"),  # type: ignore[arg-type]
        ({"risk": RiskModel(atr_stop_mult=-1.0)}, "atr_stop_mult"),
        ({"sizing": SizingModel(fraction=1.5)}, "fraction must be in"),
        ({"sizing": SizingModel(risk_pct=0.0)}, "risk_pct"),
        ({"sizing": SizingModel(SizingMode.RISK)}, "needs a stop loss"),
        ({"sizing": SizingModel("half")}, "Unknown sizing"),  # type: ignore[arg-type]
    ],
)
def test_a_configuration_out_of_range_is_refused(changes: dict[str, object], message: str) -> None:
    with pytest.raises(DomainError, match=message):
        replace(BacktestConfig(), **changes)  # type: ignore[arg-type]


def test_signals_must_be_events_on_exactly_the_bars() -> None:
    series = _series()
    index = series.bars.index

    with pytest.raises(DomainError, match="exactly the bars"):
        run_backtest(series, pd.Series([0, 1], index=index[:2]))
    with pytest.raises(DomainError, match="say 0 \\(hold\\)"):
        run_backtest(series, pd.Series([np.nan] + [0] * 7, index=index))
    with pytest.raises(DomainError, match="must be 1 \\(open\\)"):
        run_backtest(series, pd.Series([2] + [0] * 7, index=index))
    with pytest.raises(DomainError, match="conviction sizing"):
        run_backtest(series, _signals(series, [0] * 8), conviction=pd.Series(0.5, index=index))


def test_trade_statistics() -> None:
    series = make_series((100.0, 100, 110, 110, 110, 99, 100, 100), ohlc=False)
    signals = _signals(series, [1, -1, 0, 1, -1, 0, 0, 0])

    result = series.backtest(signals)

    stats = result.statistics
    assert stats.count == 2
    assert stats.win_rate == 0.5
    assert stats.average_win == pytest.approx(0.1)
    assert stats.average_loss == pytest.approx(-0.1)
    assert stats.profit_factor == pytest.approx(result.trades[0].pnl / -result.trades[1].pnl)
    assert stats.average_bars == 1.0
    assert stats.best == pytest.approx(0.1)
    assert stats.worst == pytest.approx(-0.1)


def test_statistics_without_trades_or_without_losers() -> None:
    none = TradeStatistics.of(())
    winners = _series().backtest(_signals(_series(), [1, 0, -1, 0, 0, 0, 0, 0])).statistics

    assert none.count == 0
    assert np.isnan(none.win_rate)
    assert np.isnan(none.profit_factor)
    assert winners.profit_factor == float("inf")
    assert np.isnan(winners.average_loss)
