"""Backtests over HTTP: a strategy as data, a market's costs and what trading it did.

The strategy is CryptoWorld's JSON form (ADR-0050), typed condition by condition so that
clients get its types; the core validates it again (:meth:`StrategySpec.from_dict`) and its
problems come back as ``invalid-strategy`` with where they are.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from investinglab.domain.strategy import strategy_from_dict
from investinglab_api.schemas.common import ApiModel, DateRange, FiniteFloat, Point, RequestModel
from investinglab_api.schemas.market import MetricsOut

if TYPE_CHECKING:
    from investinglab.analytics.search import StrategySpec

__all__ = [
    "CLASSIC_NAMES",
    "BacktestIn",
    "BacktestOut",
    "BlockIn",
    "ClassicOut",
    "ClassicStrategy",
    "CompareIn",
    "ConditionIn",
    "CostProfileOut",
    "CostsOut",
    "CrossIn",
    "LegIn",
    "MarketOut",
    "PatternIn",
    "RegimeIn",
    "RiskIn",
    "SizingIn",
    "SlopeIn",
    "StrategyIn",
    "ThresholdIn",
    "TradeOut",
    "TradeStatisticsOut",
]

type ClassicStrategy = Literal[
    "rsi_reversal",
    "macd_crossover",
    "sma_crossover",
    "ema_trend",
    "bollinger_bounce",
    "donchian_breakout",
    "trend_pullback",
]
CLASSIC_NAMES: tuple[str, ...] = ClassicStrategy.__value__.__args__
"""The classic strategies by name (a test checks they are the core's)."""

Parameters = dict[str, FiniteFloat]


class LegIn(RequestModel):
    """An indicator of the catalogue with its parameters (defaults where left out)."""

    indicator: str = Field(description="Its name in the catalogue (`SMA`, `PRICE`...).")
    params: Parameters = Field(default_factory=dict)


class ThresholdIn(RequestModel):
    """An oscillator above (`gt`) or below (`lt`) a value."""

    type: Literal["threshold"]
    indicator: str
    params: Parameters = Field(default_factory=dict)
    op: Literal["gt", "lt"]
    threshold: FiniteFloat
    negate: bool = False


class CrossIn(RequestModel):
    """A price level crossing another on this bar (it cannot be negated)."""

    type: Literal["cross"]
    a: LegIn
    b: LegIn
    op: Literal["cross_above", "cross_below"]


class CompareIn(RequestModel):
    """A price level above or below another while it lasts."""

    type: Literal["compare"]
    a: LegIn
    b: LegIn
    op: Literal["above", "below"]
    negate: bool = False


class SlopeIn(RequestModel):
    """An indicator higher (`rising`) or lower (`falling`) than `bars` ago."""

    type: Literal["slope"]
    indicator: str
    params: Parameters = Field(default_factory=dict)
    op: Literal["rising", "falling"]
    bars: int = Field(ge=1)
    negate: bool = False


class PatternIn(RequestModel):
    """A price pattern on this bar or on one of the `lookback - 1` before."""

    type: Literal["pattern"]
    pattern: str = Field(description="Its name in the catalogue (`SWEEP_LOW`...).")
    params: Parameters = Field(default_factory=dict)
    lookback: int = Field(default=1, ge=1)
    negate: bool = Field(default=False, description="Needs a lookback of 3 bars or more.")


ConditionIn = Annotated[
    ThresholdIn | CrossIn | CompareIn | SlopeIn | PatternIn, Field(discriminator="type")
]


class BlockIn(RequestModel):
    """One to three conditions, joined by `AND`, `OR` or at least `k` of them."""

    combine: Literal["AND", "OR", "K_OF_N"] = "AND"
    k: int | None = Field(default=None, description="With `K_OF_N`: from 2 to one fewer than n.")
    conditions: list[ConditionIn] = Field(min_length=1, max_length=3)


class RiskIn(RequestModel):
    """Barriers that close a position before its signal does (decimals: 0.05 is 5 %)."""

    stop_loss_pct: FiniteFloat | None = None
    take_profit_pct: FiniteFloat | None = None
    trailing_stop_pct: FiniteFloat | None = None
    max_bars: int | None = Field(default=None, ge=1)
    atr_stop_mult: FiniteFloat | None = None
    atr_target_mult: FiniteFloat | None = None


class SizingIn(RequestModel):
    """How large a position is: all the equity, a fraction, or what a stop loses."""

    mode: Literal["full", "fraction", "risk"] = "full"
    fraction: FiniteFloat | None = Field(default=None, description="With `fraction`.")
    risk_pct: FiniteFloat | None = Field(default=None, description="With `risk`.")


class RegimeIn(RequestModel):
    """Enter only in a trend: the ADX(14) at least `adx_min`."""

    adx_min: FiniteFloat


class StrategyIn(RequestModel):
    """A strategy in CryptoWorld's JSON form (ADR-0050)."""

    entry: BlockIn
    exit: BlockIn
    direction: Literal["long", "short", "both"] = "long"
    short_entry: BlockIn | None = Field(default=None, description="With `both`.")
    short_exit: BlockIn | None = Field(default=None, description="With `both`.")
    risk: RiskIn | None = None
    sizing: SizingIn | None = None
    regime: RegimeIn | None = None

    def to_spec(self) -> StrategySpec:
        """The core's strategy, validated again by the core.

        Raises:
            DomainError: Saying where what is wrong (``exit.conditions[1]...``).
        """
        return strategy_from_dict(self.model_dump(mode="json", exclude_none=True))


class BacktestIn(DateRange):
    """A strategy on one symbol, with the costs of its market (ADR-0051)."""

    symbol: str = Field(min_length=1, description="`SAN.MC`, `BTC/USDT`...")
    strategy: StrategyIn | ClassicStrategy = Field(
        description="A strategy, or the name of a classic one."
    )
    profile: str | None = Field(
        default=None, description="A cost profile (`XMAD`, `binance-usdm`); where it trades."
    )
    taxable: bool | None = Field(
        default=None, description="Whether purchases pay the market's tax, if not presumed."
    )
    commission_bps: FiniteFloat | None = Field(default=None, ge=0, description="Your broker's.")
    minimum_commission: FiniteFloat | None = Field(default=None, ge=0)
    slippage_bps: FiniteFloat | None = Field(default=None, ge=0)
    initial_capital: FiniteFloat = Field(default=10_000.0, gt=0)

    def to_strategy(self) -> StrategySpec | str:
        """What the toolkit backtests: the strategy, or a classic's name."""
        return self.strategy if isinstance(self.strategy, str) else self.strategy.to_spec()


class TradeOut(ApiModel):
    """One position, from its entry to its exit."""

    side: Literal["long", "short"]
    entry_time: date | datetime
    exit_time: date | datetime
    entry_fill: float
    exit_fill: float
    quantity: float
    notional: float
    pnl: float
    trade_return: float = Field(description="Its result over what it took, net of costs.")
    commission: float
    tax: float
    slippage: float
    carry: float = Field(description="Funding and borrow paid while open (negative: earned).")
    exit_reason: str
    bars: int


class TradeStatisticsOut(ApiModel):
    """What the trades were like (`null` where undefined: no trades, no losers...)."""

    count: int
    win_rate: float | None
    average_win: float | None
    average_loss: float | None
    profit_factor: float | None
    average_bars: float | None
    best: float | None
    worst: float | None


class CostsOut(ApiModel):
    """What trading cost, by kind, in the instrument's currency."""

    commission: float
    tax: float
    slippage: float
    funding: float = Field(description="Negative: earned.")
    borrow: float
    total: float


class CostProfileOut(ApiModel):
    """A market's costs: what is published, what is assumed, what is left out."""

    key: str
    name: str
    as_of: date = Field(description="When its fees were read from their sources.")
    product: Literal["cash", "perpetual"]
    commission_bps: float
    minimum_commission: float
    slippage_bps: float
    borrow_bps: float = Field(description="Yearly fee to borrow what a short sells.")
    shortable: bool
    tax: str | None = Field(description="The tax on purchases (`ITF`, `TTF`...), if any.")
    tax_bps: float | None = Field(description="Its rate today, in basis points.")
    sources: list[str]
    assumed: list[str] = Field(description="Which of its figures are assumptions.")
    unmodelled: list[str] = Field(description="Costs of this market a backtest leaves out.")


class MarketOut(ApiModel):
    """The costs a backtest paid."""

    profile: CostProfileOut
    commission_bps: float = Field(description="The commission charged (yours, if given).")
    minimum_commission: float
    slippage_bps: float
    taxable: bool
    tax_presumed: bool = Field(description="Presumed in scope: no ISIN said the issuer.")


class BacktestOut(ApiModel):
    """What trading a strategy on one symbol did."""

    symbol: str
    name: str
    currency: str
    frequency: str
    strategy: StrategyIn
    definition_hash: str = Field(description="Identifies the strategy (CryptoWorld's hash).")
    start: date | datetime = Field(description="First bar traded.")
    end: date | datetime = Field(description="Last bar traded.")
    ready_at: date | datetime | None = Field(
        description="First bar every condition was known (before: its indicators' warm-up)."
    )
    initial_capital: float
    final_equity: float
    total_return: float
    buy_and_hold: float
    exposure: float = Field(description="Share of the bars with a position open.")
    turnover: float = Field(description="Notional traded over the initial capital.")
    metrics: MetricsOut
    statistics: TradeStatisticsOut
    costs: CostsOut
    market: MarketOut | None
    equity: list[Point]
    trades: list[TradeOut]


class ClassicOut(ApiModel):
    """A classic strategy, by name."""

    name: str
    strategy: StrategyIn
    definition_hash: str
