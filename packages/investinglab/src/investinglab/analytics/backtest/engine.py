"""The bar-by-bar simulation of one instrument's signals (ADR-0049).

A port of CryptoWorld's ``backtest_execution.simulate``, checked against its own output (the
parity tests), plus what a multi-asset platform needs: a minimum commission per order, a tax
on purchases and the borrow fee of a short.

**When an order fills.** A signal is computed with the close of bar ``i``, so the earliest it
can be acted on is the **open of bar** ``i + 1``. Filling at the close that produced it would
trade at a price already seen with zero latency: an optimism the signal itself cannot reveal.
The bars are the market's sessions, so the open after a Friday is Monday's, or Tuesday's when
Monday is a holiday. A signal on the last bar is never executed: there is no next bar.

Two exceptions, and why:

* **Stops and targets** fill at their own price inside the bar that touches them: they are
  resting orders, not decisions taken after seeing a close. If a bar touches both, the stop
  is taken.
* **The exit by time** (``max_bars``) fills at the open of the bar it falls due: when that
  bar opens the position has already run its course.

**A short is not a long with the sign changed.**

* **Sale first.** Units it does not own are sold, so cash rises and the position is negative.
* **The stop goes above the entry and the target below.** Its loss has no ceiling.
* **Funding changes sign.** A positive rate (longs pay) is income for a short.
* **It pays to borrow** the units, every bar it is open.

One position at a time: a bar that says both "close" and "open the other side" closes;
turning around in one bar would take two fills at one price.

**Carry** (funding of a perpetual, borrow of a short) is charged at each bar's close on the
market value of the position, and counts in the result of its trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import numpy as np

from investinglab.analytics.backtest.models import (
    NO_COSTS,
    CostModel,
    ExitReason,
    RiskModel,
    Side,
    SizingMode,
    SizingModel,
)

if TYPE_CHECKING:
    from numpy.typing import ArrayLike, NDArray

__all__ = ["Simulation", "Trade", "simulate"]

_ENTER_LONG: Final = 1
_ENTER_SHORT: Final = 2
_EXIT: Final = -1
_SIGNAL_VALUES: Final = frozenset({-1, 0, 1})


@dataclass(frozen=True, slots=True)
class Trade:
    """One position, from the order that opened it to the one that closed it.

    Attributes:
        side: Long or short.
        entry_index: Bar it was opened at.
        exit_index: Bar it was closed at.
        entry_price: Market price at the entry, the one stops and targets are measured from.
        entry_fill: Price it was bought (or sold short) at, slippage included.
        exit_fill: Price it was closed at, slippage included.
        quantity: Units held (positive for either side).
        notional: Capital the position took when it opened.
        pnl: Profit or loss in money, net of every cost: commissions, tax and carry.
        commission: Commissions of both orders.
        tax: Transaction tax of the purchase (the entry of a long, the cover of a short).
        slippage: What the fills cost against the reference prices.
        carry: Funding and borrow paid while open (negative: received).
        exit_reason: Why it was closed.
    """

    side: Side
    entry_index: int
    exit_index: int
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

    @property
    def return_(self) -> float:
        """Result as a fraction of the capital it took."""
        return self.pnl / self.notional if self.notional else 0.0

    @property
    def bars(self) -> int:
        """Bars it was held."""
        return self.exit_index - self.entry_index


@dataclass(frozen=True, slots=True)
class Simulation:
    """What the simulation did, bar by bar and trade by trade.

    Attributes:
        initial_capital: Equity before the first bar.
        equity: Equity at each bar's close: cash plus the position at that close.
        final_capital: Cash once a position still open has been closed at the last close,
            with the costs of that close (the last ``equity`` is before them).
        position: Units held at each bar's close (negative: short).
        trades: Every position, closed ones only (an open one closes at the last close).
        commission: Total commission paid.
        tax: Total transaction tax paid.
        slippage: Total cost of the fills against the reference prices.
        funding: Total funding paid (negative: received).
        borrow: Total borrow fee of the shorts.
        traded: Gross notional of every order.
    """

    initial_capital: float
    equity: NDArray[np.float64]
    final_capital: float
    position: NDArray[np.float64]
    trades: tuple[Trade, ...]
    commission: float
    tax: float
    slippage: float
    funding: float
    borrow: float
    traded: float

    @property
    def returns(self) -> NDArray[np.float64]:
        """Return of each bar: its equity over the previous one's (the first, over capital)."""
        previous = np.concatenate(([self.initial_capital], self.equity[:-1]))
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(previous != 0, self.equity / previous - 1.0, 0.0)

    @property
    def bars_in_market(self) -> int:
        """Bars that closed with a position open."""
        return int(np.count_nonzero(self.position))

    @property
    def turnover(self) -> float:
        """Notional traded over the initial capital."""
        return self.traded / self.initial_capital if self.initial_capital else 0.0


