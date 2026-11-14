"""Translation of domain objects into response schemas (no business logic here).

Every figure the core computes is passed through as it is; the mappers only change its
shape (DataFrames to lists, timestamps to ISO dates) and turn undefined numbers (NaN) into
``null``, because JSON has no NaN.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab import __version__ as core_version
from investinglab.domain.flow import FlowField
from investinglab.domain.series import PriceField
from investinglab.ports import PortfolioSpec
from investinglab_api import __version__
from investinglab_api.schemas.analysis import (
    AssetPointOut,
    CalibrationOut,
    EstimateOut,
    FanPointOut,
    FrontierPointOut,
    HistogramBinOut,
    OptimizationOut,
    OptimizedOut,
    PlanFanPointOut,
    PlanOut,
    SimulationOut,
    WeightOut,
)
from investinglab_api.schemas.common import Matrix, Point, finite
from investinglab_api.schemas.economic import EconomicObservationOut, EconomicSeriesOut
from investinglab_api.schemas.market import (
    BarOut,
    CompareSeriesOut,
    ComparisonOut,
    ExchangeOut,
    FailureOut,
    FlowBarOut,
    FlowOut,
    FlowSummaryOut,
    IndicatorOut,
    InstrumentOut,
    IssueOut,
    MetricsOut,
    PatternEventOut,
    PatternOut,
    PatternsOut,
    QualityOut,
    RatePointOut,
    RatesOut,
    RatesSummaryOut,
    SeriesOut,
    SourceOut,
    StatsOut,
    TailRiskOut,
    TechnicalOut,
    UnavailableIndicatorOut,
    UnavailablePatternOut,
)
from investinglab_api.schemas.meta import (
    HealthOut,
    ModuleOut,
    ProviderOut,
    RateLimitOut,
    RequirementOut,
    RiskFreeOut,
)
from investinglab_api.schemas.portfolio import (
    DrawdownEpisodeOut,
    HoldingIn,
    HoldingOut,
    PortfolioAnalyticsOut,
    PortfolioIn,
    RebalanceIn,
    RiskContributionOut,
    SavedPortfolioOut,
    SavedPortfolioPage,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from investinglab.domain.economic import EconomicSeries
    from investinglab.domain.flow import FlowSeries
    from investinglab.domain.instruments import Instrument
    from investinglab.domain.metrics import RiskMetrics
    from investinglab.domain.optimization import EfficientFrontier, OptimizationResult
    from investinglab.domain.patterns import PricePatterns
    from investinglab.domain.planning import PlanResult
    from investinglab.domain.portfolio import Portfolio
    from investinglab.domain.quality import DataQualityReport
    from investinglab.domain.rate_series import RateSeries
    from investinglab.domain.series import DataSource, PriceSeries, SeriesStats
    from investinglab.domain.simulation import SimulationResult
    from investinglab.domain.technical import TechnicalIndicators
    from investinglab.modules import ModuleInfo
    from investinglab.ports import Page, ProviderCapabilities, Stored
    from investinglab.services import BatchResult

__all__ = [
    "comparison_out",
    "economic_series_out",
    "flow_out",
    "health_out",
    "metrics_out",
    "module_out",
    "optimization_out",
    "plan_out",
    "portfolio_analytics_out",
    "portfolio_spec",
    "provider_out",
    "quality_out",
    "rates_out",
    "risk_free_out",
    "saved_portfolio_out",
    "saved_portfolio_page",
    "series_out",
    "simulation_out",
    "technical_out",
]

ISSUE_EXAMPLES: Final = 10
"""Affected dates listed per data-quality issue."""
HISTOGRAM_BINS: Final = 40
"""Bins of the terminal-value histogram."""
BASE: Final = 100.0
"""Value of a rebased series at its first date."""


# ── Primitives ───────────────────────────────────────────────────────


def _time(stamp: pd.Timestamp | datetime | date) -> date | datetime:
    """A session date for midnight labels without timezone, the instant otherwise."""
    moment = pd.Timestamp(stamp)
    if moment.tzinfo is None and moment == moment.normalize():
        return moment.date()
    return moment.to_pydatetime()


def _points(series: pd.Series) -> list[Point]:
    return [
        Point(time=_time(stamp), value=finite(float(value)))
        for stamp, value in zip(pd.DatetimeIndex(series.index), series.to_numpy(), strict=True)
    ]


def _matrix(frame: pd.DataFrame) -> Matrix:
    return Matrix(
        labels=[str(label) for label in frame.columns],
        values=[[finite(float(value)) for value in row] for row in frame.to_numpy()],
    )


def _rebased(values: pd.Series) -> pd.Series:
    observed = values.dropna()
    first = float(observed.iloc[0])
    return observed * (BASE / first)


# ── Market data ──────────────────────────────────────────────────────


def instrument_out(instrument: Instrument) -> InstrumentOut:
    """An instrument's metadata."""
    exchange = instrument.exchange
    return InstrumentOut(
        symbol=instrument.symbol,
        name=instrument.name,
        asset_class=instrument.asset_class,
        currency=str(instrument.currency),
        exchange=(
            None
            if exchange is None
            else ExchangeOut(code=exchange.code, name=exchange.name, timezone=exchange.timezone)
        ),
    )


