"""Price series: the central value object of InvestingLab.

A :class:`PriceSeries` bundles an instrument's metadata with its observed bars (OHLCV and/or
adjusted close). It is immutable, validated on construction (ADR-0006) and computes its
fundamental statistics automatically when instantiated.

Immutability note: the bars live in a private DataFrame and every accessor returns a new
object. pandas >= 3 always uses Copy-on-Write, so those objects share memory with the
series (no copy cost) yet any modification triggers a private copy: the series itself can
never be altered after validation.
"""

from __future__ import annotations

import re
from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import pandas as pd

from investinglab.analytics import (
    annualize_volatility,
    beta,
    cagr,
    cumulative_returns,
    describe_returns,
    drawdown,
    log_returns,
    max_drawdown,
    simple_returns,
    total_return,
)
from investinglab.domain.errors import DomainError, InvalidSeriesError
from investinglab.domain.metrics import DEFAULT_CONFIDENCE_LEVELS, RiskMetrics
from investinglab.domain.quality import DataQualityReport, QualityThresholds, assess_quality
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from investinglab.domain.instruments import AssetClass, Instrument
    from investinglab.domain.money import Currency

__all__ = [
    "MIN_OBSERVATIONS",
    "TIME_INDEX_NAME",
    "DataSource",
    "PriceAdjustment",
    "PriceField",
    "PriceSeries",
    "ReturnKind",
    "SeriesStats",
]

MIN_OBSERVATIONS: Final = 3
"""Minimum number of observations: two returns are needed for a sample standard deviation."""

TIME_INDEX_NAME: Final = "timestamp"