@dataclass
class _Book:
    """The state the simulation carries from bar to bar."""

    capital: float
    costs: CostModel
    risk: RiskModel | None
    sizing: SizingModel
    conviction: NDArray[np.float64] | None
    atr: NDArray[np.float64] | None
    position: float = 0.0
    side: int = 0
    entry_price: float = 0.0
    entry_fill: float = 0.0
    entry_index: int = 0
    notional: float = 0.0
    favourable: float = 0.0
    entry_atr: float | None = None
    open_commission: float = 0.0
    open_tax: float = 0.0
    open_slippage: float = 0.0
    carry: float = 0.0
    trades: list[Trade] = field(default_factory=list)
    commission: float = 0.0
    tax: float = 0.0
    slippage: float = 0.0
    funding: float = 0.0
    borrow: float = 0.0
    traded: float = 0.0

    @property
    def in_trade(self) -> bool:
        return self.side != 0

    def _size(self, bar: int) -> float:
        """Notional of a new position (the capital is the equity: nothing is open)."""
        equity, sizing, risk = self.capital, self.sizing, self.risk
        if sizing.mode is SizingMode.CONVICTION:
            weight = sizing.fraction
            if self.conviction is not None and np.isfinite(self.conviction[bar]):
                weight = float(self.conviction[bar])
            notional = equity * weight
        elif sizing.mode is SizingMode.FRACTION:
            notional = equity * sizing.fraction
        elif sizing.mode is SizingMode.RISK and risk is not None and risk.stop_loss_pct:
            notional = sizing.risk_pct * equity / risk.stop_loss_pct
        else:
            notional = equity
        return max(0.0, min(notional, equity))

    def _start(self, bar: int, side: int, price: float, fill: float, notional: float) -> None:
        self.side = side
        self.entry_price = float(price)
        self.entry_fill = fill
        self.entry_index = bar
        self.notional = notional
        self.favourable = float(price)
        atr = self.atr
        valid = atr is not None and np.isfinite(atr[bar]) and atr[bar] > 0
        self.entry_atr = float(atr[bar]) if valid and atr is not None else None
        self.carry = 0.0
        self.traded += notional

    def buy(self, bar: int, price: float) -> None:
        """Open a long at ``price``: the commission and the tax come out of the notional."""
        notional = self._size(bar)
        fee = self.costs.commission(notional)
        bought = (notional - fee) / (1.0 + self.costs.tax_rate)
        if notional <= 0 or bought <= 0:
            return  # nothing to invest, or a minimum commission larger than the order
        fill = price * (1.0 + self.costs.slippage_rate)
        tax = bought * self.costs.tax_rate
        self.position = bought / fill if fill > 0 else 0.0
        self.capital -= notional
        self.open_commission, self.open_tax = fee, tax
        self.open_slippage = (fill - price) * self.position
        self._start(bar, Side.LONG, price, fill, notional)

    def short(self, bar: int, price: float) -> None:
        """Open a short at ``price``: sell borrowed units and keep the proceeds in cash."""
        notional = self._size(bar)
        fee = self.costs.commission(notional)
        if notional <= 0 or fee >= notional:
            return
        fill = price * (1.0 - self.costs.slippage_rate)  # a seller receives less
        self.position = -(notional / fill) if fill > 0 else 0.0
        self.capital += notional - fee
        self.open_commission, self.open_tax = fee, 0.0
        self.open_slippage = (price - fill) * -self.position
        self._start(bar, Side.SHORT, price, fill, notional)

    def close(self, bar: int, price: float, reason: ExitReason) -> None:
        """Close the open position at ``price``, whichever its side."""
        rate = self.costs.slippage_rate
        if self.side > 0:
            fill = price * (1.0 - rate)
            gross = self.position * fill
            fee = self.costs.commission(gross)
            tax = 0.0
            self.capital += gross - fee
            pnl = gross - fee - self.carry - self.notional
            slipped = (price - fill) * self.position
        else:
            units = -self.position
            fill = price * (1.0 + rate)  # a buyer pays more
            gross = units * fill
            fee = self.costs.commission(gross)
            tax = gross * self.costs.tax_rate
            self.capital -= gross + fee + tax
            pnl = self.notional - self.open_commission - gross - fee - tax - self.carry
            slipped = (fill - price) * units
        self.trades.append(
            Trade(
                side=Side(self.side),
                entry_index=self.entry_index,
                exit_index=bar,
                entry_price=self.entry_price,
                entry_fill=self.entry_fill,
                exit_fill=float(fill),
                quantity=abs(self.position),
                notional=self.notional,
                pnl=float(pnl),
                commission=self.open_commission + fee,
                tax=self.open_tax + tax,
                slippage=self.open_slippage + slipped,
                carry=self.carry,
                exit_reason=reason,
            )
        )
        self.commission += self.open_commission + fee
        self.tax += self.open_tax + tax
        self.slippage += self.open_slippage + slipped
        self.traded += gross
        self.position, self.side = 0.0, 0

    def barrier(self, risk: RiskModel, high: float, low: float) -> tuple[float, ExitReason] | None:
        """The stop or target the bar touches, the stop first; ``None`` if neither."""
        if self.side > 0:
            return self._long_barrier(risk, high, low)
        return self._short_barrier(risk, high, low)

    def _long_barrier(
        self, risk: RiskModel, high: float, low: float
    ) -> tuple[float, ExitReason] | None:
        entry, atr = self.entry_price, self.entry_atr
        if risk.trailing_stop_pct is not None:
            self.favourable = max(self.favourable, high)
        stops = [
            (entry * (1.0 - risk.stop_loss_pct), ExitReason.STOP_LOSS)
            if risk.stop_loss_pct is not None
            else None,
            (self.favourable * (1.0 - risk.trailing_stop_pct), ExitReason.TRAILING_STOP)
            if risk.trailing_stop_pct is not None
            else None,
            (entry - risk.atr_stop_mult * atr, ExitReason.ATR_STOP)
            if risk.atr_stop_mult is not None and atr
            else None,
        ]
        targets = [
            entry * (1.0 + risk.take_profit_pct) if risk.take_profit_pct is not None else None,
            entry + risk.atr_target_mult * atr
            if risk.atr_target_mult is not None and atr
            else None,
        ]
        stop = _tightest([s for s in stops if s is not None], highest=True)
        target = _nearest([t for t in targets if t is not None], lowest=True)
        if stop is not None and low <= stop[0]:
            return stop
        if target is not None and high >= target:
            return target, ExitReason.TAKE_PROFIT
        return None

    def _short_barrier(
        self, risk: RiskModel, high: float, low: float
    ) -> tuple[float, ExitReason] | None:
        entry, atr = self.entry_price, self.entry_atr
        if risk.trailing_stop_pct is not None:
            self.favourable = min(self.favourable, low)  # a short's best is the lowest
        stops = [
            (entry * (1.0 + risk.stop_loss_pct), ExitReason.STOP_LOSS)
            if risk.stop_loss_pct is not None
            else None,
            (self.favourable * (1.0 + risk.trailing_stop_pct), ExitReason.TRAILING_STOP)
            if risk.trailing_stop_pct is not None
            else None,
            (entry + risk.atr_stop_mult * atr, ExitReason.ATR_STOP)
            if risk.atr_stop_mult is not None and atr
            else None,
        ]
        targets = [
            entry * (1.0 - risk.take_profit_pct) if risk.take_profit_pct is not None else None,
            entry - risk.atr_target_mult * atr
            if risk.atr_target_mult is not None and atr
            else None,
        ]
        stop = _tightest([s for s in stops if s is not None], highest=False)
        target = _nearest([t for t in targets if t is not None], lowest=False)
        if stop is not None and high >= stop[0]:
            return stop
        if target is not None and low <= target:
            return target, ExitReason.TAKE_PROFIT
        return None

    def charge(self, close: float, funding: float, borrow: float) -> None:
        """Funding and borrow of the open position, on its value at this close."""
        if funding and np.isfinite(funding):
            paid = self.position * close * funding  # negative position: a short receives
            self.capital -= paid
            self.funding += paid
            self.carry += paid
        if self.side < 0 and borrow and np.isfinite(borrow):
            paid = -self.position * close * borrow
            self.capital -= paid
            self.borrow += paid
            self.carry += paid


