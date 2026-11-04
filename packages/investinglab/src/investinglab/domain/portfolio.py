"""Investment portfolios: holdings, weights and rebalancing policy."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Unpack

import numpy as np
import pandas as pd

from investinglab.analytics import (
    correlation_from_covariance,
    covariance_matrix,
    drawdown,
    drawdown_episodes,
    effective_number_of_assets,
    herfindahl_index,
    rebalanced_path,
    risk_contributions,
)
from investinglab.domain.errors import DomainError, InvalidPortfolioError
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS, RiskMetrics
from investinglab.domain.optimization import (
    EfficientFrontier,
    Estimates,
    Objective,
    OptimizationConfig,
    OptimizationInputs,
    OptimizationResult,
    OptimizationSettings,
    estimate,
    frontier_points,
    solve,
)
from investinglab.domain.panel import AlignedPanel, AlignmentMethod, align
from investinglab.domain.simulation import (
    SimulationConfig,
    SimulationInputs,
    SimulationResult,
    simulate,
)
from investinglab.domain.time import CALENDAR_YEAR_DAYS, Frequency

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from investinglab.domain.money import Currency
    from investinglab.domain.series import PriceSeries
    from investinglab.reporting.entrypoints import (
        MarkdownReport,
        PlotsReport,
        ReportOptions,
        ReportSettings,
    )

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

    def drawdown_episodes(self, top: int | None = 5) -> pd.DataFrame:
        """Deepest peak-to-recovery episodes of the portfolio value."""
        return drawdown_episodes(self._values, top=top)


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


MIN_UNION_YEARS: Final = 1.0
"""History needed before a multi-market daily portfolio annualises with its union calendar."""


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

    The portfolio is immutable, so its derived history (aligned panel, backtests) is
    computed once and reused by reports, charts and metrics.

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
    _memo: dict[tuple[object, ...], object] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

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
        key = ("aligned", AlignmentMethod(method))
        panel = self._memo.get(key)
        if not isinstance(panel, AlignedPanel):
            panel = self._memo[key] = align(self.series, method)
        return panel

    @property
    def periods_per_year(self) -> float:
        """Annualisation factor of the portfolio's return calendar.

        The portfolio is valued on the union of its holdings' calendars. On one market,
        that is the market's schedule (252 equity sessions, 365 crypto days...). Daily
        holdings on several markets trade on more dates than any of them, because a Madrid
        holiday can be a New York session: with at least :data:`MIN_UNION_YEARS` of common
        history, the factor is the density observed on the union calendar, never below
        the densest schedule.
        """
        schedule = max(h.series.periods_per_year for h in self.holdings)
        markets = {(h.series.instrument.exchange, h.series.timezone) for h in self.holdings}
        if self.frequency is not Frequency.DAY_1 or len(markets) < 2:  # noqa: PLR2004
            return schedule
        panel = self.aligned()
        dates = panel.index[panel.index >= panel.common_start()]
        years = (dates[-1] - dates[0]).days / CALENDAR_YEAR_DAYS
        if years < MIN_UNION_YEARS:
            return schedule
        return max(schedule, (len(dates) - 1) / years)

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
        key = ("backtest", float(initial_value), AlignmentMethod(method))
        cached = self._memo.get(key)
        if isinstance(cached, PortfolioBacktest):
            return cached
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
        backtest = PortfolioBacktest(
            _returns=path.returns,
            _values=path.values,
            _weights=path.weights,
            _turnover=path.turnover,
            _staleness=panel.staleness().loc[start:],
            rebalance_dates=path.rebalanced,
        )
        self._memo[key] = backtest
        return backtest

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
            risk_free_rate: Effective annual risk-free rate (decimal), constant or
                point-in-time series (see :class:`~investinglab.domain.RateConvention`).
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

    # ── Simulation ───────────────────────────────────────────────────

    def monte_carlo(self, config: SimulationConfig | None = None) -> SimulationResult:
        """Simulate the portfolio's future value (B1-T1 §4.4).

        Asset returns are simulated jointly (correlations included) and the portfolio's
        own rebalancing policy is applied inside every path. See
        :class:`~investinglab.domain.simulation.SimulationConfig` for the parameters.

        Examples:
            >>> result = portfolio.monte_carlo(SimulationConfig(n_paths=10_000, horizon=252))
            >>> result.value_at_risk(0.95)
            >>> result.plot()
        """
        settings = config or SimulationConfig()
        panel = self.aligned()
        prices = panel.prices.loc[panel.common_start() :]
        rebalance_every, band = self._simulation_rebalancing()
        inputs = SimulationInputs(
            prices=prices,
            weights=self.weights.reindex([str(c) for c in prices.columns]).to_numpy(),
            periods_per_year=self.periods_per_year,
            rebalance_every=rebalance_every,
            band=band,
            start=pd.Timestamp(prices.index[-1]),
        )
        return simulate(inputs, settings)

    # ── Optimisation (ADR-0023) ──────────────────────────────────────

    def with_weights(self, weights: Mapping[str, float], *, name: str | None = None) -> Portfolio:
        """The same holdings with other target weights (same currency and rebalancing).

        Raises:
            InvalidPortfolioError: If the weights miss a holding, name an unknown symbol or
                do not sum to 1.
        """
        return Portfolio.from_weights(
            name or self.name,
            self.series,
            weights,
            base_currency=self.base_currency,
            rebalance=self.rebalance,
            allow_short=self.allow_short or any(weight < 0 for weight in weights.values()),
        )

    def optimize(
        self,
        config: OptimizationConfig | None = None,
        **settings: Unpack[OptimizationSettings],
    ) -> OptimizationResult:
        """Weights that best meet an objective, estimated from the holdings' history.

        Pass an :class:`~investinglab.domain.optimization.OptimizationConfig` and/or override
        any of its fields as keywords.

        Raises:
            DomainError: If the configuration is invalid, the history too short or the
                problem infeasible.

        Examples:
            >>> portfolio.optimize(objective="max_sharpe", max_weight=0.4).weights
            >>> portfolio.optimize(objective="risk_parity").portfolio.report()
        """
        resolved = replace(config or OptimizationConfig(), **settings)  # type: ignore[arg-type]
        estimates = estimate(self._optimization_inputs(resolved), resolved)
        return self._optimization_result(resolved, estimates, solve(estimates, resolved))

    def efficient_frontier(
        self,
        config: OptimizationConfig | None = None,
        *,
        points: int = 30,
        **settings: Unpack[OptimizationSettings],
    ) -> EfficientFrontier:
        """The minimum-variance frontier, from the global minimum to the highest return.

        The objective is ignored; estimators, views and weight bounds are used as given.

        Raises:
            DomainError: If the inputs cannot be estimated or the bounds are infeasible.
        """
        resolved = replace(config or OptimizationConfig(), **settings)  # type: ignore[arg-type]
        minimum_config = replace(resolved, objective=Objective.MIN_VARIANCE, target_return=None)
        estimates = estimate(self._optimization_inputs(minimum_config), minimum_config)
        minimum = self._optimization_result(
            minimum_config, estimates, solve(estimates, minimum_config)
        )
        sharpe_config = replace(minimum_config, objective=Objective.MAX_SHARPE)
        try:
            best: OptimizationResult | None = self._optimization_result(
                sharpe_config, estimates, solve(estimates, sharpe_config)
            )
        except DomainError:
            best = None  # no portfolio expects more than the risk-free rate
        return EfficientFrontier(
            config=minimum_config,
            estimates=estimates,
            points=frontier_points(estimates, minimum_config, points),
            minimum_variance=minimum,
            maximum_sharpe=best,
        )

    def _optimization_inputs(self, config: OptimizationConfig) -> OptimizationInputs:
        frequency = config.frequency or self.frequency
        returns = self.asset_returns(frequency)
        common = returns.notna().cummax().all(axis=1)  # every holding has started trading
        periods = max(h.series.instrument.schedule.periods_per_year(frequency) for h in self)
        return OptimizationInputs(
            returns=returns.loc[common], weights=self.weights, periods_per_year=periods
        )

    def _optimization_result(
        self, config: OptimizationConfig, estimates: Estimates, weights: np.ndarray
    ) -> OptimizationResult:
        optimised = dict(zip(estimates.symbols, weights.tolist(), strict=True))
        return OptimizationResult(
            config=config,
            portfolio=self.with_weights(optimised),
            estimates=estimates,
            previous_weights=self.weights,
        )

    # ── Reports (B1-T1 §4.5) ─────────────────────────────────────────

    def report(
        self, options: ReportOptions | None = None, **settings: Unpack[ReportSettings]
    ) -> MarkdownReport:
        """Markdown report of the portfolio (B1-T1 §4.5).

        Sections: composition, return and risk, comparison with every holding over the
        common period, tail risk, correlations, risk contributions, rebalancing, drawdowns,
        calendars and valuation, Monte Carlo when requested, data quality, diagnostics and
        methodology.

        The text is bilingual (``language="es"`` by default, ``"en"`` available) and is an
        ordinary ``str`` that notebooks render as formatted Markdown.

        Args:
            options: Report options (:class:`~investinglab.reporting.options.ReportOptions`).
            **settings: Any option by name, overriding ``options``.

        Examples:
            >>> portfolio.report(language="en", risk_free_rate=0.03).save("report.md")
        """
        # Lazy, documented exception to the layering (ADR-0017): presentation lives in reporting.
        from investinglab.reporting.entrypoints import portfolio_report  # noqa: PLC0415

        return portfolio_report(self, options, **settings)

    def plots_report(
        self, options: ReportOptions | None = None, **settings: Unpack[ReportSettings]
    ) -> PlotsReport:
        """Charts of the portfolio: growth, drawdown, correlations, risk and weights.

        Growth versus every holding, drawdown, correlation heatmap, weight versus risk
        contribution and effective weights against their targets. Needs the ``plots``
        extra. Returns a :class:`~investinglab.reporting.plots.PlotsReport`: a mapping of
        named matplotlib figures that can be saved with ``save(directory)``.

        Examples:
            >>> portfolio.plots_report(language="en").save("charts/")
        """
        from investinglab.reporting.entrypoints import portfolio_plots  # noqa: PLC0415

        return portfolio_plots(self, options, **settings)

    def _simulation_rebalancing(self) -> tuple[int | None, float | None]:
        policy = self.rebalance
        if policy.kind is RebalanceKind.THRESHOLD:
            return None, policy.band
        if policy.kind is RebalanceKind.BUY_AND_HOLD or policy.frequency is None:
            return None, None
        densest = max(self.holdings, key=lambda h: h.series.periods_per_year).series
        per_rebalance = densest.instrument.schedule.periods_per_year(policy.frequency)
        return max(1, round(self.periods_per_year / per_rebalance)), None

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
