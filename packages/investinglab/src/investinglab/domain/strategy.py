"""A strategy on a series: its signals and its backtest (ADR-0050).

A :class:`~investinglab.analytics.search.StrategySpec` says when to open and close; here it
meets a :class:`~investinglab.domain.series.PriceSeries`. Its indicators and patterns read
the bars as traded, like the asset card (:func:`technical_indicators`,
:func:`price_patterns`): what the strategy sees is what was on the screen at the time, and
the backtest trades adjusted prices on top (its result is a total return). A strategy that
needs a column the series does not have, or a session pattern on daily bars, is refused:
nothing is computed from substitutes.

:func:`backtest_strategy` runs it with its own barriers and sizing; the market (costs,
funding, borrow) and the capital are the caller's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from investinglab.analytics.backtest import FULL_SIZING, NO_COSTS, NO_RISK, CostModel
from investinglab.analytics.search import StrategySpec, compile_sides
from investinglab.domain.backtest import BacktestConfig, BacktestResult, run_backtest
from investinglab.domain.errors import DomainError
from investinglab.domain.patterns import pattern_bars, session_labels
from investinglab.domain.technical import indicator_bars

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd

    from investinglab.domain.series import PriceSeries

__all__ = [
    "StrategySignals",
    "StrategySpec",
    "backtest_strategy",
    "strategy_config",
    "strategy_from_dict",
    "strategy_signals",
]


def strategy_from_dict(data: Mapping[str, Any]) -> StrategySpec:
    """Read a strategy from its JSON form (CryptoWorld's), its barriers and sizing checked.

    Raises:
        DomainError: Saying where what is wrong (``exit.conditions[1].threshold: ...``).
    """
    try:
        spec = StrategySpec.from_dict(data)
    except ValueError as error:
        raise DomainError(f"Invalid strategy: {error}") from error
    strategy_config(spec)
    return spec


def strategy_config(
    spec: StrategySpec, *, costs: CostModel = NO_COSTS, initial_capital: float = 10_000.0
) -> BacktestConfig:
    """The configuration a backtest of ``spec`` runs with: its barriers and sizing.

    Raises:
        DomainError: A barrier or a sizing out of its range (a sizing by risk needs a stop).
    """
    return BacktestConfig(
        initial_capital=initial_capital,
        costs=costs,
        risk=spec.risk or NO_RISK,
        sizing=spec.sizing or FULL_SIZING,
    )


@dataclass(frozen=True, slots=True)
class StrategySignals:
    """A strategy's signals on the bars of a series.

    Attributes:
        strategy: The strategy.
        long: Signals of the long side: ``1`` opens, ``-1`` closes, ``0`` holds.
        short: Signals of the short side; ``None`` if it only trades long.
        ready_at: The first bar from which every condition is known (``None`` if the series
            is too short for its indicators to warm up).
    """

    strategy: StrategySpec
    long: pd.Series
    short: pd.Series | None
    ready_at: pd.Timestamp | None


def strategy_signals(series: PriceSeries, strategy: StrategySpec) -> StrategySignals:
    """The signals of ``strategy`` on the bars of ``series``.

    Raises:
        DomainError: The series lacks a column the strategy reads, or the strategy has a
            session pattern and the bars are not intraday.
    """
    bars = {**pattern_bars(series), **indicator_bars(series)}
    try:
        sides = compile_sides(strategy, bars, session_labels(series))
    except KeyError as error:
        raise DomainError(
            f"The strategy reads what {series.instrument.symbol} has not: {error.args[0]}"
        ) from error
    except ValueError as error:
        raise DomainError(
            f"The strategy has a session pattern, which needs intraday bars: {error}"
        ) from error
    index = series.bars.index
    return StrategySignals(
        strategy=strategy,
        long=sides.long,
        short=sides.short,
        ready_at=index[sides.ready] if sides.ready < len(index) else None,
    )


def backtest_strategy(
    series: PriceSeries,
    strategy: StrategySpec,
    *,
    costs: CostModel = NO_COSTS,
    initial_capital: float = 10_000.0,
    funding: pd.Series | None = None,
    borrow: pd.Series | None = None,
) -> BacktestResult:
    """Backtest ``strategy`` on ``series``, with its own barriers and sizing.

    Args:
        series: The prices.
        strategy: When to open and close, its barriers and its sizing.
        costs: What each order costs on this market.
        initial_capital: Equity before the first bar, in the instrument's currency.
        funding: Funding rate of each bar for a perpetual (positive: longs pay).
        borrow: Borrow fee of each bar for a short (a decimal of its value).

    Raises:
        DomainError: The series lacks what the strategy reads, or a value is out of range.
    """
    setup = strategy_config(strategy, costs=costs, initial_capital=initial_capital)
    signals = strategy_signals(series, strategy)
    result = run_backtest(
        series,
        signals.long,
        short_signals=signals.short,
        config=setup,
        funding=funding,
        borrow=borrow,
    )
    return result.with_strategy(strategy, signals.ready_at)