def _source_out(source: DataSource) -> SourceOut:
    return SourceOut(
        provider=source.provider, dataset=source.dataset, retrieved_at=source.retrieved_at
    )


def _stats_out(stats: SeriesStats) -> StatsOut:
    return StatsOut(
        n_observations=stats.n_observations,
        start=_time(stats.start),
        end=_time(stats.end),
        periods_per_year=stats.periods_per_year,
        mean_return=finite(stats.mean_return),
        std_return=finite(stats.std_return),
        total_return=finite(stats.total_return),
        annualized_return=finite(stats.annualized_return),
        annualized_volatility=finite(stats.annualized_volatility),
        max_drawdown=finite(stats.max_drawdown),
        skewness=finite(stats.skewness),
        excess_kurtosis=finite(stats.excess_kurtosis),
    )


def _bars(series: PriceSeries) -> list[BarOut]:
    frame = series.bars
    columns = {field: frame[field].to_numpy() for field in PriceField if field in frame.columns}
    bars: list[BarOut] = []
    for position, stamp in enumerate(pd.DatetimeIndex(frame.index)):
        values = {str(field): finite(float(column[position])) for field, column in columns.items()}
        bars.append(BarOut(time=_time(stamp), **values))  # type: ignore[arg-type]
    return bars


def economic_series_out(series: EconomicSeries) -> EconomicSeriesOut:
    """An economic series with each value's publication date."""
    frame = series.observations
    return EconomicSeriesOut(
        series_id=series.series_id,
        title=series.title,
        units=series.units,
        frequency=series.frequency,
        source=_source_out(series.source),
        has_revisions=series.has_revisions,
        observations=[
            EconomicObservationOut(
                time=pd.Timestamp(observed).date(),
                published_at=pd.Timestamp(published).date(),
                value=float(value),
            )
            for observed, published, value in zip(
                frame["observation_date"], frame["published_at"], frame["value"], strict=True
            )
        ],
    )


def flow_out(flow: FlowSeries) -> FlowOut:
    """The flow of each bar, with what follows from it and the totals."""
    table = flow.flow
    derived: dict[str, pd.Series] = {}
    if flow.has_aggressor_side:
        derived |= {
            "sell_volume": flow.sell_volume,
            "delta": flow.delta,
            "cvd": flow.cvd,
            "buy_ratio": flow.buy_ratio,
        }
    if FlowField.QUOTE_VOLUME in table.columns:
        derived["vwap"] = flow.vwap
    columns = {
        **{str(name): table[name].to_numpy() for name in table.columns},
        **{name: values.to_numpy() for name, values in derived.items()},
    }
    bars = [
        FlowBarOut(
            time=_time(stamp),
            **{name: finite(float(values[position])) for name, values in columns.items()},  # type: ignore[arg-type]
        )
        for position, stamp in enumerate(pd.DatetimeIndex(table.index))
    ]
    totals = table.sum()

    def total(field: FlowField) -> float | None:
        return finite(float(totals[field])) if field in totals.index else None

    volume = float(totals[FlowField.VOLUME])
    bought = total(FlowField.BUY_VOLUME)
    return FlowOut(
        instrument=instrument_out(flow.instrument),
        frequency=flow.frequency,
        source=_source_out(flow.source),
        has_aggressor_side=flow.has_aggressor_side,
        columns=[FlowField(name) for name in table.columns],
        summary=FlowSummaryOut(
            volume=volume,
            quote_volume=total(FlowField.QUOTE_VOLUME),
            trades=total(FlowField.TRADES),
            delta=None if bought is None else 2.0 * bought - volume,
            buy_ratio=None if bought is None or volume <= 0 else bought / volume,
        ),
        bars=bars,
    )


