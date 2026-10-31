"""Economic (macro) series with point-in-time semantics.

Macroeconomic figures are *revised* after their first publication, and they are published
some time after the period they measure. Using today's revised value as if it had been known
at the time introduces look-ahead bias. :class:`EconomicSeries` therefore stores
**bitemporal** data (ADR-0009): for each observation date, every published vintage with its
publication date (FRED/ALFRED ``realtime_start``).
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.domain.errors import InvalidSeriesError

if TYPE_CHECKING:
    from datetime import date, datetime

    from investinglab.domain.series import DataSource
    from investinglab.domain.time import Frequency

__all__ = ["EconomicSeries"]

_COLUMNS: Final = ("observation_date", "published_at", "value")


def _date_column_problem(values: pd.Series, column: str) -> str | None:
    if not pd.api.types.is_datetime64_any_dtype(values):
        return f"{column!r} must be datetime64, got {values.dtype}"
    if getattr(values.dt, "tz", None) is not None:
        return f"{column!r} must be timezone-naive dates"
    if values.isna().any():
        return f"{column!r} has missing dates"
    if not (values == values.dt.normalize()).all():
        return f"{column!r} must be dates at midnight"
    return None


def _validated_observations(data: object, subject: str) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame):
        raise InvalidSeriesError(subject, [f"observations must be a DataFrame, got {type(data)}"])
    problems: list[str] = []
    missing = [c for c in _COLUMNS if c not in data.columns]
    extra = [str(c) for c in data.columns if c not in _COLUMNS]
    if missing:
        problems.append(f"missing columns {missing}")
    if extra:
        problems.append(f"unknown columns {extra}")
    if data.empty:
        problems.append("at least one observation is required")
    if problems:
        raise InvalidSeriesError(subject, problems)

    frame = data.loc[:, list(_COLUMNS)].reset_index(drop=True)
    for column in ("observation_date", "published_at"):
        problem = _date_column_problem(frame[column], column)
        if problem:
            problems.append(problem)
    value = frame["value"]
    if not pd.api.types.is_numeric_dtype(value) or pd.api.types.is_bool_dtype(value):
        problems.append(f"'value' must be numeric, got {value.dtype}")
    elif not np.isfinite(value.astype("float64")).all():
        problems.append("'value' has missing or non-finite numbers; drop unpublished points")
    if problems:
        raise InvalidSeriesError(subject, problems)

    if frame.duplicated(subset=["observation_date", "published_at"]).any():
        raise InvalidSeriesError(
            subject, ["duplicated (observation_date, published_at) pairs: one value per vintage"]
        )
    frame["value"] = frame["value"].astype("float64")
    return frame.sort_values(["observation_date", "published_at"], ignore_index=True)


@dataclass(frozen=True, slots=True, eq=False)
class EconomicSeries:
    """A bitemporal macroeconomic series (e.g. FRED/ALFRED).

    Args:
        series_id: Provider identifier (``DGS3MO``, ``UNRATE``, ``CPIAUCSL``...).
        title: Human-readable title.
        units: Units as published (``Percent``, ``Index 1982-1984=100``...).
        frequency: Observation frequency.
        source: Provenance.
        data: Long-format observations with columns ``observation_date`` (period measured),
            ``published_at`` (date the value became public) and ``value``. One row per
            published vintage of each observation.
        seasonal_adjustment: Optional seasonal-adjustment label (``SA``, ``NSA``...).
    """

    series_id: str
    title: str
    units: str
    frequency: Frequency
    source: DataSource
    data: InitVar[pd.DataFrame]
    seasonal_adjustment: str | None = None
    _observations: pd.DataFrame = field(init=False, repr=False)

    def __post_init__(self, data: pd.DataFrame) -> None:
        object.__setattr__(self, "_observations", _validated_observations(data, self.series_id))

    @property
    def observations(self) -> pd.DataFrame:
        """All vintages in long format, sorted by observation and publication date."""
        return self._observations.copy(deep=False)

    @property
    def has_revisions(self) -> bool:
        """Whether any observation has more than one published vintage."""
        return bool(self._observations["observation_date"].duplicated().any())

    def first_release(self) -> pd.Series:
        """The value first published for each observation (what the market saw first)."""
        first = self._observations.drop_duplicates("observation_date", keep="first")
        return self._as_series(first)

    def latest(self) -> pd.Series:
        """The most recent vintage of each observation (fully revised, *not* point-in-time)."""
        last = self._observations.drop_duplicates("observation_date", keep="last")
        return self._as_series(last)

    def as_of(self, when: date | datetime | pd.Timestamp | str) -> pd.Series:
        """The series exactly as it could be downloaded on ``when``.

        Only vintages published on or before ``when`` are used, taking the latest of them for
        each observation date.
        """
        cutoff = pd.Timestamp(when).normalize()
        known = self._observations[self._observations["published_at"] <= cutoff]
        return self._as_series(known.drop_duplicates("observation_date", keep="last"))

    def known_values_at(self, dates: pd.DatetimeIndex) -> pd.Series:
        """Point-in-time value of the indicator at each date in ``dates``.

        For each date, the value of the most recent observation already published, in its
        latest vintage known at that date. Dates before the first publication are NaN. Use it
        to join macro data onto daily prices without look-ahead bias.
        """
        target = pd.DatetimeIndex(dates)
        events = self._observations.sort_values(["published_at", "observation_date"])
        published = events["published_at"].to_numpy()
        observed = events["observation_date"].to_numpy()
        values = events["value"].to_numpy()

        result = np.full(len(target), np.nan)
        order = np.argsort(target.to_numpy(), kind="stable")
        known: dict[np.datetime64, float] = {}
        latest_observation: np.datetime64 | None = None
        cursor = 0
        for position in order:
            moment = target[position].to_datetime64()
            while cursor < len(events) and published[cursor] <= moment:
                known[observed[cursor]] = values[cursor]
                if latest_observation is None or observed[cursor] > latest_observation:
                    latest_observation = observed[cursor]
                cursor += 1
            if latest_observation is not None:
                result[position] = known[latest_observation]
        return pd.Series(result, index=target, name=self.series_id)

    def between(
        self,
        start: date | datetime | pd.Timestamp | str | None = None,
        end: date | datetime | pd.Timestamp | str | None = None,
    ) -> EconomicSeries:
        """Sub-series with observation dates in ``[start, end]``, keeping every vintage."""
        dates = self._observations["observation_date"]
        mask = pd.Series(data=True, index=dates.index)
        if start is not None:
            mask &= dates >= pd.Timestamp(start)
        if end is not None:
            mask &= dates <= pd.Timestamp(end)
        return EconomicSeries(
            series_id=self.series_id,
            title=self.title,
            units=self.units,
            frequency=self.frequency,
            source=self.source,
            data=self._observations[mask],
            seasonal_adjustment=self.seasonal_adjustment,
        )

    def _as_series(self, frame: pd.DataFrame) -> pd.Series:
        series = pd.Series(
            frame["value"].to_numpy(),
            index=pd.DatetimeIndex(frame["observation_date"].to_numpy(), name="observation_date"),
            name=self.series_id,
        )
        return series.sort_index()

    def __len__(self) -> int:
        return int(self._observations["observation_date"].nunique())

    def __repr__(self) -> str:
        dates = self._observations["observation_date"]
        return (
            f"EconomicSeries({self.series_id}, {self.frequency.value}, "
            f"{dates.min().date()} → {dates.max().date()}, n={len(self)}, "
            f"vintages={len(self._observations)}, source={self.source.provider})"
        )
