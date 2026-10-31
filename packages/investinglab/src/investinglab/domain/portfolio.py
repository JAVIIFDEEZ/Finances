"""Investment portfolios: holdings, weights and rebalancing policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import pandas as pd

from investinglab.domain.errors import DomainError, InvalidPortfolioError
from investinglab.domain.panel import AlignedPanel, AlignmentMethod, align
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from investinglab.domain.money import Currency
    from investinglab.domain.series import PriceSeries

__all__ = [
    "WEIGHT_TOLERANCE",
    "Holding",
    "Portfolio",
    "RebalanceKind",
    "RebalancePolicy",
]

WEIGHT_TOLERANCE: Final = 1e-6
"""Maximum accepted deviation of the sum of weights from 1."""


class RebalanceKind(StrEnum):
    """How a portfolio returns to its target weights."""

    BUY_AND_HOLD = "buy_and_hold"
    PERIODIC = "periodic"
    THRESHOLD = "threshold"


_REBALANCE_FREQUENCIES: Final = frozenset(
    {Frequency.DAY_1, Frequency.WEEK_1, Frequency.MONTH_1, Frequency.QUARTER_1, Frequency.YEAR_1}
)


@dataclass(frozen=True, slots=True)
class RebalancePolicy:
    """Rebalancing rule, applied identically to historical analysis and simulation.

    Prefer the constructors :meth:`buy_and_hold`, :meth:`periodic` and :meth:`threshold`.

    Attributes:
        kind: Rebalancing rule.
        frequency: Calendar frequency for ``PERIODIC`` rebalancing.
        band: Maximum absolute drift of any weight before rebalancing, for ``THRESHOLD``.
    """

    kind: RebalanceKind
    frequency: Frequency | None = None
    band: float | None = None

    def __post_init__(self) -> None:
        if self.kind is RebalanceKind.PERIODIC:
            if self.frequency not in _REBALANCE_FREQUENCIES:
                allowed = sorted(f.value for f in _REBALANCE_FREQUENCIES)
                raise DomainError(f"Periodic rebalancing needs a frequency in {allowed}")
            if self.band is not None:
                raise DomainError("Periodic rebalancing does not take a band")
        elif self.kind is RebalanceKind.THRESHOLD:
            if self.band is None or not 0 < self.band < 1:
                raise DomainError("Threshold rebalancing needs a band in (0, 1)")
            if self.frequency is not None:
                raise DomainError("Threshold rebalancing does not take a frequency")
        elif self.frequency is not None or self.band is not None:
            raise DomainError("Buy-and-hold takes neither frequency nor band")

    @classmethod
    def buy_and_hold(cls) -> RebalancePolicy:
        """Never rebalance: weights drift with prices."""
        return cls(RebalanceKind.BUY_AND_HOLD)

    @classmethod
    def periodic(cls, frequency: Frequency | str = Frequency.MONTH_1) -> RebalancePolicy:
        """Rebalance to target weights at the end of every calendar period."""
        return cls(RebalanceKind.PERIODIC, frequency=Frequency(frequency))

    @classmethod
    def threshold(cls, band: float) -> RebalancePolicy:
        """Rebalance when any weight drifts more than ``band`` from its target."""
        return cls(RebalanceKind.THRESHOLD, band=band)

    def __str__(self) -> str:
        if self.kind is RebalanceKind.PERIODIC and self.frequency is not None:
            return f"periodic ({self.frequency.value})"
        if self.kind is RebalanceKind.THRESHOLD:
            return f"threshold (±{self.band:.1%})"
        return "buy and hold"


@dataclass(frozen=True, slots=True)
class Holding:
    """A position in a portfolio: a price series and its target weight."""

    series: PriceSeries
    weight: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight):
            raise DomainError(f"Weight of {self.series.symbol} must be finite")

    @property
    def symbol(self) -> str:
        """Symbol of the held instrument."""
        return self.series.symbol


@dataclass(frozen=True, slots=True, eq=False)
class Portfolio:
    """A portfolio of instruments with validated target weights.

    Invariants (checked on construction, all problems reported together):

    * at least one holding and no duplicated symbols;
    * finite weights summing to 1 (within :data:`WEIGHT_TOLERANCE`);
    * no negative weights unless ``allow_short=True``;
    * every series has the same frequency;
    * every series is expressed in ``base_currency`` (convert foreign assets first; the
      conversion keeps currency risk inside the returns).

    Args:
        name: Portfolio name.
        holdings: Positions and target weights.
        base_currency: Currency in which the portfolio is valued.
        rebalance: Rebalancing policy (monthly by default).
        allow_short: Accept negative weights (short positions).
    """

    name: str
    holdings: tuple[Holding, ...]
    base_currency: Currency
    rebalance: RebalancePolicy = RebalancePolicy(RebalanceKind.PERIODIC, Frequency.MONTH_1)
    allow_short: bool = False

    def __post_init__(self) -> None:
        holdings = tuple(self.holdings)
        object.__setattr__(self, "holdings", holdings)
        problems: list[str] = []
        if not self.name.strip():
            problems.append("name must not be empty")
        if not holdings:
            problems.append("at least one holding is required")
        symbols = [h.symbol for h in holdings]
        duplicated = sorted({s for s in symbols if symbols.count(s) > 1})
        if duplicated:
            problems.append(f"duplicated symbols {duplicated}")
        total = math.fsum(h.weight for h in holdings)
        if holdings and abs(total - 1.0) > WEIGHT_TOLERANCE:
            problems.append(f"weights must sum to 1, got {total:.6f}")
        shorts = [h.symbol for h in holdings if h.weight < 0]
        if shorts and not self.allow_short:
            problems.append(f"negative weights for {shorts}; pass allow_short=True to allow them")
        frequencies = sorted({h.series.frequency.value for h in holdings})
        if len(frequencies) > 1:
            problems.append(f"mixed frequencies {frequencies}; resample to a common one")
        foreign = sorted(
            f"{h.symbol} ({h.series.currency})"
            for h in holdings
            if h.series.currency != self.base_currency
        )
        if foreign:
            problems.append(
                f"series not in base currency {self.base_currency}: {foreign}; "
                "convert them to the base currency first"
            )
        if problems:
            raise InvalidPortfolioError(self.name or "<unnamed>", problems)

    # ── Constructors ─────────────────────────────────────────────────

    @classmethod
    def from_weights(
        cls,
        name: str,
        series: Iterable[PriceSeries],
        weights: Mapping[str, float] | Sequence[float],
        *,
        base_currency: Currency | None = None,
        rebalance: RebalancePolicy | None = None,
        allow_short: bool = False,
    ) -> Portfolio:
        """Build a portfolio from series and weights.

        Args:
            name: Portfolio name.
            series: Price series of the holdings.
            weights: Either a mapping ``symbol -> weight`` or a sequence aligned with
                ``series``.
            base_currency: Defaults to the currency shared by all the series.
            rebalance: Defaults to monthly periodic rebalancing.
            allow_short: Accept negative weights.
        """
        items = list(series)
        if isinstance(weights, dict) or hasattr(weights, "keys"):
            mapping = dict(weights)
            missing = [s.symbol for s in items if s.symbol not in mapping]
            unknown = sorted(set(mapping) - {s.symbol for s in items})
            if missing or unknown:
                raise InvalidPortfolioError(
                    name, [f"weights missing for {missing}, unknown symbols {unknown}"]
                )
            values = [float(mapping[s.symbol]) for s in items]
        else:
            values = [float(w) for w in weights]
            if len(values) != len(items):
                raise InvalidPortfolioError(
                    name, [f"{len(values)} weights for {len(items)} series"]
                )
        if base_currency is None:
            currencies = {s.currency for s in items}
            if len(currencies) != 1:
                raise InvalidPortfolioError(
                    name,
                    [
                        (
                            f"series use several currencies {sorted(map(str, currencies))}; "
                            "pass base_currency and convert the series"
                        )
                    ],
                )
            base_currency = currencies.pop()
        return cls(
            name=name,
            holdings=tuple(Holding(s, w) for s, w in zip(items, values, strict=True)),
            base_currency=base_currency,
            rebalance=rebalance or RebalancePolicy.periodic(Frequency.MONTH_1),
            allow_short=allow_short,
        )

    @classmethod
    def equal_weight(
        cls,
        name: str,
        series: Iterable[PriceSeries],
        *,
        base_currency: Currency | None = None,
        rebalance: RebalancePolicy | None = None,
    ) -> Portfolio:
        """Build a portfolio with the same weight on every series."""
        items = list(series)
        weight = 1.0 / len(items) if items else 0.0
        return cls.from_weights(
            name,
            items,
            [weight] * len(items),
            base_currency=base_currency,
            rebalance=rebalance,
        )

    # ── Accessors ────────────────────────────────────────────────────

    @property
    def symbols(self) -> tuple[str, ...]:
        """Symbols of the holdings, in order."""
        return tuple(h.symbol for h in self.holdings)

    @property
    def weights(self) -> pd.Series:
        """Target weights indexed by symbol."""
        return pd.Series([h.weight for h in self.holdings], index=list(self.symbols), name="weight")

    @property
    def frequency(self) -> Frequency:
        """Common frequency of the holdings."""
        return self.holdings[0].series.frequency

    @property
    def series(self) -> tuple[PriceSeries, ...]:
        """Price series of the holdings, in order."""
        return tuple(h.series for h in self.holdings)

    @property
    def gross_exposure(self) -> float:
        """Sum of absolute weights (1 for long-only portfolios)."""
        return math.fsum(abs(h.weight) for h in self.holdings)

    def aligned(self, method: AlignmentMethod | str = AlignmentMethod.UNION) -> AlignedPanel:
        """Holdings' prices and returns on a common time axis (no data is invented)."""
        return align(self.series, method)

    def __len__(self) -> int:
        return len(self.holdings)

    def __iter__(self) -> Iterator[Holding]:
        return iter(self.holdings)

    def __repr__(self) -> str:
        weights = ", ".join(f"{h.symbol}={h.weight:.2%}" for h in self.holdings)
        return (
            f"Portfolio({self.name!r}, [{weights}], base={self.base_currency}, "
            f"rebalance={self.rebalance})"
        )
