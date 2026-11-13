"""Market data: instruments, bars, statistics, metrics, comparisons and data quality."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from investinglab.domain.flow import FlowField
from investinglab.domain.instruments import AssetClass
from investinglab.domain.quality import IssueKind, Severity
from investinglab.domain.rate_series import RateKind
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
    "FlowBarOut",
    "FlowOut",
    "FlowSummaryOut",
    "InstrumentOut",
    "IssueOut",
    "MetricsOut",
    "QualityOut",
    "RatePointOut",
    "RatesOut",
    "RatesSummaryOut",
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
        examples=["SAN.MC", "^GSPC", "EURUSD=X", "BTC/USDT", "BTC/USDT:USDT"],
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


class FlowBarOut(ApiModel):
    """The flow of one bar; what the source does not report is ``null``."""

    time: date | datetime = Field(description="Session date (daily and above) or UTC open.")
    volume: float = Field(description="Units of the instrument traded.")
    quote_volume: float | None = Field(default=None, description="Value traded, quote currency.")
    trades: float | None = Field(default=None, description="Number of trades.")
    buy_volume: float | None = Field(default=None, description="Units bought by the aggressor.")
    sell_volume: float | None = Field(default=None, description="Units sold by the aggressor.")
    delta: float | None = Field(default=None, description="Aggressive buying minus selling.")
    cvd: float | None = Field(default=None, description="Cumulative delta since the first bar.")
    buy_ratio: float | None = Field(
        default=None, description="Share of the volume bought by the aggressor."
    )
    vwap: float | None = Field(default=None, description="Volume-weighted average price.")


class FlowSummaryOut(ApiModel):
    """Totals over the whole range."""

    volume: float
    quote_volume: float | None
    trades: float | None
    delta: float | None = Field(description="Net aggressive buying (the last CVD).")
    buy_ratio: float | None = Field(description="Share of all the volume bought by aggressors.")


class FlowOut(ApiModel):
    """Trade flow per bar of an instrument (ADR-0031)."""

    instrument: InstrumentOut
    frequency: Frequency
    source: SourceOut
    has_aggressor_side: bool = Field(
        description="Whether the source reports the aggressor (then delta and CVD exist)."
    )
    columns: list[FlowField] = Field(description="Columns the source reports.")
    summary: FlowSummaryOut
    bars: list[FlowBarOut]


class RatePointOut(ApiModel):
    """One settled holding rate."""

    time: datetime = Field(description="Settlement instant (UTC).")
    rate: float = Field(description="Rate of the period as a decimal (0.0001 = 0.01 %).")
    annualized: float = Field(description="The rate times the periods in a year.")
    accumulated_long: float = Field(
        description="What a long unit position received so far (negative: paid)."
    )


class RatesSummaryOut(ApiModel):
    """The rates over the whole range."""

    payments: int
    mean_rate: float | None
    mean_annualized: float | None
    positive_share: float | None = Field(description="Share of periods with a positive rate.")
    accumulated_long: float = Field(
        description="Received by a long unit position (negative: paid)."
    )
    accumulated_short: float = Field(
        description="Received by a short unit position (negative: paid)."
    )


class RatesOut(ApiModel):
    """Funding, borrow fees or financing costs of an instrument on a venue (ADR-0031)."""

    instrument: InstrumentOut
    venue: str
    kind: RateKind
    payer: Literal["long", "short"] = Field(description="Side that pays when the rate is positive.")
    exchanged: bool = Field(
        description="Whether the other side receives what the payer pays (funding)."
    )
    source: SourceOut
    interval_hours: float = Field(description="Length of an accrual period.")
    periods_per_year: float
    summary: RatesSummaryOut
    rates: list[RatePointOut]
