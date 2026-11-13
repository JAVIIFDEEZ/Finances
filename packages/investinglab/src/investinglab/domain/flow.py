"""Trade flow per bar: how much traded, in how many trades and who was the aggressor.

A price bar says where the price went; its flow says who pushed it. Venues that report the
aggressor side of each trade (most crypto exchanges, and equity feeds with trade
classification) allow two classic order-flow measures with no tick data at all:

* **delta**: aggressive buying minus aggressive selling in the bar;
* **CVD** (cumulative volume delta): the running sum of the delta.

Flow is not a price, so it lives beside :class:`~investinglab.domain.series.PriceSeries`
instead of inside it: the same instrument, frequency and timestamps, its own columns and its
own rules (ADR-0031).
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.domain.errors import DomainError, IncompatibleSeriesError, InvalidSeriesError
from investinglab.domain.series import (
    MIN_OBSERVATIONS,
    TIME_INDEX_NAME,
    DataSource,
    calendar_periods,
    validate_time_index,
)
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from investinglab.domain.instruments import Instrument
    from investinglab.domain.series import PriceSeries

__all__ = ["FlowField", "FlowSeries"]

VOLUME_TOLERANCE: Final = 1e-9
"""Relative slack when comparing the aggressive buying of a bar with its volume."""


class FlowField(StrEnum):
    """Columns of a :class:`FlowSeries`."""

    VOLUME = "volume"
    """Units of the instrument traded in the bar."""
    QUOTE_VOLUME = "quote_volume"
    """Value traded in the bar, in the currency the price is quoted in."""
    TRADES = "trades"
    """Number of trades in the bar."""
    BUY_VOLUME = "buy_volume"
    """Units bought by the aggressor (the taker lifted the offer)."""
    BUY_QUOTE_VOLUME = "buy_quote_volume"
    """Value bought by the aggressor, in the quote currency."""


_COLUMNS: Final = tuple(FlowField)


def _validated_flow(data: object, frequency: Frequency, subject: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise InvalidSeriesError(subject, [f"flow must be a DataFrame, got {type(data).__name__}"])
    problems: list[str] = []
    if len(data) < MIN_OBSERVATIONS:
        problems.append(f"needs at least {MIN_OBSERVATIONS} observations, got {len(data)}")
    index = validate_time_index(data.index, frequency, problems)
    allowed = {column.value for column in _COLUMNS}
    unknown = [str(column) for column in data.columns if column not in allowed]
    if unknown:
        problems.append(f"unknown columns {unknown}; allowed: {sorted(allowed)}")
    if FlowField.VOLUME not in data.columns:
        problems.append("a 'volume' column is required")
    numeric: dict[str, pd.Series] = {}
    for column in (c.value for c in _COLUMNS if c.value in data.columns):
        values = data[column]
        if not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values):
            problems.append(f"column {column!r} must be numeric, got {values.dtype}")
            continue
        values = values.astype("float64")
        bad = ~np.isfinite(values) | (values < 0)
        if bad.any():
            examples = [str(stamp) for stamp in values.index[bad][:3]]
            problems.append(
                f"{column!r} has {int(bad.sum())} missing, non-finite or negative values "
                f"(e.g. at {examples}); a bar without flow is an absent row"
            )
        numeric[column] = values
    for part, whole in (
        (FlowField.BUY_VOLUME, FlowField.VOLUME),
        (FlowField.BUY_QUOTE_VOLUME, FlowField.QUOTE_VOLUME),
    ):
        if part in numeric and whole in numeric:
            excess = numeric[part] > numeric[whole] * (1 + VOLUME_TOLERANCE) + VOLUME_TOLERANCE
            if excess.any():
                examples = [str(stamp) for stamp in numeric[part].index[excess][:3]]
                problems.append(f"{part.value!r} exceeds {whole.value!r} (e.g. at {examples})")
    if FlowField.TRADES in numeric and (numeric[FlowField.TRADES] % 1 != 0).any():
        problems.append("'trades' must be whole numbers")
    if problems:
        raise InvalidSeriesError(subject, problems)
    flow = pd.DataFrame(numeric, index=data.index)
    flow.index = pd.DatetimeIndex(index).as_unit("ns").rename(TIME_INDEX_NAME)
    flow.columns.name = None
    return flow


@dataclass(frozen=True, slots=True, eq=False)
class FlowSeries:
    """An immutable, validated series of trade flow per bar of one instrument.

    Args:
        instrument: The instrument traded.
        frequency: Frequency of the bars.
        source: Provenance (provider and download timestamp).
        data: Flow indexed like the price bars, with ``volume`` and any of
            ``quote_volume``, ``trades``, ``buy_volume`` and ``buy_quote_volume``.

    Raises:
        InvalidSeriesError: Listing every problem found. Values are finite and not negative,
            the aggressive buying of a bar never exceeds its volume, and a bar without flow
            is an absent row, never a zero.
    """

    instrument: Instrument
    frequency: Frequency
    source: DataSource
    data: InitVar[pd.DataFrame]
    _flow: pd.DataFrame = field(init=False, repr=False)

    __match_args__ = ("instrument", "frequency", "source")

    def __post_init__(self, data: pd.DataFrame) -> None:
        object.__setattr__(
            self, "_flow", _validated_flow(data, self.frequency, self.instrument.symbol)
        )

    @property
    def symbol(self) -> str:
        """Instrument symbol."""
        return self.instrument.symbol

    @property
    def flow(self) -> pd.DataFrame:
        """A copy of the validated flow, columns in canonical order."""
        return self._flow.copy()

    @property
    def start(self) -> pd.Timestamp:
        """Timestamp of the first bar."""
        return pd.Timestamp(self._flow.index[0])

    @property
    def end(self) -> pd.Timestamp:
        """Timestamp of the last bar."""
        return pd.Timestamp(self._flow.index[-1])

    def __len__(self) -> int:
        return len(self._flow)

    @property
    def has_aggressor_side(self) -> bool:
        """Whether the venue reported who was the aggressor (``buy_volume``)."""
        return FlowField.BUY_VOLUME in self._flow.columns

    def column(self, name: FlowField | str) -> pd.Series:
        """One column of the flow.

        Raises:
            KeyError: The source did not report that column.
        """
        key = FlowField(name).value
        if key not in self._flow.columns:
            raise KeyError(f"{self.symbol}: the source reports no {key!r}")
        return self._flow[key].copy()

    @property
    def volume(self) -> pd.Series:
        """Units traded in each bar."""
        return self._flow[FlowField.VOLUME].copy()

    def _buy(self) -> pd.Series:
        if not self.has_aggressor_side:
            raise KeyError(
                f"{self.symbol}: the source reports no aggressor side, so there is no "
                "buy/sell split, delta or CVD"
            )
        return self._flow[FlowField.BUY_VOLUME]

    @property
    def buy_volume(self) -> pd.Series:
        """Units bought by the aggressor in each bar."""
        return self._buy().copy()

    @property
    def sell_volume(self) -> pd.Series:
        """Units sold by the aggressor in each bar (the rest of the volume)."""
        return (self._flow[FlowField.VOLUME] - self._buy()).clip(lower=0.0).rename("sell_volume")

    @property
    def delta(self) -> pd.Series:
        """Aggressive buying minus aggressive selling: ``2 x buy_volume - volume``."""
        return (2.0 * self._buy() - self._flow[FlowField.VOLUME]).rename("delta")

    @property
    def cvd(self) -> pd.Series:
        """Cumulative volume delta since the first bar of this series.

        Its level depends on where the series starts; its changes do not.
        """
        return self.delta.cumsum().rename("cvd")

    @property
    def buy_ratio(self) -> pd.Series:
        """Share of the volume bought by the aggressor (NaN in bars with no volume)."""
        volume = self._flow[FlowField.VOLUME]
        return (self._buy() / volume.where(volume > 0)).rename("buy_ratio")

    @property
    def vwap(self) -> pd.Series:
        """Volume-weighted average price of each bar (NaN in bars with no volume).

        Raises:
            KeyError: The source did not report ``quote_volume``.
        """
        volume = self._flow[FlowField.VOLUME]
        return (self.column(FlowField.QUOTE_VOLUME) / volume.where(volume > 0)).rename("vwap")

    @property
    def average_trade_size(self) -> pd.Series:
        """Units per trade in each bar (NaN in bars with no trades).

        Raises:
            KeyError: The source did not report ``trades``.
        """
        trades = self.column(FlowField.TRADES)
        return (self._flow[FlowField.VOLUME] / trades.where(trades > 0)).rename(
            "average_trade_size"
        )

    def between(
        self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None
    ) -> FlowSeries:
        """Sub-series with timestamps in ``[start, end]`` (both inclusive)."""
        return FlowSeries(self.instrument, self.frequency, self.source, self._flow.loc[start:end])

    def resample(self, frequency: Frequency | str) -> FlowSeries:
        """Aggregate the flow to a coarser frequency, labelled like the price bars.

        Every column is a quantity, so each one is summed. The labels follow
        :meth:`PriceSeries.resample <investinglab.domain.series.PriceSeries.resample>`:
        intraday bins keep their open time, intraday flow aggregated to days uses the session
        dates of the market's timezone, and weeks, months, quarters and years are labelled with
        their last observed session. Periods without bars are left out, never filled.

        Raises:
            DomainError: If ``frequency`` is not coarser than the current one.
        """
        target = Frequency(frequency)
        if not self.frequency.is_finer_than(target):
            raise DomainError(
                f"Can only resample to a coarser frequency than {self.frequency.value!r}, "
                f"got {target.value!r}"
            )
        flow = self._flow
        if target.is_intraday:
            bins = flow.resample(target.pandas_rule, label="left", closed="left")
            return self._with(bins.sum(min_count=1).dropna(how="all"), target)
        if self.frequency.is_intraday:
            local = pd.DatetimeIndex(flow.index).tz_convert(self.instrument.timezone)
            flow = flow.groupby(local.tz_localize(None).normalize(), sort=True).sum()
            if target is Frequency.DAY_1:
                return self._with(flow, target)
        sessions = pd.DatetimeIndex(flow.index)
        periods = calendar_periods(sessions, target)
        aggregated = flow.groupby(periods, sort=True).sum()
        last_session = sessions.to_series().groupby(periods).max()
        aggregated.index = pd.DatetimeIndex(last_session.loc[aggregated.index].to_numpy())
        return self._with(aggregated, target)

    def _with(self, flow: pd.DataFrame, frequency: Frequency) -> FlowSeries:
        return FlowSeries(self.instrument, frequency, self.source, flow)

    def aligned_with(self, prices: PriceSeries) -> FlowSeries:
        """The flow of the bars ``prices`` has: same instrument, frequency and timestamps.

        Raises:
            IncompatibleSeriesError: Another instrument or frequency, or no bar in common.
        """
        problems = []
        if prices.instrument.symbol != self.symbol:
            problems.append(f"flow of {self.symbol}, prices of {prices.symbol}")
        if prices.frequency != self.frequency:
            problems.append(f"flow is {self.frequency.value}, prices are {prices.frequency.value}")
        if problems:
            raise IncompatibleSeriesError(self.symbol, problems)
        common = self._flow.index.intersection(prices.bars.index)
        if len(common) < MIN_OBSERVATIONS:
            raise IncompatibleSeriesError(
                self.symbol, [f"only {len(common)} bars in common with the prices"]
            )
        return FlowSeries(self.instrument, self.frequency, self.source, self._flow.loc[common])

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FlowSeries):
            return NotImplemented
        return (
            self.instrument == other.instrument
            and self.frequency == other.frequency
            and self.source == other.source
            and self._flow.equals(other._flow)
        )

    def __hash__(self) -> int:
        return hash((self.instrument, self.frequency, self.source, self.start, self.end, len(self)))

    def __repr__(self) -> str:
        return (
            f"FlowSeries({self.symbol}, {self.frequency.value}, "
            f"{self.start.isoformat()} → {self.end.isoformat()}, n={len(self)}, "
            f"source={self.source.provider})"
        )
