"""Technical indicators of a price series, for any asset class (ADR-0034).

:func:`technical_indicators` evaluates the catalogue of
:mod:`investinglab.analytics.technical` on the bars of a
:class:`~investinglab.domain.series.PriceSeries`: the same RSI for ``SAN.MC``, ``^GSPC``,
``EURUSD=X`` and ``BTC/USDT``. An indicator that needs a column the series does not have
(the volume of a currency pair, the highs and lows of a series of closes) is left out with
the reason, never computed from substitutes.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

import pandas as pd

from investinglab.analytics.technical import CATALOGUE, compute
from investinglab.domain.errors import DomainError
from investinglab.domain.series import PriceField

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from investinglab.domain.instruments import Instrument
    from investinglab.domain.series import DataSource, PriceSeries
    from investinglab.domain.time import Frequency

__all__ = ["TechnicalIndicators", "technical_indicators"]

_COLUMNS = (PriceField.HIGH, PriceField.LOW, PriceField.CLOSE, PriceField.VOLUME)


@dataclass(frozen=True, slots=True, eq=False)
class TechnicalIndicators:
    """Indicator values on the bars of one price series.

    Args:
        instrument: The instrument measured.
        frequency: Frequency of the bars.
        source: Provenance of the bars.
        data: One column per indicator, on the index of the bars (``NaN`` in warm-up).
        parameters: Parameters used for each indicator.
        unavailable: Indicators left out and why (a price column the series lacks).
    """

    instrument: Instrument
    frequency: Frequency
    source: DataSource
    data: InitVar[pd.DataFrame]
    parameters: Mapping[str, Mapping[str, float]]
    unavailable: Mapping[str, str] = field(default_factory=dict)
    _values: pd.DataFrame = field(init=False, repr=False)

    def __post_init__(self, data: pd.DataFrame) -> None:
        unknown = sorted(set(data.columns) - set(CATALOGUE))
        if unknown:
            raise DomainError(f"Unknown indicators {unknown}")
        if set(data.columns) != set(self.parameters):
            raise DomainError("Every indicator needs its parameters, and only those")
        object.__setattr__(self, "_values", data.copy())
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType({k: MappingProxyType(dict(v)) for k, v in self.parameters.items()}),
        )
        object.__setattr__(self, "unavailable", MappingProxyType(dict(self.unavailable)))

    @property
    def values(self) -> pd.DataFrame:
        """A copy of the values: one column per indicator."""
        return self._values.copy()

    @property
    def names(self) -> tuple[str, ...]:
        """The indicators computed, in catalogue order."""
        return tuple(self._values.columns)

    def threshold(self, name: str) -> tuple[float, float] | None:
        """Range of meaningful thresholds of an oscillator; ``None`` for a price level.

        Raises:
            KeyError: If ``name`` was not computed.
        """
        if name not in self._values.columns:
            raise KeyError(f"{name} was not computed")
        return CATALOGUE[name].threshold

    def __getitem__(self, name: str) -> pd.Series:
        return self._values[name].copy()

    def latest(self) -> dict[str, float | None]:
        """The value of each indicator on the last bar (``None`` while still warming up)."""
        if self._values.empty:
            return dict.fromkeys(self.names)
        last = self._values.iloc[-1]
        return {name: (None if pd.isna(last[name]) else float(last[name])) for name in self.names}

    def between(
        self, start: pd.Timestamp | str | None = None, end: pd.Timestamp | str | None = None
    ) -> TechnicalIndicators:
        """The values of the bars in ``[start, end]`` (both inclusive), computed on all of them.

        Cutting after computing keeps the indicators warm at ``start``.
        """
        return TechnicalIndicators(
            self.instrument,
            self.frequency,
            self.source,
            self._values.loc[start:end],
            self.parameters,
            self.unavailable,
        )


def technical_indicators(
    series: PriceSeries,
    names: Iterable[str] | None = None,
    parameters: Mapping[str, Mapping[str, float]] | None = None,
) -> TechnicalIndicators:
    """Evaluate the catalogue (or ``names`` from it) on the bars of ``series``.

    Indicators read the high, low and close as traded (split-adjusted when the provider
    adjusts them) and the volume; ``adj_close`` is not used, so that every price column
    shares one adjustment.

    Args:
        series: The bars.
        names: Indicators to compute; the whole catalogue by default.
        parameters: Parameters by indicator; each one's defaults otherwise.

    Raises:
        DomainError: An unknown indicator, or parameters for one not requested or invalid.
    """
    wanted = list(CATALOGUE) if names is None else list(dict.fromkeys(names))
    unknown = sorted(set(wanted) - set(CATALOGUE))
    if unknown:
        raise DomainError(f"Unknown indicators {unknown}; known: {sorted(CATALOGUE)}")
    overrides = dict(parameters or {})
    stray = sorted(set(overrides) - set(wanted))
    if stray:
        raise DomainError(f"Parameters for indicators not requested: {stray}")
    bars = series.bars
    available = {column.value: bars[column] for column in _COLUMNS if column in bars.columns}
    values: dict[str, pd.Series] = {}
    used: dict[str, dict[str, float]] = {}
    unavailable: dict[str, str] = {}
    for name in wanted:
        indicator = CATALOGUE[name]
        missing = sorted(c.value for c in indicator.columns if c.value not in available)
        if missing:
            unavailable[name] = f"the series has no {', '.join(missing)}"
            continue
        chosen = {**indicator.defaults, **overrides.get(name, {})}
        try:
            values[name] = compute(name, available, **chosen)
        except ValueError as error:
            raise DomainError(f"{name}: {error}") from error
        used[name] = chosen
    return TechnicalIndicators(
        instrument=series.instrument,
        frequency=series.frequency,
        source=series.source,
        data=pd.DataFrame(values, index=bars.index),
        parameters=used,
        unavailable=unavailable,
    )