def rates_out(rates: RateSeries) -> RatesOut:
    """Settled rates with their annualised value and what a long position accumulated."""
    values = rates.rates
    annualized = rates.annualized()
    accumulated = rates.cashflow("long").cumsum()
    assert rates.interval is not None  # noqa: S101 - set when the series is built
    return RatesOut(
        instrument=instrument_out(rates.instrument),
        venue=rates.venue,
        kind=rates.kind,
        payer=rates.kind.payer,
        exchanged=rates.kind.is_exchanged,
        source=_source_out(rates.source),
        interval_hours=rates.interval / pd.Timedelta(hours=1),
        periods_per_year=rates.periods_per_year,
        summary=RatesSummaryOut(
            payments=len(values),
            mean_rate=finite(float(values.mean())),
            mean_annualized=finite(float(annualized.mean())),
            positive_share=finite(float((values > 0).mean())),
            accumulated_long=rates.accumulated("long"),
            accumulated_short=rates.accumulated("short"),
        ),
        rates=[
            RatePointOut(
                time=pd.Timestamp(stamp).to_pydatetime(),
                rate=float(rate),
                annualized=float(annual),
                accumulated_long=float(running),
            )
            for stamp, rate, annual, running in zip(
                pd.DatetimeIndex(values.index),
                values.to_numpy(),
                annualized.to_numpy(),
                accumulated.to_numpy(),
                strict=True,
            )
        ],
    )


def technical_out(indicators: TechnicalIndicators) -> TechnicalOut:
    """Every indicator with its parameters, its latest value and its values per bar."""
    values = indicators.values
    latest = indicators.latest()
    return TechnicalOut(
        instrument=instrument_out(indicators.instrument),
        frequency=indicators.frequency,
        source=_source_out(indicators.source),
        indicators=[
            IndicatorOut(
                name=name,
                kind="oscillator" if indicators.threshold(name) else "level",
                parameters=dict(indicators.parameters[name]),
                threshold=indicators.threshold(name),
                latest=finite(latest[name]),
                values=_points(values[name]),
            )
            for name in indicators.names
        ],
        unavailable=[
            UnavailableIndicatorOut(name=name, missing=list(missing))  # type: ignore[arg-type]
            for name, missing in indicators.unavailable.items()
        ],
    )


def patterns_out(patterns: PricePatterns) -> PatternsOut:
    """Every pattern with how often and when it last fired, and each occurrence."""
    active = set(patterns.active())
    events = patterns.events()
    return PatternsOut(
        instrument=instrument_out(patterns.instrument),
        frequency=patterns.frequency,
        source=_source_out(patterns.source),
        patterns=[
            PatternOut(
                name=name,
                family=patterns.pattern(name).family.value,
                direction=patterns.pattern(name).direction.value,
                state=patterns.pattern(name).state,
                parameters=dict(patterns.parameters[name]),
                count=patterns.count(name),
                last=None if (last := patterns.last(name)) is None else _time(last),
                active=name in active,
            )
            for name in patterns.names
        ],
        events=[
            PatternEventOut(time=_time(time), name=str(name))
            for time, name in zip(events["time"], events["pattern"], strict=True)
        ],
        unavailable=[
            UnavailablePatternOut(name=name, missing=list(missing))  # type: ignore[arg-type]
            for name, missing in patterns.unavailable.items()
        ],
    )


def series_out(series: PriceSeries) -> SeriesOut:
    """A series with its bars and statistics."""
    return SeriesOut(
        instrument=instrument_out(series.instrument),
        frequency=series.frequency,
        adjustment=series.adjustment,
        price_field=series.price_field,
        source=_source_out(series.source),
        stats=_stats_out(series.stats),
        bars=_bars(series),
    )


def metrics_out(metrics: RiskMetrics) -> MetricsOut:
    """Risk metrics."""
    return MetricsOut(
        start=_time(metrics.start),
        end=_time(metrics.end),
        periods=metrics.periods,
        periods_per_year=metrics.periods_per_year,
        total_return=finite(metrics.total_return),
        annualized_return=finite(metrics.annualized_return),
        annualized_volatility=finite(metrics.annualized_volatility),
        sharpe_ratio=finite(metrics.sharpe_ratio),
        sharpe_standard_error=finite(metrics.sharpe_standard_error),
        sortino_ratio=finite(metrics.sortino_ratio),
        calmar_ratio=finite(metrics.calmar_ratio),
        max_drawdown=finite(metrics.max_drawdown),
        best_period=finite(metrics.best_period),
        worst_period=finite(metrics.worst_period),
        positive_ratio=finite(metrics.positive_ratio),
        skewness=finite(metrics.skewness),
        excess_kurtosis=finite(metrics.excess_kurtosis),
        risk_free_rate=finite(metrics.risk_free_rate),
        risk_free_coverage=finite(metrics.risk_free_coverage),
        tail=[
            TailRiskOut(
                level=tail.level,
                method=str(tail.method),
                value_at_risk=finite(tail.value_at_risk),
                conditional_value_at_risk=finite(tail.conditional_value_at_risk),
            )
            for tail in metrics.tail
        ],
    )


