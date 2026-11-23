"""What a backtest is told: its costs, its risk barriers and how it sizes a position (ADR-0049).

Plain, frozen descriptions with no behaviour beyond reading them: the engine
(:mod:`~investinglab.analytics.backtest.engine`) applies them and the domain
(:class:`~investinglab.domain.BacktestConfig`) validates them. Rates are decimals per side
(``commission_bps=10`` is 0.1 % of the notional of each order); prices are in the
instrument's currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

__all__ = [
    "BPS",
    "FULL_SIZING",
    "NO_COSTS",
    "NO_RISK",
    "CostModel",
    "ExitReason",
    "RiskModel",
    "Side",
    "SizingMode",
    "SizingModel",
]

BPS = 10_000.0
"""Basis points in one."""


class Side(IntEnum):
    """Which way a position is open: its sign in units."""

    LONG = 1
    SHORT = -1


class ExitReason(StrEnum):
    """Why a position was closed."""

    SIGNAL = "signal"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    ATR_STOP = "atr_stop"
    TAKE_PROFIT = "take_profit"
    TIME_EXIT = "time_exit"
    END_OF_DATA = "end_of_data"


@dataclass(frozen=True, slots=True)
class CostModel:
    """What each order costs, on top of the price it is filled at.

    Attributes:
        commission_bps: Commission on the notional of each order, in basis points.
        minimum_commission: Least commission an order pays, in the instrument's currency
            (a broker's minimum per trade); an order it would exceed is not sent.
        slippage_bps: How much worse than the reference price each order is filled, in
            basis points: half the quoted spread plus the impact. A purchase pays more,
            a sale receives less.
        transaction_tax_bps: Tax on every purchase (a long's entry, a short's cover), in
            basis points of the amount bought: Spain's ITF and France's TTF on large
            listed companies, for instance.
    """

    commission_bps: float = 0.0
    minimum_commission: float = 0.0
    slippage_bps: float = 0.0
    transaction_tax_bps: float = 0.0

    @property
    def commission_rate(self) -> float:
        """Commission as a decimal of the notional."""
        return self.commission_bps / BPS

    @property
    def slippage_rate(self) -> float:
        """Slippage as a decimal of the price."""
        return self.slippage_bps / BPS

    @property
    def tax_rate(self) -> float:
        """Transaction tax as a decimal of the amount bought."""
        return self.transaction_tax_bps / BPS

    def commission(self, notional: float) -> float:
        """Commission of an order of ``notional``: the rate, or the minimum if more."""
        if notional <= 0:
            return 0.0
        return max(notional * self.commission_rate, self.minimum_commission)


NO_COSTS = CostModel()


@dataclass(frozen=True, slots=True)
class RiskModel:
    """Barriers that close a position before its signal does (decimals: ``0.05`` is 5 %).

    The stops and the targets are checked against each bar's high and low, from the bar
    after the entry; if one bar touches both, the stop is taken (the conservative reading).
    Together, ``atr_stop_mult``, ``atr_target_mult`` and ``max_bars`` are López de Prado's
    triple barrier.

    Attributes:
        stop_loss_pct: Loss from the entry price that closes the position.
        take_profit_pct: Gain from the entry price that closes it.
        trailing_stop_pct: Retreat from the best price since the entry that closes it.
        max_bars: Bars after which it is closed at the next open, whatever happened.
        atr_stop_mult: A stop this many ATRs (measured at the entry bar) from the entry.
        atr_target_mult: A target this many ATRs from the entry.
    """

    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    max_bars: int | None = None
    atr_stop_mult: float | None = None
    atr_target_mult: float | None = None

    @property
    def active(self) -> bool:
        """Whether any barrier is set."""
        return any(
            value is not None
            for value in (
                self.stop_loss_pct,
                self.take_profit_pct,
                self.trailing_stop_pct,
                self.max_bars,
                self.atr_stop_mult,
                self.atr_target_mult,
            )
        )

    @property
    def needs_atr(self) -> bool:
        """Whether a barrier is measured in ATRs."""
        return self.atr_stop_mult is not None or self.atr_target_mult is not None


class SizingMode(StrEnum):
    """How much of the equity a new position takes."""

    FULL = "full"
    """All of it: in or out of the market."""
    FRACTION = "fraction"
    """A fixed fraction; the rest stays in cash."""
    RISK = "risk"
    """As much as loses ``risk_pct`` of the equity if the stop loss is hit (never more
    than the equity: no leverage)."""
    CONVICTION = "conviction"
    """The fraction a model gives each bar (the meta-model of the Laboratory, G4); a bar
    it says nothing about takes ``fraction``."""


@dataclass(frozen=True, slots=True)
class SizingModel:
    """How large a position is when it opens.

    Attributes:
        mode: The rule (see :class:`SizingMode`).
        fraction: Fraction of the equity for ``fraction``, and the fallback of ``conviction``.
        risk_pct: Fraction of the equity at risk for ``risk``.
    """

    mode: SizingMode = SizingMode.FULL
    fraction: float = 1.0
    risk_pct: float = 0.02


NO_RISK = RiskModel()
"""No barrier: positions close only on their signals."""

FULL_SIZING = SizingModel()
"""All the equity in each position."""
