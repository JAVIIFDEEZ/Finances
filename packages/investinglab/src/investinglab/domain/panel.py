"""Alignment of several price series on a common time axis without inventing data (ADR-0008).

Three uses, three treatments:

1. **Returns** are computed on each series' own calendar and then joined: a holiday on one
   market is a missing value (NaN) for that asset, never a 0 % return, and the move spanning
   the holiday is attributed to the next observed session.
2. **Observed prices** keep NaN where the market did not trade.
3. **Valuation prices** carry the last *observed* price forward (mark-to-market, as a fund's
   NAV does) and expose its age in sessions through :meth:`AlignedPanel.staleness`, so stale
   marks are always visible. They are never presented as new observations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from investinglab.analytics import simple_returns
from investinglab.domain.errors import IncompatibleSeriesError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from investinglab.domain.series import PriceSeries

__all__ = ["AlignedPanel", "AlignmentMethod", "align"]


class AlignmentMethod(StrEnum):
    """How to build the common time axis."""

    UNION = "union"
    """Every timestamp observed by at least one series (default; keeps all the data)."""
    INTERSECTION = "intersection"
    """Only timestamps observed by every series (fully synchronous, loses data)."""


@dataclass(frozen=True, slots=True, eq=False)
class AlignedPanel:
    """Several price series on a common time axis.

    Build it with :func:`align`; accessors return new objects.
    """

    method: AlignmentMethod
    _prices: pd.DataFrame = field(repr=False)
    _returns: pd.DataFrame = field(repr=False)

    @property
    def symbols(self) -> tuple[str, ...]:
        """Column labels, in input order."""
        return tuple(str(c) for c in self._prices.columns)

    @property
    def index(self) -> pd.DatetimeIndex:
        """The common time axis."""
        return pd.DatetimeIndex(self._prices.index)

    @property
    def prices(self) -> pd.DataFrame:
        """Observed prices; NaN where an asset has no observation."""
        return self._prices.copy(deep=False)

    @property
    def returns(self) -> pd.DataFrame:
        """Simple returns computed on each asset's own calendar; NaN where not observed."""
        return self._returns.copy(deep=False)

    @property
    def observed(self) -> pd.DataFrame:
        """Boolean mask: ``True`` where the asset has a real observation."""
        return self._prices.notna()

    def valuation_prices(self) -> pd.DataFrame:
        """Last observed price at each timestamp (mark-to-market).

        Values before an asset's first observation stay NaN. Combine with
        :meth:`staleness` to know how old each mark is.
        """
        return self._prices.ffill()

    def staleness(self) -> pd.DataFrame:
        """Number of timestamps since each asset's last real observation.

        ``0`` on observed timestamps, ``k`` when the valuation price is ``k`` steps old, and
        NaN before the first observation.
        """
        observed = self._prices.notna()
        positions = np.arange(len(observed), dtype="float64")
        last_seen = pd.DataFrame(
            np.where(observed.to_numpy(), positions[:, None], np.nan),
            index=observed.index,
            columns=observed.columns,
        ).ffill()
        return last_seen.rsub(positions, axis=0)

    def common_start(self) -> pd.Timestamp:
        """First timestamp at which every asset has been observed at least once."""
        first_positions = self._prices.notna().to_numpy().argmax(axis=0)
        return pd.Timestamp(self.index[int(first_positions.max())])

    def __len__(self) -> int:
        return len(self._prices)


def align(
    series: Sequence[PriceSeries],
    method: AlignmentMethod | str = AlignmentMethod.UNION,
) -> AlignedPanel:
    """Align several price series of the same frequency on a common time axis.

    Raises:
        IncompatibleSeriesError: If the input is empty, symbols are duplicated or the
            frequencies differ.
    """
    how = AlignmentMethod(method)
    problems: list[str] = []
    if not series:
        problems.append("at least one series is required")
    symbols = [s.symbol for s in series]
    duplicated = sorted({s for s in symbols if symbols.count(s) > 1})
    if duplicated:
        problems.append(f"duplicated symbols {duplicated}")
    frequencies = sorted({s.frequency.value for s in series})
    if len(frequencies) > 1:
        problems.append(f"mixed frequencies {frequencies}; resample to a common one first")
    if problems:
        raise IncompatibleSeriesError(", ".join(symbols) or "<empty>", problems)

    prices = pd.concat([s.prices for s in series], axis=1, join="outer", sort=True)
    if how is AlignmentMethod.INTERSECTION:
        prices = prices.dropna(how="any")
        if len(prices) < 2:  # noqa: PLR2004
            raise IncompatibleSeriesError(
                ", ".join(symbols), ["fewer than two common timestamps; use the union method"]
            )
    returns = simple_returns(prices).reindex(prices.index)
    return AlignedPanel(method=how, _prices=prices, _returns=returns)
