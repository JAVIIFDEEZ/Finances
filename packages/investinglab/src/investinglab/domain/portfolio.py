"""Investment portfolios: holdings, weights and rebalancing policy."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics import (
    correlation_from_covariance,
    covariance_matrix,
    drawdown,
    effective_number_of_assets,
    herfindahl_index,
    rebalanced_path,
    risk_contributions,
)
from investinglab.domain.errors import DomainError, InvalidPortfolioError
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS, RiskMetrics
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
    "PortfolioBacktest",
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


_PERIOD_ALIASES: Final[dict[Frequency, str]] = {
    Frequency.WEEK_1: "W-SUN",
    Frequency.MONTH_1: "M",
    Frequency.QUARTER_1: "Q",
    Frequency.YEAR_1: "Y",
}


@dataclass(frozen=True, slots=True, eq=False)
class PortfolioBacktest:
    """Historical path of a portfolio under its rebalancing policy.

    Values use the last *observed* price of each holding (mark-to-market, ADR-0008);
    :attr:`staleness` tells how many periods old each holding's mark is.
    """

    _returns: pd.Series = field(repr=False)
    _values: pd.Series = field(repr=False)
    _weights: pd.DataFrame = field(repr=False)
    _turnover: pd.Series = field(repr=False)
    _staleness: pd.DataFrame = field(repr=False)
    rebalance_dates: pd.DatetimeIndex = field(repr=False)

    @property
    def returns(self) -> pd.Series:
        """Portfolio return per period."""
        return self._returns.copy(deep=False)

    @property
    def values(self) -> pd.Series:
        """Portfolio value per period, starting at the initial value."""
        return self._values.copy(deep=False)

    @property
    def weights(self) -> pd.DataFrame:
        """Weights held at the end of each period (after any rebalancing)."""
        return self._weights.copy(deep=False)

    @property
    def turnover(self) -> pd.Series:
        """One-way turnover traded at each period."""
        return self._turnover.copy(deep=False)

    @property
    def staleness(self) -> pd.DataFrame:
        """Age, in periods, of each holding's last observed price."""
        return self._staleness.copy(deep=False)

    @property
    def total_turnover(self) -> float:
        """Sum of the one-way turnover over the whole period."""
        return float(self._turnover.sum())

    @property
    def start(self) -> pd.Timestamp:
        """First date of the backtest (every holding observed at least once)."""
        return pd.Timestamp(self._values.index[0])

    @property
    def end(self) -> pd.Timestamp:
        """Last date of the backtest."""
        return pd.Timestamp(self._values.index[-1])

    def drawdown(self) -> pd.Series:
        """Decline of the portfolio value from its running peak."""
        return drawdown(self._values)


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

    @property
    def periods_per_year(self) -> float:
        """Annualisation factor: the densest holding's (the union calendar is at least as dense)."""
        return max(h.series.periods_per_year for h in self.holdings)

    @property
    def herfindahl_index(self) -> float:
        """Concentration of the target weights (1 = single asset, 1/n = equal weights)."""
        return herfindahl_index(self.weights.to_numpy())

    @property
    def effective_number_of_assets(self) -> float:
        """How many equally weighted assets the portfolio is equivalent to."""
        return effective_number_of_assets(self.weights.to_numpy())

    # ── History ──────────────────────────────────────────────────────

    def backtest(
        self,
        *,
        initial_value: float = 1.0,
        method: AlignmentMethod | str = AlignmentMethod.UNION,
    ) -> PortfolioBacktest:
        """Value the portfolio through history under its rebalancing policy.

        The path starts at the first date on which every holding has been observed.

        Args:
            initial_value: Portfolio value at the start date.
            method: Calendar alignment (union keeps every observation).
        """
        if not initial_value > 0:
            raise DomainError("initial_value must be positive")
        panel = self.aligned(method)
        start = panel.common_start()
        returns = panel.returns.loc[start:]
        policy = self.rebalance
        path = rebalanced_path(
            returns,
            self.weights.to_numpy(),
            rebalance_dates=self._rebalance_dates(pd.DatetimeIndex(returns.index)),
            band=policy.band if policy.kind is RebalanceKind.THRESHOLD else None,
            initial_value=initial_value,
        )
        return PortfolioBacktest(
            _returns=path.returns,
            _values=path.values,
            _weights=path.weights,
            _turnover=path.turnover,
            _staleness=panel.staleness().loc[start:],
            rebalance_dates=path.rebalanced,
        )

    def returns(self) -> pd.Series:
        """Historical portfolio returns under the rebalancing policy."""
        return self.backtest().returns

    def value_history(self, initial_value: float = 1.0) -> pd.Series:
        """Historical portfolio value under the rebalancing policy."""
        return self.backtest(initial_value=initial_value).values

    def metrics(
        self,
        *,
        risk_free_rate: float | pd.Series = 0.0,
        levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS,
    ) -> RiskMetrics:
        """Performance and risk metrics of the historical portfolio returns.

        Args:
            risk_free_rate: Annual risk-free rate (decimal), constant or point-in-time series.
            levels: Confidence levels for VaR and CVaR.
        """
        return RiskMetrics.from_returns(
            self.returns(),
            periods_per_year=self.periods_per_year,
            risk_free_rate=risk_free_rate,
            levels=levels,
        )

    # ── Co-movement and risk decomposition ───────────────────────────

    def asset_returns(self, frequency: Frequency | str | None = None) -> pd.DataFrame:
        """Holdings' returns on their own calendars, joined (NaN = not observed).

        Args:
            frequency: Optional coarser frequency (e.g. weekly) to resample each holding
                first. Weekly returns reduce the bias of non-synchronous closes between
                markets (Europe closes hours before the United States).
        """
        series = self.series
        if frequency is not None and Frequency(frequency) != self.frequency:
            series = tuple(s.resample(frequency) for s in series)
        return align(series).returns.iloc[1:]

    def covariance(self, frequency: Frequency | str | None = None) -> pd.DataFrame:
        """Covariance of holdings' returns (pairwise-complete, PSD-repaired), per period."""
        return covariance_matrix(self.asset_returns(frequency))

    def correlation(self, frequency: Frequency | str | None = None) -> pd.DataFrame:
        """Correlation of holdings' returns consistent with :meth:`covariance`."""
        return correlation_from_covariance(self.covariance(frequency))

    def risk_contributions(self, frequency: Frequency | str | None = None) -> pd.DataFrame:
        """Contribution of each holding to the portfolio volatility (Euler decomposition).

        Columns: ``weight``, ``marginal``, ``contribution`` and ``share`` (per period) plus
        ``annualized_contribution``. Shares sum to 1.
        """
        covariance = self.covariance(frequency)
        table = risk_contributions(self.weights.to_numpy(), covariance.to_numpy())
        table.index = pd.Index(self.symbols, name="symbol")
        target = Frequency(frequency) if frequency is not None else self.frequency
        periods = max(h.series.instrument.schedule.periods_per_year(target) for h in self)
        table["annualized_contribution"] = table["contribution"] * np.sqrt(periods)
        return table

    def _rebalance_dates(self, index: pd.DatetimeIndex) -> pd.DatetimeIndex | None:
        policy = self.rebalance
        if policy.kind is not RebalanceKind.PERIODIC or policy.frequency is None:
            return None
        if policy.frequency is Frequency.DAY_1 and not self.frequency.is_intraday:
            return index[1:-1]
        labels = index.tz_localize(None) if index.tz is not None else index
        sessions = labels.normalize()
        keys: pd.Index
        if policy.frequency is Frequency.DAY_1:
            keys = pd.Index(sessions)
        else:
            keys = pd.Index(sessions.to_period(_PERIOD_ALIASES[policy.frequency]))
        last_in_period = pd.Series(index, index=index).groupby(keys.to_numpy()).max()
        return pd.DatetimeIndex(last_in_period.to_numpy()).difference(index[-1:])

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
