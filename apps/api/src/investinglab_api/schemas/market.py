"""Market data: instruments, bars, statistics, metrics, comparisons and data quality."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from investinglab.domain.instruments import AssetClass
from investinglab.domain.quality import IssueKind, Severity
from investinglab.domain.series import PriceAdjustment, PriceField
from investinglab.domain.time import Frequency
from investinglab_api.schemas.common import ApiModel, DateRange, Matrix, Point

__all__ = [
    "BarOut",
    "CompareRequest",
    "CompareSeriesOut",
    "ComparisonOut",
    "ExchangeOut",
    "FailureOut",
    "InstrumentOut",
    "IssueOut",
    "MetricsOut",
    "QualityOut",
    "SeriesOut",
    "SourceOut",
    "StatsOut",
    "Symbol",
    "TailRiskOut",
]

Symbol = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9.^=\-_/:]+$",
        examples=["SAN.MC", "^GSPC", "EURUSD=X", "BTC-USD"],
    ),
]


class ExchangeOut(ApiModel):
    """Trading venue."""

    code: str = Field(description="ISO 10383 MIC, or FX / CRYPTO.")
    name: str
    timezone: str = Field(description="IANA timezone of the sessions.")


class InstrumentOut(ApiModel):
    """What a series measures."""

    symbol: str
    name: str
    asset_class: AssetClass
    currency: str = Field(description="ISO 4217 code of the prices.")
    exchange: ExchangeOut | None


class SourceOut(ApiModel):
    """Provenance of the data."""

    provider: str = Field(description="Provider slug (yahoo, ecb, files...).")
    dataset: str | None
    retrieved_at: datetime


class StatsOut(ApiModel):
    """Statistics computed when the series was built (per period unless annualised)."""

    n_observations: int
    start: date | datetime
    end: date | datetime
    periods_per_year: float
    mean_return: float | None
    std_return: float | None
    total_return: float | None
    annualized_return: float | None
    annualized_volatility: float | None
    max_drawdown: float | None
    skewness: float | None
    excess_kurtosis: float | None


class BarOut(ApiModel):
    """One bar; absent columns are ``null``."""

    time: date | datetime = Field(description="Session date (daily and above) or UTC open.")
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    adj_close: float | None = None
    volume: float | None = None


class SeriesOut(ApiModel):
    """A validated price series."""

    instrument: InstrumentOut
    frequency: Frequency
    adjustment: PriceAdjustment
    price_field: PriceField = Field(description="Column used for returns and statistics.")
    source: SourceOut
    stats: StatsOut
    bars: list[BarOut]


class TailRiskOut(ApiModel):
    """VaR and CVaR per period, as positive loss fractions."""

    level: float
    method: str
    value_at_risk: float | None
    conditional_value_at_risk: float | None


class MetricsOut(ApiModel):
    """Performance and risk metrics of a return series."""

    start: date | datetime
    end: date | datetime
    periods: int
    periods_per_year: float
    total_return: float | None
    annualized_return: float | None
    annualized_volatility: float | None
    sharpe_ratio: float | None
    sharpe_standard_error: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    max_drawdown: float | None
    best_period: float | None
    worst_period: float | None
    positive_ratio: float | None
    skewness: float | None
    excess_kurtosis: float | None
    risk_free_rate: float | None = Field(
        description="Average effective annual risk-free rate used (point-in-time)."
    )
    risk_free_coverage: float | None = Field(
        description="Share of periods with a known risk-free rate (0 = none was available)."
    )
    tail: list[TailRiskOut]


class CompareRequest(DateRange):
    """Several instruments to compare on a common footing."""

    symbols: list[Symbol] = Field(min_length=1, examples=[["SAN.MC", "BBVA.MC", "^IBEX"]])


class CompareSeriesOut(ApiModel):
    """One instrument of a comparison."""

    instrument: InstrumentOut
    performance: list[Point] = Field(description="Value rebased to 100 at its first date.")
    drawdown: list[Point] = Field(description="Decline from the running peak (non-positive).")
    stats: StatsOut
    metrics: MetricsOut


class FailureOut(ApiModel):
    """An instrument that could not be obtained."""

    symbol: str
    reason: str


class ComparisonOut(ApiModel):
    """Rebased performance, drawdowns, metrics and correlation of several instruments."""

    series: list[CompareSeriesOut]
    correlation: Matrix | None = Field(
        description="Correlation of returns on common dates (null with fewer than two series)."
    )
    failed: list[FailureOut]


class IssueOut(ApiModel):
    """One data-quality issue."""

    kind: IssueKind
    severity: Severity
    message: str
    count: int = Field(description="Number of affected dates (0 for whole-series issues).")
    examples: list[date | datetime] = Field(description="First affected dates.")


class QualityOut(ApiModel):
    """Data-quality diagnosis against the market's official calendar."""

    symbol: str
    observations: int
    start: date | datetime
    end: date | datetime
    expected_sessions: int | None
    ok: bool
    worst_severity: Severity | None
    issues: list[IssueOut]
