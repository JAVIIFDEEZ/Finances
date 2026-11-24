"""A strategy on a SYNTHETIC series: its signals, its backtest and what it is refused (ADR-0050)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.search import (
    CLASSICS,
    Block,
    Leg,
    Operator,
    PatternCondition,
    Slope,
    StrategySpec,
    Threshold,
)
from investinglab.domain import (
    CostModel,
    DomainError,
    Frequency,
    RiskModel,
    SizingMode,
    SizingModel,
    backtest_strategy,
    strategy_config,
    strategy_from_dict,
    strategy_signals,
)
from support.factories import gbm_prices, make_series

PRICES = gbm_prices(300, sigma=0.35, seed=5)
RSI = Leg("RSI", {"window": 14})


def _swing() -> StrategySpec:
    return StrategySpec(
        entry=Block((Threshold(RSI, Operator.LT, 45.0),)),
        exit=Block((Threshold(RSI, Operator.GT, 55.0),)),
        risk=RiskModel(stop_loss_pct=0.08),
        sizing=SizingModel(SizingMode.FRACTION, fraction=0.5),
    )


def test_a_strategy_trades_with_its_own_barriers_and_sizing() -> None:
    series = make_series(PRICES, ohlc=True)
    costs = CostModel(commission_bps=10, slippage_bps=5)

    result = backtest_strategy(series, _swing(), costs=costs, initial_capital=20_000)

    assert result.strategy == _swing()
    assert result.config.risk == RiskModel(stop_loss_pct=0.08)
    assert result.config.sizing.fraction == 0.5
    assert result.config.costs == costs
    assert result.config.initial_capital == 20_000
    assert result.trades
    assert result.trades[0].notional == pytest.approx(10_000)  # half the equity
    assert result.ready_at == series.bars.index[13]  # the RSI(14)'s first value
    assert result.trades[0].entry_time > result.ready_at


def test_the_signals_are_those_of_the_bars_as_traded() -> None:
    series = make_series(PRICES, ohlc=True)

    signals = strategy_signals(series, CLASSICS["sma_crossover"])
    method = series.backtest_strategy(CLASSICS["sma_crossover"])

    assert signals.long.index.equals(series.bars.index)
    assert signals.short is None
    assert signals.ready_at == series.bars.index[50]  # a cross needs the SMA(50) the bar before
    assert method.trades
    first = int(signals.long.to_numpy().argmax())  # the first entry signal
    assert method.trades[0].entry_time == series.bars.index[first + 1]


def test_a_series_too_short_for_the_strategy_is_never_ready() -> None:
    series = make_series(PRICES[:120], ohlc=True)

    signals = strategy_signals(series, CLASSICS["trend_pullback"])  # an SMA(150)
    result = series.backtest_strategy(CLASSICS["trend_pullback"])

    assert signals.ready_at is None
    assert not result.trades
    assert result.ready_at is None


def test_what_a_series_has_not_is_never_made_up() -> None:
    closes = make_series(PRICES)  # no open, high or low
    engulfing = StrategySpec(
        entry=Block((PatternCondition("BULL_ENGULF"),)),
        exit=Block((Slope(Leg("PRICE"), Operator.FALLING, 2),)),
    )
    breakout = StrategySpec(
        entry=Block((PatternCondition("ORB_UP"),)),
        exit=Block((Slope(Leg("PRICE"), Operator.FALLING, 2),)),
    )

    with pytest.raises(DomainError, match=r"reads what TEST\.MC has not: .*open"):
        strategy_signals(closes, engulfing)
    with pytest.raises(DomainError, match="needs intraday bars"):
        strategy_signals(make_series(PRICES, ohlc=True), breakout)


def test_a_session_pattern_reads_the_markets_sessions() -> None:
    hours = pd.date_range("2024-03-04 09:00", periods=24 * 10, freq="h", tz="UTC")
    series = make_series(PRICES[:240], ohlc=True, index=hours, frequency=Frequency.HOUR_1)
    breakout = StrategySpec(
        entry=Block((PatternCondition("ORB_UP", {"bars": 3}),)),
        exit=Block((Slope(Leg("PRICE"), Operator.FALLING, 2),)),
    )

    signals = strategy_signals(series, breakout)

    assert signals.long.isin([-1.0, 0.0, 1.0]).all()


def test_a_strategy_is_read_from_its_json_form_with_its_barriers_checked() -> None:
    spec = strategy_from_dict(_swing().to_dict())
    wrong = {**_swing().to_dict(), "risk": {"stop_loss_pct": 5.0}}
    no_stop = {**_swing().to_dict(), "risk": None, "sizing": {"mode": "risk", "risk_pct": 0.02}}

    assert spec == _swing()
    with pytest.raises(DomainError, match="stop_loss_pct must be between 0 and 1"):
        strategy_from_dict(wrong)
    with pytest.raises(DomainError, match="needs a stop loss"):
        strategy_from_dict(no_stop)
    with pytest.raises(DomainError, match=r"Invalid strategy: exit\.conditions\[0\]"):
        strategy_from_dict({**_swing().to_dict(), "exit": {"combine": "AND", "conditions": [{}]}})
    assert strategy_config(spec).risk == RiskModel(stop_loss_pct=0.08)


def test_a_short_strategy_trades_its_short_side() -> None:
    series = make_series(PRICES, ohlc=True)
    short = StrategySpec(
        entry=_swing().entry,
        exit=_swing().exit,
        direction="short",  # type: ignore[arg-type]
    )

    result = backtest_strategy(series, short)

    assert result.trades
    assert all(int(trade.side) == -1 for trade in result.trades)
    assert np.isfinite(result.total_return)