def comparison_out(
    batch: BatchResult[PriceSeries],
    metrics: Mapping[str, RiskMetrics],
    correlation: pd.DataFrame | None,
) -> ComparisonOut:
    """Rebased performance, drawdowns, metrics and correlation of a batch."""
    return ComparisonOut(
        series=[
            CompareSeriesOut(
                instrument=instrument_out(series.instrument),
                performance=_points(_rebased(series.prices)),
                drawdown=_points(series.drawdown()),
                stats=_stats_out(series.stats),
                metrics=metrics_out(metrics[symbol]),
            )
            for symbol, series in batch.succeeded.items()
        ],
        correlation=None if correlation is None else _matrix(correlation),
        failed=[
            FailureOut(symbol=symbol, reason=failure.message)
            for symbol, failure in batch.failed.items()
        ],
    )


def quality_out(report: DataQualityReport) -> QualityOut:
    """A data-quality diagnosis."""
    return QualityOut(
        symbol=report.symbol,
        observations=report.observations,
        start=_time(report.start),
        end=_time(report.end),
        expected_sessions=report.expected_sessions,
        ok=report.ok,
        worst_severity=report.worst_severity,
        issues=[
            IssueOut(
                kind=issue.kind,
                severity=issue.severity,
                message=issue.message,
                count=len(issue.timestamps),
                examples=[_time(stamp) for stamp in issue.timestamps[:ISSUE_EXAMPLES]],
            )
            for issue in report.issues
        ],
    )


def risk_free_out(currency: str, rates: pd.Series) -> RiskFreeOut:
    """Point-in-time risk-free rates."""
    return RiskFreeOut(currency=currency, rates=_points(rates))


# ── Portfolios ───────────────────────────────────────────────────────


def _contributions(table: pd.DataFrame) -> list[RiskContributionOut]:
    annualized = "annualized_contribution" in table.columns
    return [
        RiskContributionOut(
            symbol=str(symbol),
            weight=float(row["weight"]),
            marginal=finite(float(row["marginal"])),
            contribution=finite(float(row["contribution"])),
            share=finite(float(row["share"])),
            annualized_contribution=(
                finite(float(row["annualized_contribution"])) if annualized else None
            ),
        )
        for symbol, row in table.iterrows()
    ]


def _episodes(table: pd.DataFrame) -> list[DrawdownEpisodeOut]:
    return [
        DrawdownEpisodeOut(
            peak=_time(row["peak"]),
            trough=_time(row["trough"]),
            recovery=None if pd.isna(row["recovery"]) else _time(row["recovery"]),
            depth=float(row["depth"]),
            duration_periods=int(row["duration_periods"]),
        )
        for _, row in table.iterrows()
    ]


def portfolio_analytics_out(portfolio: Portfolio, metrics: RiskMetrics) -> PortfolioAnalyticsOut:
    """History, metrics, correlation and risk decomposition of a portfolio."""
    backtest = portfolio.backtest()
    return PortfolioAnalyticsOut(
        name=portfolio.name,
        base_currency=str(portfolio.base_currency),
        rebalance=str(portfolio.rebalance),
        frequency=portfolio.frequency,
        start=_time(backtest.start),
        end=_time(backtest.end),
        holdings=[
            HoldingOut(
                symbol=holding.symbol,
                name=holding.series.instrument.name,
                asset_class=holding.series.instrument.asset_class,
                currency=str(holding.series.currency),
                weight=holding.weight,
            )
            for holding in portfolio
        ],
        metrics=metrics_out(metrics),
        value=_points(_rebased(backtest.values)),
        drawdown=_points(backtest.drawdown()),
        drawdown_episodes=_episodes(backtest.drawdown_episodes()),
        correlation=_matrix(portfolio.correlation()),
        risk_contributions=_contributions(portfolio.risk_contributions()),
        effective_number_of_assets=portfolio.effective_number_of_assets,
        total_turnover=backtest.total_turnover,
    )


