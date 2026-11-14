"""Price patterns of a price series, for any asset class (ADR-0035).

:func:`price_patterns` evaluates the catalogue of :mod:`investinglab.analytics.patterns` on
the bars of a :class:`~investinglab.domain.series.PriceSeries`. The session patterns (the
opening range breakout) need intraday bars, and take as each bar's session its trading date
in the market's timezone (UTC for markets that never close). A pattern that needs a column
the series does not have (the open of a series of closes) is left out with what it lacks,
never computed from substitutes.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from investinglab.analytics.patterns import PATTERNS, Family, Pattern, detect
from investinglab.domain.errors import DomainError
from investinglab.domain.series import PriceField

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable, Mapping

    from investinglab.domain.instruments import Instrument
    from investinglab.domain.series import DataSource, PriceSeries
    from investinglab.domain.time import Frequency

__all__ = ["INTRADAY", "PricePatterns", "price_patterns"]

INTRADAY = "intraday"
"""What a session pattern lacks on daily or coarser bars."""
_COLUMNS = (PriceField.OPEN, PriceField.HIGH, PriceField.LOW, PriceField.CLOSE)


@dataclass(frozen=True, slots=True, eq=False)
class PricePatterns:
    """Where each price pattern occurred on the bars of one price series.

    Args:
        instrument: The instrument observed.
        frequency: Frequency of the bars.
        source: Provenance of the bars.
        data: One boolean column per pattern, on the index of the bars.
        parameters: Parameters used for each pattern.
        unavailable: Patterns left out, with what the series lacks for them (price columns,
            or ``"intraday"`` bars for the session patterns).
    """

    instrument: Instrument
    frequency: Frequency
    source: DataSource
    data: InitVar[pd.DataFrame]
    parameters: Mapping[str, Mapping[str, float]]
    unavailable: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    _flags: pd.DataFrame = field(init=False, repr=False)

    def __post_init__(self, data: pd.DataFrame) -> None:
        unknown = sorted(set(data.columns) - set(PATTERNS))
        if unknown:
            raise DomainError(f"Unknown patterns {unknown}")
        if set(data.columns) != set(self.parameters):
            raise DomainError("Every pattern needs its parameters, and only those")
        object.__setattr__(self, "_flags", data.astype(bool))
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType({k: MappingProxyType(dict(v)) for k, v in self.parameters.items()}),
        )
        object.__setattr__(self, "unavailable", MappingProxyType(dict(self.unavailable)))

    @property
    def flags(self) -> pd.DataFrame:
        """A copy of the flags: one boolean column per pattern."""
        return self._flags.copy()

    @property
    def names(self) -> tuple[str, ...]:
        """The patterns evaluated, in catalogue order."""
        return tuple(self._flags.columns)

    def pattern(self, name: str) -> Pattern:
        """The catalogue entry of an evaluated pattern.

        Raises:
            KeyError: If ``name`` was not evaluated.
        """
        if name not in self._flags.columns:
            raise KeyError(f"{name} was not evaluated")
        return PATTERNS[name]

    def __getitem__(self, name: str) -> pd.Series:
        return self._flags[name].copy()

    def count(self, name: str) -> int:
        """Bars flagged by a pattern (for a zone, the bars spent in it)."""
        return int(self[name].sum())

    def last(self, name: str) -> pd.Timestamp | None:
        """The last bar a pattern flagged, if any."""
        flags = self[name]
        hits = flags.index[flags.to_numpy()]
        return hits[-1] if len(hits) else None

    def active(self) -> tuple[str, ...]:
        """The patterns flagged on the last bar (the zones the price is in now)."""
        if self._flags.empty:
            return ()
        last = self._flags.iloc[-1]
        return tuple(name for name in self.names if bool(last[name]))

    def events(self) -> pd.DataFrame:
        """Every occurrence of an event pattern, oldest first.

        Zones are states that last, not events: they are counted, not listed.

        Returns:
            Columns ``time`` and ``pattern``, one row per flagged bar and pattern.
        """
        names = [name for name in self.names if not PATTERNS[name].state]
        rows, columns = np.nonzero(self._flags[names].to_numpy())  # by bar, then catalogue
        return pd.DataFrame(
            {"time": self._flags.index[rows], "pattern": np.asarray(names, dtype=object)[columns]}
        )

    def between(
        self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None
    ) -> PricePatterns:
        """The flags of the bars in ``[start, end]`` (both inclusive), computed on all of them.

        Cutting after detecting keeps what the bars before ``start`` set up (an order block,
        a swing) for the bars after it.
        """
        return PricePatterns(
            self.instrument,
            self.frequency,
            self.source,
            self._flags.loc[start:end],
            self.parameters,
            self.unavailable,
        )


def _sessions(series: PriceSeries) -> list[Hashable] | None:
    """The trading date of each intraday bar in the market's timezone (``None`` otherwise)."""
    if not series.frequency.is_intraday:
        return None
    index = series.bars.index
    assert isinstance(index, pd.DatetimeIndex)  # noqa: S101 - validated by PriceSeries
    return list(index.tz_convert(series.timezone).date)


def price_patterns(
    series: PriceSeries,
    names: Iterable[str] | None = None,
    parameters: Mapping[str, Mapping[str, float]] | None = None,
) -> PricePatterns:
    """Evaluate the catalogue (or ``names`` from it) on the bars of ``series``.

    Patterns read the open, high, low and close as traded; ``adj_close`` is not used, so
    that every price column shares one adjustment.

    Args:
        series: The bars.
        names: Patterns to evaluate; the whole catalogue by default.
        parameters: Parameters by pattern; each one's defaults otherwise.

    Raises:
        DomainError: An unknown pattern, or parameters for one not requested or invalid.
    """
    wanted = list(PATTERNS) if names is None else list(dict.fromkeys(names))
    unknown = sorted(set(wanted) - set(PATTERNS))
    if unknown:
        raise DomainError(f"Unknown patterns {unknown}; known: {sorted(PATTERNS)}")
    overrides = dict(parameters or {})
    stray = sorted(set(overrides) - set(wanted))
    if stray:
        raise DomainError(f"Parameters for patterns not requested: {stray}")
    bars = series.bars
    available = {column.value: bars[column] for column in _COLUMNS if column in bars.columns}
    labels = _sessions(series)
    flags: dict[str, pd.Series] = {}
    used: dict[str, dict[str, float]] = {}
    unavailable: dict[str, tuple[str, ...]] = {}
    for name in wanted:
        pattern = PATTERNS[name]
        lacking = sorted(c.value for c in pattern.columns if c.value not in available)
        if pattern.family is Family.SESSION and labels is None:
            lacking.append(INTRADAY)
        if lacking:
            unavailable[name] = tuple(lacking)
            continue
        chosen = {**pattern.defaults, **overrides.get(name, {})}
        try:
            flags[name] = detect(name, available, labels, **chosen)
        except ValueError as error:
            raise DomainError(f"{name}: {error}") from error
        used[name] = chosen
    return PricePatterns(
        instrument=series.instrument,
        frequency=series.frequency,
        source=series.source,
        data=pd.DataFrame(flags, index=bars.index, dtype=bool),
        parameters=used,
        unavailable=unavailable,
    )