class PriceField(StrEnum):
    """Columns a price series may contain."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    ADJ_CLOSE = "adj_close"
    VOLUME = "volume"


_PRICE_FIELDS: Final = (
    PriceField.OPEN,
    PriceField.HIGH,
    PriceField.LOW,
    PriceField.CLOSE,
    PriceField.ADJ_CLOSE,
)
_COLUMN_ORDER: Final = (*_PRICE_FIELDS, PriceField.VOLUME)


class PriceAdjustment(StrEnum):
    """Corporate-action adjustment applied to the open/high/low/close columns.

    The ``adj_close`` column, when present, is always adjusted for splits *and* dividends
    (a total-return series).
    """

    RAW = "raw"
    SPLITS = "splits"
    SPLITS_AND_DIVIDENDS = "splits_and_dividends"


class ReturnKind(StrEnum):
    """Return convention."""

    SIMPLE = "simple"
    LOG = "log"


_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,39}$")


@dataclass(frozen=True, slots=True)
class DataSource:
    """Provenance of a dataset.

    Attributes:
        provider: Provider slug (``yahoo``, ``alphavantage``, ``fred``, ``synthetic``...).
        retrieved_at: When the data was downloaded (timezone-aware).
        dataset: Optional provider endpoint or dataset name, for traceability.
    """

    provider: str
    retrieved_at: datetime
    dataset: str | None = None

    def __post_init__(self) -> None:
        if not _PROVIDER.fullmatch(self.provider):
            raise DomainError(f"Invalid provider slug {self.provider!r}")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise DomainError("DataSource.retrieved_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SeriesStats:
    """Fundamental statistics of a price series, computed at construction time.

    Per-period figures use the series' own frequency; annualised figures use the number of
    periods per year of the instrument's market (252 trading days for equities, 365 for
    crypto, bars per session for intraday data...).

    Attributes:
        n_observations: Number of prices.
        start: First timestamp.
        end: Last timestamp.
        periods_per_year: Annualisation factor used.
        mean_return: Mean simple return per period.
        std_return: Sample standard deviation of simple returns per period (``ddof=1``).
        mean_log_return: Mean log return per period.
        std_log_return: Sample standard deviation of log returns per period.
        total_return: Simple return from the first to the last price.
        annualized_return: Compound annual growth rate (geometric).
        annualized_volatility: ``std_return * sqrt(periods_per_year)``.
        max_drawdown: Worst peak-to-trough decline (non-positive).
        skewness: Sample skewness of simple returns (``nan`` if undefined).
        excess_kurtosis: Sample excess kurtosis of simple returns (``nan`` if undefined).
    """

    n_observations: int
    start: pd.Timestamp
    end: pd.Timestamp
    periods_per_year: float
    mean_return: float
    std_return: float
    mean_log_return: float
    std_log_return: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    skewness: float
    excess_kurtosis: float

    @classmethod
    def from_prices(cls, prices: pd.Series, periods_per_year: float) -> SeriesStats:
        """Compute the statistics of a validated, gap-free price series."""
        simple = describe_returns(simple_returns(prices))
        logs = describe_returns(log_returns(prices))
        growth = total_return(prices)
        return cls(
            n_observations=len(prices),
            start=prices.index[0],
            end=prices.index[-1],
            periods_per_year=periods_per_year,
            mean_return=simple.mean,
            std_return=simple.std,
            mean_log_return=logs.mean,
            std_log_return=logs.std,
            total_return=growth,
            annualized_return=cagr(growth, len(prices) - 1, periods_per_year),
            annualized_volatility=annualize_volatility(simple.std, periods_per_year),
            max_drawdown=max_drawdown(prices),
            skewness=simple.skewness,
            excess_kurtosis=simple.excess_kurtosis,
        )


# ──────────────────────────────────────────────────────────────────────
# Validation (ADR-0006)
# ──────────────────────────────────────────────────────────────────────


def _validate_index(index: pd.Index, frequency: Frequency, problems: list[str]) -> pd.Index:
    if not isinstance(index, pd.DatetimeIndex):
        problems.append(f"index must be a DatetimeIndex, got {type(index).__name__}")
        return index
    if frequency.is_intraday:
        if index.tz is None:
            problems.append("intraday data needs a timezone-aware index (it is normalised to UTC)")
        else:
            index = index.tz_convert("UTC")
    elif index.tz is not None:
        problems.append(
            "daily and lower frequencies use session labels: a timezone-naive index of dates "
            "(the market timezone is instrument metadata)"
        )
    elif not (index == index.normalize()).all():
        problems.append("session labels must be dates at midnight (no time of day)")
    if index.has_duplicates:
        duplicated = index[index.duplicated()].unique()[:3]
        problems.append(f"duplicated timestamps: {[str(ts) for ts in duplicated]}")
    if not index.is_monotonic_increasing:
        problems.append("index must be sorted in increasing time order")
    elif len(index) > 1 and not index.has_duplicates:
        smallest_gap = index.to_series().diff().min()
        if smallest_gap < frequency.min_spacing:
            problems.append(
                f"observations {smallest_gap} apart are too close for frequency "
                f"{frequency.value!r} (minimum {frequency.min_spacing})"
            )
    return index


def _validate_columns(frame: pd.DataFrame, problems: list[str]) -> pd.DataFrame:
    allowed = {f.value for f in _COLUMN_ORDER}
    unknown = [str(c) for c in frame.columns if c not in allowed]
    if unknown:
        problems.append(f"unknown columns {unknown}; allowed: {sorted(allowed)}")
    if PriceField.CLOSE not in frame.columns:
        problems.append("a 'close' column is required")
    present = [f.value for f in _COLUMN_ORDER if f.value in frame.columns]
    canonical = frame.loc[:, present]
    numeric: dict[str, pd.Series] = {}
    for column in present:
        values = canonical[column]
        if not (pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values)):
            problems.append(f"column {column!r} must be numeric, got {values.dtype}")
            continue
        values = values.astype("float64")
        if column == PriceField.VOLUME:
            if (values.dropna() < 0).any() or np.isinf(values).any():
                problems.append("'volume' must be finite and non-negative (NaN = not reported)")
        else:
            bad = ~np.isfinite(values) | (values <= 0)
            if bad.any():
                examples = [str(ts) for ts in values.index[bad][:3]]
                problems.append(
                    f"{column!r} has {int(bad.sum())} missing, non-finite or non-positive "
                    f"prices (e.g. at {examples}); a missing observation is an absent row"
                )
        numeric[column] = values
    return pd.DataFrame(numeric, index=canonical.index)


def _validated_bars(data: object, frequency: Frequency, subject: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise InvalidSeriesError(subject, [f"bars must be a DataFrame, got {type(data).__name__}"])
    problems: list[str] = []
    if len(data) < MIN_OBSERVATIONS:
        problems.append(f"needs at least {MIN_OBSERVATIONS} observations, got {len(data)}")
    index = _validate_index(data.index, frequency, problems)
    bars = _validate_columns(data, problems)
    if problems:
        raise InvalidSeriesError(subject, problems)
    # Canonical nanosecond resolution: sources (CSV, Parquet, DuckDB) differ in time units.
    bars.index = pd.DatetimeIndex(index).as_unit("ns").rename(TIME_INDEX_NAME)
    bars.columns.name = None
    return bars


# ──────────────────────────────────────────────────────────────────────
# PriceSeries
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True, eq=False)
class PriceSeries:
    """An immutable, validated price series of one instrument.

    Args:
        instrument: Instrument metadata (symbol, name, asset class, currency, venue).
        frequency: Sampling frequency of the bars.
        source: Provenance (provider and download timestamp).
        data: Bars indexed by time with a subset of the columns ``open``, ``high``,
            ``low``, ``close``, ``adj_close`` and ``volume``. ``close`` is required.
        adjustment: Adjustment applied to the open/high/low/close columns.

    Raises:
        InvalidSeriesError: Listing every structural problem found (see ADR-0006).

    Examples:
        >>> series.stats.mean_return, series.stats.std_return  # computed on creation
        >>> series.returns().tail()
        >>> series.max_drawdown()
    """

    instrument: Instrument
    frequency: Frequency
    source: DataSource
    data: InitVar[pd.DataFrame]
    adjustment: PriceAdjustment = PriceAdjustment.RAW
    _bars: pd.DataFrame = field(init=False, repr=False)
    stats: SeriesStats = field(init=False)

    def __post_init__(self, data: pd.DataFrame) -> None:
        bars = _validated_bars(data, self.frequency, self.instrument.symbol)
        object.__setattr__(self, "_bars", bars)
        price_column = (
            PriceField.ADJ_CLOSE if PriceField.ADJ_CLOSE in bars.columns else PriceField.CLOSE
        )
        stats = SeriesStats.from_prices(bars[price_column], self.periods_per_year)
        object.__setattr__(self, "stats", stats)

    # ── Metadata ─────────────────────────────────────────────────────

    @property
    def symbol(self) -> str:
        """Instrument symbol (ticker)."""
        return self.instrument.symbol

    @property
    def name(self) -> str:
        """Instrument name."""
        return self.instrument.name

    @property
    def asset_class(self) -> AssetClass:
        """Instrument asset class."""
        return self.instrument.asset_class

    @property
    def currency(self) -> Currency:
        """Currency the prices are expressed in."""
        return self.instrument.currency

    @property
    def timezone(self) -> str:
        """IANA timezone of the market (session labels are dates in this zone)."""
        return self.instrument.timezone

    @property
    def retrieved_at(self) -> datetime:
        """When the data was downloaded."""
        return self.source.retrieved_at

    @property
    def periods_per_year(self) -> float:
        """Annualisation factor for this frequency on the instrument's market."""
        return self.instrument.schedule.periods_per_year(self.frequency)

    @property
    def start(self) -> pd.Timestamp:
        """First timestamp."""
        return self.stats.start

    @property
    def end(self) -> pd.Timestamp:
        """Last timestamp."""
        return self.stats.end

    # ── Data access (each call returns a new object; the series stays immutable) ──

    @property
    def bars(self) -> pd.DataFrame:
        """All columns, indexed by time."""
        return self._bars.copy(deep=False)

    @property
    def price_field(self) -> PriceField:
        """Column used for analytics: ``adj_close`` when available, else ``close``."""
        if PriceField.ADJ_CLOSE in self._bars.columns:
            return PriceField.ADJ_CLOSE
        return PriceField.CLOSE

    @property
    def prices(self) -> pd.Series:
        """Analytical price series (``adj_close`` if present, otherwise ``close``)."""
        return self._bars[self.price_field].rename(self.symbol)

    def column(self, name: PriceField | str) -> pd.Series:
        """One column of the bars.

        Raises:
            KeyError: If the column is not present in this series.
        """
        key = PriceField(name)
        if key not in self._bars.columns:
            raise KeyError(f"{self.symbol} has no {key.value!r} column")
        return self._bars[key].rename(self.symbol)

    def to_frame(self) -> pd.DataFrame:
        """The bars as a DataFrame (alias of :attr:`bars`)."""
        return self.bars

    def __len__(self) -> int:
        return len(self._bars)

    # ── Analytics ────────────────────────────────────────────────────

    def returns(self, kind: ReturnKind | str = ReturnKind.SIMPLE) -> pd.Series:
        """Period returns between consecutive observations."""
        if ReturnKind(kind) is ReturnKind.LOG:
            return log_returns(self.prices)
        return simple_returns(self.prices)

    def log_returns(self) -> pd.Series:
        """Logarithmic returns (additive over time)."""
        return self.returns(ReturnKind.LOG)

    def cumulative_returns(self) -> pd.Series:
        """Compounded return since the first observation."""
        return cumulative_returns(self.returns())

    def annualized_volatility(self) -> float:
        """Annualised volatility of simple returns."""
        return self.stats.annualized_volatility

    def drawdown(self) -> pd.Series:
        """Decline from the running peak at each date (values in ``[-1, 0]``)."""
        return drawdown(self.prices)

    def max_drawdown(self) -> float:
        """Worst peak-to-trough decline (non-positive)."""
        return self.stats.max_drawdown

    def metrics(
        self,
        *,
        risk_free_rate: float | pd.Series = 0.0,
        levels: Sequence[float] = DEFAULT_CONFIDENCE_LEVELS,
    ) -> RiskMetrics:
        """Performance and risk metrics (Sharpe, Sortino, Calmar, VaR/CVaR...).

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

    def quality(
        self,
        *,
        expected_sessions: pd.DatetimeIndex | None = None,
        thresholds: QualityThresholds | None = None,
    ) -> DataQualityReport:
        """Diagnose data-quality issues (outliers, split-like jumps, frozen prices...).

        Nothing is modified or removed. Pass the market's official sessions (see
        :class:`~investinglab.services.DataQualityService`) to also detect missing days.
        """
        return assess_quality(self, expected_sessions=expected_sessions, thresholds=thresholds)

    def beta(self, benchmark: PriceSeries) -> float:
        """Sensitivity to ``benchmark`` on the dates where both have a return."""
        return beta(self.returns(), benchmark.returns())

    # ── Transformations (return new, validated series) ───────────────

    def with_bars(self, data: pd.DataFrame, **changes: Any) -> PriceSeries:  # noqa: ANN401
        """A new series with other bars (and optionally other metadata), validated again."""
        values: dict[str, Any] = {
            "instrument": self.instrument,
            "frequency": self.frequency,
            "source": self.source,
            "adjustment": self.adjustment,
        }
        values.update(changes)
        return PriceSeries(data=data, **values)

    def between(
        self,
        start: date | datetime | pd.Timestamp | str | None = None,
        end: date | datetime | pd.Timestamp | str | None = None,
    ) -> PriceSeries:
        """Sub-series with timestamps in ``[start, end]`` (both inclusive).

        For intraday series, naive bounds are session dates in the market timezone: the
        start includes that whole day and the end includes every bar of its day.
        """
        lower = self._bound(start, is_end=False)
        upper = self._bound(end, is_end=True)
        return self.with_bars(self._bars.loc[lower:upper])

    def _bound(
        self, value: date | datetime | pd.Timestamp | str | None, *, is_end: bool
    ) -> pd.Timestamp | None:
        if value is None:
            return None
        stamp = pd.Timestamp(value)
        if not self.frequency.is_intraday or stamp.tzinfo is not None:
            return stamp
        day = stamp.normalize().tz_localize(self.instrument.timezone)
        if is_end:
            day += pd.Timedelta(days=1) - pd.Timedelta(1, unit="ns")
        return day.tz_convert("UTC")

    def resample(self, frequency: Frequency | str) -> PriceSeries:
        """Aggregate the bars to a coarser frequency.

        OHLC is aggregated as first/max/min/last, ``adj_close`` as last and ``volume`` as
        the sum. Periods without observations are dropped (never filled). Daily and lower
        frequencies are labelled with the *last observed session* of each period, so no
        artificial dates appear; intraday bars keep the bin start (bar open time). Intraday
        data resampled to daily is converted to session dates in the market timezone.

        Raises:
            DomainError: If ``frequency`` is not coarser than the current one.
        """
        target = Frequency(frequency)
        if not self.frequency.is_finer_than(target):
            raise DomainError(
                f"Can only resample to a coarser frequency than {self.frequency.value!r}, "
                f"got {target.value!r}"
            )
        bars = self._bars
        if self.frequency.is_intraday and not target.is_intraday:
            local = bars.index.tz_convert(self.instrument.timezone)  # type: ignore[attr-defined]
            bars = bars.set_axis(local.tz_localize(None).normalize())
            bars = _aggregate(bars, bars.index)
            if target is Frequency.DAY_1:
                return self.with_bars(bars, frequency=target)
        if target.is_intraday:
            grouped = bars.resample(target.pandas_rule, label="left", closed="left")
            return self.with_bars(_aggregate_resampled(grouped, bars.columns), frequency=target)
        return self.with_bars(_aggregate_by_period(bars, target), frequency=target)

    # ── Value semantics ──────────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PriceSeries):
            return NotImplemented
        return (
            self.instrument == other.instrument
            and self.frequency == other.frequency
            and self.source == other.source
            and self.adjustment == other.adjustment
            and self._bars.equals(other._bars)
        )

    def __hash__(self) -> int:
        return hash((self.instrument, self.frequency, self.source, self.start, self.end, len(self)))

    def __repr__(self) -> str:
        return (
            f"PriceSeries({self.symbol}, {self.frequency.value}, "
            f"{self.start.isoformat()} → {self.end.isoformat()}, n={len(self)}, "
            f"{self.currency}, source={self.source.provider})"
        )


# ──────────────────────────────────────────────────────────────────────
# Aggregation helpers
# ──────────────────────────────────────────────────────────────────────

_AGGREGATIONS: Final[dict[str, str]] = {
    PriceField.OPEN: "first",
    PriceField.HIGH: "max",
    PriceField.LOW: "min",
    PriceField.CLOSE: "last",
    PriceField.ADJ_CLOSE: "last",
}


def _aggregate(bars: pd.DataFrame, keys: pd.Index) -> pd.DataFrame:
    """Aggregate rows sharing the same key; the key becomes the new index."""
    grouped = bars.groupby(keys, sort=True)
    columns = {
        column: (
            grouped[column].sum(min_count=1)
            if column == PriceField.VOLUME
            else grouped[column].agg(_AGGREGATIONS[column])
        )
        for column in bars.columns
    }
    return pd.DataFrame(columns)


def _aggregate_resampled(grouped: Any, columns: pd.Index) -> pd.DataFrame:  # noqa: ANN401
    result = pd.DataFrame(
        {
            column: (
                grouped[column].sum(min_count=1)
                if column == PriceField.VOLUME
                else grouped[column].agg(_AGGREGATIONS[column])
            )
            for column in columns
        }
    )
    return result.dropna(subset=[PriceField.CLOSE])


def _aggregate_by_period(bars: pd.DataFrame, target: Frequency) -> pd.DataFrame:
    """Aggregate session bars into calendar periods labelled by their last observed session."""
    periods = bars.index.to_period(_PERIOD_ALIASES[target])  # type: ignore[attr-defined]
    aggregated = _aggregate(bars, periods)
    last_session = bars.index.to_series().groupby(periods).max()
    aggregated.index = pd.DatetimeIndex(last_session.loc[aggregated.index].to_numpy())
    return aggregated


_PERIOD_ALIASES: Final[dict[Frequency, str]] = {
    Frequency.WEEK_1: "W-SUN",
    Frequency.MONTH_1: "M",
    Frequency.QUARTER_1: "Q",
    Frequency.YEAR_1: "Y",
}