# ── Simulation, optimisation, plans ──────────────────────────────────


def _estimate(level: float, estimate: object) -> EstimateOut:
    return EstimateOut(
        level=level,
        value=finite(getattr(estimate, "value", None)),
        lower=finite(getattr(estimate, "lower", None)),
        upper=finite(getattr(estimate, "upper", None)),
        standard_error=finite(getattr(estimate, "standard_error", None)),
    )


def _histogram(values: np.ndarray) -> list[HistogramBinOut]:
    counts, edges = np.histogram(values[np.isfinite(values)], bins=HISTOGRAM_BINS)
    return [
        HistogramBinOut(lower=float(edges[i]), upper=float(edges[i + 1]), count=int(counts[i]))
        for i in range(len(counts))
    ]


def simulation_out(result: SimulationResult) -> SimulationOut:
    """Fan chart, terminal distribution and tail risk."""
    config = result.config
    fan = result.percentile_paths((1, 5, 25, 50, 75, 95, 99))
    calibration = result.calibration
    levels = config.confidence_levels
    return SimulationOut(
        model=config.model,
        n_paths=result.n_paths,
        horizon=result.horizon,
        periods_per_year=calibration.periods_per_year,
        initial_value=config.initial_value,
        start=_time(result.start),
        fan=[
            FanPointOut(period=period, **{str(k): float(v) for k, v in row.items()})
            for period, row in enumerate(fan.to_dict("records"))  # periods 0..horizon
        ],
        terminal_histogram=_histogram(result.terminal_values),
        expected_terminal_value=finite(result.expected_terminal_value),
        median_terminal_value=finite(result.median_terminal_value),
        probability_of_loss=finite(result.probability_of_loss),
        value_at_risk=[_estimate(level, result.value_at_risk(level)) for level in levels],
        conditional_value_at_risk=[
            _estimate(level, result.conditional_value_at_risk(level)) for level in levels
        ],
        drawdown_at_risk=[
            EstimateOut(
                level=level,
                value=finite(result.drawdown_at_risk(level)),
                lower=None,
                upper=None,
                standard_error=None,
            )
            for level in levels
        ],
        calibration=CalibrationOut(
            symbols=list(calibration.symbols),
            weights=[float(w) for w in calibration.weights],
            annual_expected_return=[
                finite(float(v)) for v in calibration.annual_expected_return.to_numpy()
            ],
            annual_volatility=[finite(float(v)) for v in calibration.annual_volatility.to_numpy()],
            observations=calibration.observations,
            periods_per_year=calibration.periods_per_year,
            shrinkage=finite(calibration.shrinkage),
        ),
    )


def _optimized(result: OptimizationResult) -> OptimizedOut:
    previous = result.previous_weights
    return OptimizedOut(
        weights=[
            WeightOut(
                symbol=str(symbol),
                weight=float(weight),
                previous_weight=float(previous.get(symbol, 0.0)),
            )
            for symbol, weight in result.weights.items()
        ],
        expected_return=finite(result.expected_return),
        volatility=finite(result.volatility),
        sharpe_ratio=finite(result.sharpe_ratio),
        effective_number_of_assets=finite(result.effective_number_of_assets),
        risk_contributions=_contributions(result.risk_contributions),
    )


def optimization_out(
    result: OptimizationResult, frontier: EfficientFrontier | None
) -> OptimizationOut:
    """The optimal weights and the efficient frontier around them."""
    symbols: Sequence[str] = result.estimates.symbols
    points = frontier.points if frontier is not None else pd.DataFrame()
    assets = frontier.assets if frontier is not None else pd.DataFrame()
    return OptimizationOut(
        objective=result.config.objective,
        observations=result.estimates.observations,
        shrinkage=finite(result.estimates.shrinkage),
        result=_optimized(result),
        frontier=[
            FrontierPointOut(
                expected_return=float(row["expected_return"]),
                volatility=float(row["volatility"]),
                sharpe_ratio=finite(float(row["sharpe_ratio"])),
                weights={symbol: float(row[symbol]) for symbol in symbols},
            )
            for _, row in points.iterrows()
        ],
        assets=[
            AssetPointOut(
                symbol=str(symbol),
                expected_return=finite(float(row["expected_return"])),
                volatility=finite(float(row["volatility"])),
            )
            for symbol, row in assets.iterrows()
        ],
        minimum_variance=None if frontier is None else _optimized(frontier.minimum_variance),
        maximum_sharpe=(
            None
            if frontier is None or frontier.maximum_sharpe is None
            else _optimized(frontier.maximum_sharpe)
        ),
    )


