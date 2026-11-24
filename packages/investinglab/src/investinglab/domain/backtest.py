"""A backtest of one instrument: validated configuration, dated trades and metrics (ADR-0049).

:func:`run_backtest` gives the engine (:func:`investinglab.analytics.backtest.simulate`) a
series' bars and its signals, and turns what it did into a :class:`BacktestResult`: the
equity at each bar's close, every trade with its dates and costs, and the metrics of its
returns annualised with the instrument's own calendar (252 sessions a year for a Spanish
share, 365 days for bitcoin).

**Prices.** A series with adjusted closes is traded at adjusted prices (open, high and low
scaled like the close), so its result is a total return: dividends reinvested and splits
undone. Without them, the raw bars are traded: bitcoin pays no dividends.

**Signals are events, not states.** ``1`` opens a position at the next bar's open, ``-1``
closes it, ``0`` holds. A missing signal is not "hold": it is an error to fix, never a value
made up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics.backtest import (
    BPS,
    FULL_SIZING,
    NO_COSTS,
    NO_RISK,
    CostModel,
    ExitReason,
    RiskModel,
    Side,
    Simulation,
    SizingMode,
    SizingModel,
    simulate,
)
from investinglab.analytics.technical import atr
from investinglab.domain.errors import DomainError
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS, RiskMetrics

if TYPE_CHECKING:
    from collections.abc import Sequence

    from investinglab.analytics.search import StrategySpec
    from investinglab.domain.instruments import Instrument
    from investinglab.domain.series import PriceSeries
    from investinglab.domain.time import Frequency

__all__ = [
    "ATR_WINDOW",
    "BacktestConfig",
    "BacktestResult",
    "BacktestTrade",
    "CostBreakdown",
    "CostModel",
    "ExitReason",
    "RiskModel",
    "SizingMode",
    "SizingModel",
    "TradeStatistics",
    "run_backtest",
]

ATR_WINDOW: Final = 14
"""Bars of the ATR the barriers in ATRs are measured with (CryptoWorld's)."""


def _finite_non_negative(value: float, what: str) -> None:
    if not (math.isfinite(value) and value >= 0):
        raise DomainError(f"{what} must be zero or more, got {value}")


def _fraction(value: float | None, what: str, *, upto_one: bool = True) -> None:
    if value is None:
        return
    if not (math.isfinite(value) and value > 0 and (value < 1 or not upto_one)):
        bound = "between 0 and 1" if upto_one else "positive"
        raise DomainError(f"{what} must be {bound} (a decimal: 0.05 is 5 %), got {value}")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """How a backtest trades: capital, costs, barriers and sizing.

    Attributes:
        initial_capital: Equity before the first bar, in the instrument's currency.
        costs: Commission, minimum commission, slippage and tax of each order.
        risk: Stops, targets and exit by time (none by default).
        sizing: How large each position is (all the equity by default).

    Raises:
        DomainError: If a value is out of its range, or the sizing needs a stop there is not.
    """

    initial_capital: float = 10_000.0
    costs: CostModel = NO_COSTS
    risk: RiskModel = NO_RISK
    sizing: SizingModel = FULL_SIZING

    def __post_init__(self) -> None:
        if not (math.isfinite(self.initial_capital) and self.initial_capital > 0):
            raise DomainError(f"The initial capital must be positive, got {self.initial_capital}")
        costs = self.costs
        for name in ("commission_bps", "minimum_commission", "slippage_bps", "transaction_tax_bps"):
            _finite_non_negative(getattr(costs, name), name)
        for name in ("commission_bps", "slippage_bps", "transaction_tax_bps"):
            if getattr(costs, name) >= BPS:
                raise DomainError(f"{name} must be below {BPS:g} (100 %)")
        risk = self.risk
        _fraction(risk.stop_loss_pct, "stop_loss_pct")
        _fraction(risk.trailing_stop_pct, "trailing_stop_pct")
        _fraction(risk.take_profit_pct, "take_profit_pct", upto_one=False)
        _fraction(risk.atr_stop_mult, "atr_stop_mult", upto_one=False)
        _fraction(risk.atr_target_mult, "atr_target_mult", upto_one=False)
        if risk.max_bars is not None and (
            isinstance(risk.max_bars, bool) or not isinstance(risk.max_bars, int)
        ):
            raise DomainError(f"max_bars must be a whole number of bars, got {risk.max_bars!r}")
        if risk.max_bars is not None and risk.max_bars < 1:
            raise DomainError(f"max_bars must be at least one bar, got {risk.max_bars}")
        sizing = self.sizing
        if not isinstance(sizing.mode, SizingMode):
            raise DomainError(f"Unknown sizing {sizing.mode!r}")
        if not (math.isfinite(sizing.fraction) and 0 < sizing.fraction <= 1):
            raise DomainError(f"The sizing fraction must be in (0, 1], got {sizing.fraction}")
        if not (math.isfinite(sizing.risk_pct) and 0 < sizing.risk_pct <= 1):
            raise DomainError(f"risk_pct must be in (0, 1], got {sizing.risk_pct}")
        if sizing.mode is SizingMode.RISK and risk.stop_loss_pct is None:
            raise DomainError("Sizing by risk needs a stop loss: the risk is the distance to it")


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    """One position of a backtest, with its dates.

    Attributes:
        side: Long or short.
        entry_time: Bar it was opened at (at its open).
        exit_time: Bar it was closed at.
        entry_price: Market price at the entry, the one stops are measured from.
        entry_fill: Price it was opened at, slippage included.
        exit_fill: Price it was closed at, slippage included.
        quantity: Units held.
        notional: Capital it took when it opened.
        pnl: Profit or loss in the instrument's currency, net of every cost.
        commission: Commissions of both orders.
        tax: Transaction tax of the purchase.
        slippage: What the fills cost against the reference prices.
        carry: Funding and borrow paid while open (negative: received).
        exit_reason: Why it was closed.
        bars: Bars it was held.
    """

    side: Side
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    entry_fill: float
    exit_fill: float
    quantity: float
    notional: float
    pnl: float
    commission: float
    tax: float
    slippage: float
    carry: float
    exit_reason: ExitReason
    bars: int

    @property
    def return_(self) -> float:
        """Result as a fraction of the capital it took."""
        return self.pnl / self.notional if self.notional else 0.0


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """What trading cost, by kind, in the instrument's currency.

    Kept apart because they grow with different things: commissions and tax with the number
    of orders, carry with the time in the market, slippage with the size against liquidity.

    Attributes:
        commission: Commissions.
        tax: Transaction taxes.
        slippage: Cost of the fills against the reference prices.
        funding: Funding of perpetuals (negative: received).
        borrow: Borrow fees of shorts.
    """

    commission: float
    tax: float
    slippage: float
    funding: float
    borrow: float

    @property
    def total(self) -> float:
        """Every cost together."""
        return self.commission + self.tax + self.slippage + self.funding + self.borrow


@dataclass(frozen=True, slots=True)
class TradeStatistics:
    """What the trades of a backtest were like.

    Attributes:
        count: Trades.
        win_rate: Share that made money (``nan`` without trades).
        average_win: Mean return of the winners (``nan`` without them).
        average_loss: Mean return of the losers, a negative number (``nan`` without them).
        profit_factor: Money won over money lost (``inf`` without losers, ``nan`` without
            trades).
        average_bars: Mean bars a trade was held (``nan`` without trades).
        best: Best trade's return.
        worst: Worst trade's return.
    """

    count: int
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    average_bars: float
    best: float
    worst: float

    @classmethod
    def of(cls, trades: Sequence[BacktestTrade]) -> TradeStatistics:
        """The statistics of ``trades``."""
        nan = float("nan")
        if not trades:
            return cls(0, nan, nan, nan, nan, nan, nan, nan)
        returns = np.array([trade.return_ for trade in trades])
        pnls = np.array([trade.pnl for trade in trades])
        wins, losses = returns[returns > 0], returns[returns <= 0]
        won, lost = float(pnls[pnls > 0].sum()), float(-pnls[pnls < 0].sum())
        return cls(
            count=len(trades),
            win_rate=float(len(wins) / len(trades)),
            average_win=float(wins.mean()) if wins.size else nan,
            average_loss=float(losses.mean()) if losses.size else nan,
            profit_factor=won / lost if lost > 0 else (math.inf if won > 0 else nan),
            average_bars=float(np.mean([trade.bars for trade in trades])),
            best=float(returns.max()),
            worst=float(returns.min()),
        )


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """What a backtest of one instrument did.

    Attributes:
        instrument: What was traded.
        frequency: Its bars' frequency.
        periods_per_year: Bars in a year on its market (the annualisation factor).
        config: How it was traded.
        equity: Equity at each bar's close, in the instrument's currency. A position still
            open at the end is closed at the last close, and the last value is after the
            costs of that close.
        trades: Every position, in order.
        costs: What trading cost, by kind.
        exposure: Share of the bars that closed with a position open.
        turnover: Notional traded over the initial capital.
        buy_and_hold: Return of holding the instrument over the same bars (close to close).
        strategy: The strategy that gave the signals, when one did.
        ready_at: The first bar from which every condition of the strategy was known: the
            bars before it are its indicators' warm-up.
    """

    instrument: Instrument
    frequency: Frequency
    periods_per_year: float
    config: BacktestConfig
    equity: pd.Series
    trades: tuple[BacktestTrade, ...]
    costs: CostBreakdown
    exposure: float
    turnover: float
    buy_and_hold: float
    strategy: StrategySpec | None = None
    ready_at: pd.Timestamp | None = None

    def with_strategy(
        self, strategy: StrategySpec, ready_at: pd.Timestamp | None
    ) -> BacktestResult:
        """The same result, saying which strategy gave its signals."""
        return replace(self, strategy=strategy, ready_at=ready_at)

    @property
    def returns(self) -> pd.Series:
        """Return of each bar; the first, against the initial capital."""
        previous = self.equity.shift(1)
        previous.iloc[0] = self.config.initial_capital
        return (self.equity / previous - 1.0).rename("returns")

    @property
    def total_return(self) -> float:
        """Final equity over the initial capital, less one."""
        return float(self.equity.iloc[-1] / self.config.initial_capital - 1.0)

    @property
    def statistics(self) -> TradeStatistics:
        """What the trades were like."""
        return TradeStatistics.of(self.trades)

    def metrics(
        self,
        *,
        risk_free_rate: float | pd.Series = 0.0,
        levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS,
    ) -> RiskMetrics:
        """Sharpe, Sortino, Calmar, drawdown and tail risk of the strategy's returns.

        Args:
            risk_free_rate: Effective annual risk-free rate (decimal), constant or
                point-in-time series.
            levels: Confidence levels for VaR and CVaR.
        """
        return RiskMetrics.from_returns(
            self.returns,
            periods_per_year=self.periods_per_year,
            risk_free_rate=risk_free_rate,
            levels=levels,
        )


def _aligned(values: pd.Series, index: pd.Index, what: str) -> np.ndarray:
    """A series bar by bar with the prices, or an error saying why it is not."""
    if not values.index.equals(index):
        raise DomainError(f"The {what} must be a series on exactly the bars of the prices")
    return values.to_numpy(dtype=np.float64)


def _per_bar(values: pd.Series | None, index: pd.Index, what: str) -> np.ndarray | None:
    return None if values is None else _aligned(values, index, what)


def _signals(values: pd.Series, index: pd.Index, what: str) -> np.ndarray:
    array = _aligned(values, index, what)
    if np.isnan(array).any():
        raise DomainError(f"The {what} have gaps: say 0 (hold) where there is no signal")
    if not set(np.unique(array)) <= {-1.0, 0.0, 1.0}:
        raise DomainError(f"The {what} must be 1 (open), -1 (close) or 0 (hold)")
    return array


def _tradeable_bars(series: PriceSeries) -> dict[str, np.ndarray]:
    """Open, high, low and close to trade at: adjusted when the series has adjusted closes."""
    bars = series.bars
    close = bars["close"].to_numpy(dtype=np.float64)
    factor = (
        bars["adj_close"].to_numpy(dtype=np.float64) / close
        if "adj_close" in bars.columns
        else np.ones_like(close)
    )
    out = {}
    for name in ("open", "high", "low"):
        raw = bars[name].to_numpy(dtype=np.float64) if name in bars.columns else close
        out[name] = raw * factor
    out["close"] = close * factor
    return out


def run_backtest(
    series: PriceSeries,
    signals: pd.Series,
    *,
    short_signals: pd.Series | None = None,
    config: BacktestConfig | None = None,
    funding: pd.Series | None = None,
    borrow: pd.Series | None = None,
    conviction: pd.Series | None = None,
) -> BacktestResult:
    """Backtest ``series`` with ``signals`` (see the module's conventions).

    Args:
        series: The prices: open, high, low and close (a close alone is used for all four).
        signals: The long side, on exactly the series' bars: ``1`` opens, ``-1`` closes,
            ``0`` holds.
        short_signals: The short side, the same way.
        config: Capital, costs, barriers and sizing.
        funding: Funding rate of each bar for a perpetual (positive: longs pay).
        borrow: Borrow fee of each bar for a short (a decimal of its value).
        conviction: Fraction of the equity the entry of each bar's signal takes, with
            ``conviction`` sizing, known at that bar's close like the signal (``NaN``: the
            sizing's fraction). The order fills at the next open, so it sizes that fill.

    Raises:
        DomainError: If an input is not on the series' bars, or a signal is not -1, 0 or 1.
    """
    config = config or BacktestConfig()
    index = series.bars.index
    longs = _signals(signals, index, "signals")
    shorts = None if short_signals is None else _signals(short_signals, index, "short signals")
    if conviction is not None and config.sizing.mode is not SizingMode.CONVICTION:
        raise DomainError("A conviction only sizes positions with the conviction sizing")
    prices = _tradeable_bars(series)
    average_range = None
    if config.risk.needs_atr:
        average_range = atr(
            pd.Series(prices["high"]),
            pd.Series(prices["low"]),
            pd.Series(prices["close"]),
            ATR_WINDOW,
        ).to_numpy()
    simulation = simulate(
        prices["open"],
        prices["high"],
        prices["low"],
        prices["close"],
        longs,
        short_signals=shorts,
        initial_capital=config.initial_capital,
        costs=config.costs,
        risk=config.risk,
        sizing=config.sizing,
        atr=average_range,
        # The engine reads it at the bar the order fills at, one after the signal's.
        conviction=None
        if conviction is None
        else np.concatenate(([np.nan], _aligned(conviction, index, "conviction")[:-1])),
        funding=_per_bar(funding, index, "funding"),
        borrow=_per_bar(borrow, index, "borrow"),
    )
    return _result(series, config, simulation, prices["close"])


def _result(
    series: PriceSeries, config: BacktestConfig, simulation: Simulation, close: np.ndarray
) -> BacktestResult:
    index = series.bars.index
    trades = tuple(
        BacktestTrade(
            side=trade.side,
            entry_time=index[trade.entry_index],
            exit_time=index[trade.exit_index],
            entry_price=trade.entry_price,
            entry_fill=trade.entry_fill,
            exit_fill=trade.exit_fill,
            quantity=trade.quantity,
            notional=trade.notional,
            pnl=trade.pnl,
            commission=trade.commission,
            tax=trade.tax,
            slippage=trade.slippage,
            carry=trade.carry,
            exit_reason=trade.exit_reason,
            bars=trade.bars,
        )
        for trade in simulation.trades
    )
    return BacktestResult(
        instrument=series.instrument,
        frequency=series.frequency,
        periods_per_year=series.periods_per_year,
        config=config,
        equity=pd.Series(
            np.append(simulation.equity[:-1], simulation.final_capital), index=index, name="equity"
        ),
        trades=trades,
        costs=CostBreakdown(
            commission=simulation.commission,
            tax=simulation.tax,
            slippage=simulation.slippage,
            funding=simulation.funding,
            borrow=simulation.borrow,
        ),
        exposure=simulation.bars_in_market / len(index),
        turnover=simulation.turnover,
        buy_and_hold=float(close[-1] / close[0] - 1.0),
    )
