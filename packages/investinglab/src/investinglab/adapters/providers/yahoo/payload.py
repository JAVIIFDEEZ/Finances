"""Typed view of the Yahoo Finance chart payload (``/v8/finance/chart/{symbol}``).

Only the fields the adapter uses are modelled; anything else Yahoo sends is ignored. The
payload is validated here, at the boundary, so the provider works with typed values and a
change in Yahoo's format surfaces as a clear :class:`~investinglab.ports.ProviderDataError`
instead of a ``KeyError`` deep inside the parsing code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AdjustedClose",
    "Chart",
    "ChartError",
    "ChartMeta",
    "ChartResponse",
    "ChartResult",
    "Indicators",
    "Quote",
    "TradingPeriod",
    "TradingPeriods",
]


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class TradingPeriod(_Payload):
    """A trading period in UTC seconds."""

    start: int
    end: int


class TradingPeriods(_Payload):
    """The current (or latest) trading periods of the instrument's market."""

    regular: TradingPeriod | None = None


class ChartMeta(_Payload):
    """Instrument metadata sent with every chart."""

    symbol: str
    currency: str | None = None
    exchange_name: str | None = Field(default=None, alias="exchangeName")
    instrument_type: str | None = Field(default=None, alias="instrumentType")
    exchange_timezone_name: str = Field(alias="exchangeTimezoneName")
    long_name: str | None = Field(default=None, alias="longName")
    short_name: str | None = Field(default=None, alias="shortName")
    data_granularity: str | None = Field(default=None, alias="dataGranularity")
    current_trading_period: TradingPeriods | None = Field(
        default=None, alias="currentTradingPeriod"
    )


class Quote(_Payload):
    """OHLCV columns, aligned with the timestamps (``None`` where Yahoo has no value)."""

    open: list[float | None] = Field(default_factory=list)
    high: list[float | None] = Field(default_factory=list)
    low: list[float | None] = Field(default_factory=list)
    close: list[float | None] = Field(default_factory=list)
    volume: list[float | None] = Field(default_factory=list)


class AdjustedClose(_Payload):
    """Close adjusted for splits and dividends (daily and coarser intervals only)."""

    adjclose: list[float | None] = Field(default_factory=list)


class Indicators(_Payload):
    """Price columns of a chart."""

    quote: list[Quote] = Field(default_factory=list)
    adjclose: list[AdjustedClose] = Field(default_factory=list)


class ChartResult(_Payload):
    """One instrument's chart: metadata, bar open times (UTC seconds) and columns."""

    meta: ChartMeta
    timestamp: list[int] = Field(default_factory=list)
    indicators: Indicators = Field(default_factory=Indicators)


class ChartError(_Payload):
    """Error reported inside the payload."""

    code: str
    description: str | None = None


class Chart(_Payload):
    """Either results or an error."""

    result: list[ChartResult] | None = None
    error: ChartError | None = None


class ChartResponse(_Payload):
    """Top-level chart document."""

    chart: Chart