def plan_out(result: PlanResult, probability: float) -> PlanOut:
    """Odds of a savings plan, in today's money."""
    fan = result.percentile_paths((5, 25, 50, 75, 95))
    contributed = result.contributed()
    required = None if result.plan.goal is None else result.required_contribution(probability)
    return PlanOut(
        months=result.months,
        currency=result.currency,
        goal=result.plan.goal,
        fan=[
            PlanFanPointOut(
                month=month,
                contributed=float(contributed[month]),
                **{str(k): float(v) for k, v in row.items()},
            )
            for month, row in enumerate(fan.to_dict("records"))  # months 0..months
        ],
        median_terminal_wealth=finite(result.median_terminal_wealth),
        probability_of_success=finite(result.probability_of_success),
        expected_shortfall=finite(result.expected_shortfall),
        probability_of_ruin=finite(result.probability_of_ruin),
        required_contribution=finite(required),
        success_probability=probability,
    )


# ── Service metadata ─────────────────────────────────────────────────


def health_out(
    providers: Sequence[str], *, offline: bool, database: str = "not_configured"
) -> HealthOut:
    """Health of the service."""
    return HealthOut.model_validate(
        {
            "status": "ok",
            "version": __version__,
            "core_version": core_version,
            "providers": list(providers),
            "offline": offline,
            "database": database,
        }
    )


def portfolio_spec(request: PortfolioIn) -> PortfolioSpec:
    """The definition to store for a portfolio request."""
    return PortfolioSpec(
        name=request.name,
        weights=tuple((holding.symbol, holding.weight) for holding in request.holdings),
        base_currency=request.base_currency,
        rebalance=request.rebalance.to_policy(),
        allow_short=request.allow_short,
        start=request.start,
        end=request.end,
        frequency=request.frequency,
    )


def saved_portfolio_out(record: Stored[PortfolioSpec]) -> SavedPortfolioOut:
    """A saved portfolio, with its definition in the shape the analyses take."""
    spec = record.value
    rebalance = RebalanceIn(kind=spec.rebalance.kind, band=spec.rebalance.band)
    if spec.rebalance.frequency is not None:
        rebalance = rebalance.model_copy(update={"frequency": spec.rebalance.frequency})
    return SavedPortfolioOut(
        id=record.id,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        portfolio=PortfolioIn(
            name=spec.name,
            holdings=[HoldingIn(symbol=symbol, weight=weight) for symbol, weight in spec.weights],
            base_currency=spec.base_currency,
            rebalance=rebalance,
            allow_short=spec.allow_short,
            start=spec.start,
            end=spec.end,
            frequency=spec.frequency,
        ),
    )


def saved_portfolio_page(page: Page[Stored[PortfolioSpec]]) -> SavedPortfolioPage:
    """A page of saved portfolios."""
    return SavedPortfolioPage(
        items=[saved_portfolio_out(record) for record in page.items],
        next_cursor=page.next_cursor,
    )


def provider_out(name: str, capabilities: ProviderCapabilities) -> ProviderOut:
    """What a provider serves."""
    return ProviderOut(
        name=name,
        datasets=sorted(capabilities.datasets),
        asset_classes=sorted(capabilities.asset_classes),
        frequencies=sorted(capabilities.frequencies, key=lambda frequency: frequency.rank),
        requires_api_key=capabilities.requires_api_key,
        max_history_days={
            frequency.value: limit.days for frequency, limit in capabilities.max_history.items()
        },
        rate_limits=[
            RateLimitOut(max_calls=limit.max_calls, period_seconds=limit.period_seconds)
            for limit in capabilities.rate_limits
        ],
        identifiers=capabilities.identifiers,
        rate_kinds=sorted(capabilities.rate_kinds),
    )


def module_out(module: ModuleInfo, language: str) -> ModuleOut:
    """A module of the master with its traceability."""
    return ModuleOut(
        slug=module.slug,
        block=module.block,
        title=module.title(language),
        summary=module.summary(language),
        complete=module.complete,
        requirements=[
            RequirementOut(
                id=requirement.id,
                title=requirement.title(language),
                status=requirement.status,
                code=list(requirement.code),
                tests=list(requirement.tests),
                note=requirement.note(language),
            )
            for requirement in module.requirements
        ],
    )