def _tightest(
    candidates: list[tuple[float, ExitReason]], *, highest: bool
) -> tuple[float, ExitReason] | None:
    """The binding stop: the one touched first (the highest for a long, lowest for a short).

    On a tie the earlier candidate wins: fixed stop, then trailing, then ATR.
    """
    best: tuple[float, ExitReason] | None = None
    for price, reason in candidates:
        if best is None or (price > best[0] if highest else price < best[0]):
            best = (price, reason)
    return best


def _nearest(candidates: list[float], *, lowest: bool) -> float | None:
    """The binding target: the one touched first (the lowest for a long, highest for a short)."""
    best: float | None = None
    for price in candidates:
        if best is None or (price < best if lowest else price > best):
            best = price
    return best


def _array(values: ArrayLike, n: int, name: str) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=np.float64)
    if array.shape != (n,):
        msg = f"{name} has {array.shape[0] if array.ndim else 0} values for {n} bars"
        raise ValueError(msg)
    return array


def _signals(values: ArrayLike | None, n: int, name: str) -> NDArray[np.int8]:
    if values is None:
        return np.zeros(n, dtype=np.int8)
    array = _array(values, n, name)
    if not np.isfinite(array).all() or not set(np.unique(array)) <= _SIGNAL_VALUES:
        msg = f"{name} must be 1 (open), -1 (close) or 0 (hold) on every bar"
        raise ValueError(msg)
    return array.astype(np.int8)


def simulate(  # noqa: PLR0912, PLR0915 - one loop over the bars, as in CryptoWorld
    open_: ArrayLike,
    high: ArrayLike,
    low: ArrayLike,
    close: ArrayLike,
    signals: ArrayLike,
    *,
    short_signals: ArrayLike | None = None,
    initial_capital: float = 10_000.0,
    costs: CostModel | None = None,
    risk: RiskModel | None = None,
    sizing: SizingModel | None = None,
    atr: ArrayLike | None = None,
    conviction: ArrayLike | None = None,
    funding: ArrayLike | None = None,
    borrow: ArrayLike | None = None,
    fill_next_bar: bool = True,
) -> Simulation:
    """Simulate one instrument's signals bar by bar.

    Args:
        open_: Open of each bar: where the orders of the previous bar's signals fill.
        high: High of each bar: where a short's stop or a long's target is touched.
        low: Low of each bar: where a long's stop or a short's target is touched.
        close: Close of each bar: where the equity is measured.
        signals: The long side: ``1`` opens, ``-1`` closes, ``0`` holds.
        short_signals: The short side, the same way (no shorts if ``None``).
        initial_capital: Equity before the first bar.
        costs: Commission, slippage and tax of each order (none by default).
        risk: Stops, targets and exit by time (none by default).
        sizing: How large each position is (all the equity by default).
        atr: ATR of each bar, for barriers in ATRs.
        conviction: Fraction of the equity of an entry filled at each bar, for
            ``conviction`` sizing (``NaN``: the sizing's ``fraction``). Keyed by the bar the
            order fills at, as CryptoWorld's: the signal of bar ``s`` reads ``conviction[s+1]``.
        funding: Funding rate of each bar (positive: longs pay).
        borrow: Borrow fee of each bar for a short (a decimal of its value).
        fill_next_bar: Fill at the next open (``True``) or, optimistically, at the close that
            gave the signal: only to compare with engines that did.

    Raises:
        ValueError: If the arrays have different lengths or a signal is not -1, 0 or 1.
    """
    closes = np.asarray(close, dtype=np.float64)
    n = closes.shape[0]
    opens = _array(open_, n, "open")
    highs, lows = _array(high, n, "high"), _array(low, n, "low")
    longs, shorts = _signals(signals, n, "signals"), _signals(short_signals, n, "short_signals")
    funding_rates = None if funding is None else _array(funding, n, "funding")
    borrow_rates = None if borrow is None else _array(borrow, n, "borrow")
    barriers = risk if risk is not None and risk.active else None
    book = _Book(
        capital=float(initial_capital),
        costs=costs or NO_COSTS,
        risk=risk,
        sizing=sizing or SizingModel(),
        conviction=None if conviction is None else _array(conviction, n, "conviction"),
        atr=None if atr is None else _array(atr, n, "atr"),
    )
    equity = np.empty(n, dtype=np.float64)
    position = np.empty(n, dtype=np.float64)
    pending = 0  # the order the previous bar's signal left for this bar's open

    for i in range(n):
        exited = False
        # An order left by the previous bar: nothing can have changed since its signal, so an
        # entry finds the book flat and an exit finds its position open.
        if pending == _ENTER_LONG:
            book.buy(i, float(opens[i]))
        elif pending == _ENTER_SHORT:
            book.short(i, float(opens[i]))
        elif pending == _EXIT:
            book.close(i, float(opens[i]), ExitReason.SIGNAL)
            exited = True
        pending = 0

        if book.in_trade and barriers is not None and i > book.entry_index:
            hit = book.barrier(barriers, float(highs[i]), float(lows[i]))
            if hit is not None:
                book.close(i, hit[0], hit[1])
                exited = True

        if (
            not exited
            and book.in_trade
            and barriers is not None
            and barriers.max_bars is not None
            and i - book.entry_index >= barriers.max_bars
        ):
            price = float(opens[i]) if fill_next_bar else float(closes[i])
            book.close(i, price, ExitReason.TIME_EXIT)
            exited = True

        if not exited:
            order = 0
            if (book.in_trade and book.side > 0 and longs[i] == _EXIT) or (
                book.in_trade and book.side < 0 and shorts[i] == _EXIT
            ):
                order = _EXIT
            elif not book.in_trade and longs[i] == 1:
                order = _ENTER_LONG
            elif not book.in_trade and shorts[i] == 1:
                order = _ENTER_SHORT
            if order and fill_next_bar:
                pending = order
            elif order == _EXIT:
                book.close(i, float(closes[i]), ExitReason.SIGNAL)
            elif order == _ENTER_LONG:
                book.buy(i, float(closes[i]))
            elif order == _ENTER_SHORT:
                book.short(i, float(closes[i]))

        if book.in_trade:
            book.charge(
                float(closes[i]),
                0.0 if funding_rates is None else float(funding_rates[i]),
                0.0 if borrow_rates is None else float(borrow_rates[i]),
            )
        equity[i] = book.capital + (book.position * float(closes[i]) if book.in_trade else 0.0)
        position[i] = book.position if book.in_trade else 0.0

    if book.in_trade:
        book.close(n - 1, float(closes[-1]), ExitReason.END_OF_DATA)

    return Simulation(
        initial_capital=float(initial_capital),
        equity=equity,
        final_capital=book.capital,
        position=position,
        trades=tuple(book.trades),
        commission=book.commission,
        tax=book.tax,
        slippage=book.slippage,
        funding=book.funding,
        borrow=book.borrow,
        traded=book.traded,
    )
