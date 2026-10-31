from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from investinglab.domain import EconomicSeries, Frequency, InvalidSeriesError
from support.factories import SYNTHETIC_SOURCE

if TYPE_CHECKING:
    from collections.abc import Callable


def _unrate(rows: list[tuple[str, str, float]]) -> EconomicSeries:
    data = pd.DataFrame(rows, columns=["observation_date", "published_at", "value"])
    data["observation_date"] = pd.to_datetime(data["observation_date"])
    data["published_at"] = pd.to_datetime(data["published_at"])
    return EconomicSeries(
        series_id="UNRATE",
        title="Unemployment Rate (synthetic)",
        units="Percent",
        frequency=Frequency.MONTH_1,
        source=SYNTHETIC_SOURCE,
        data=data,
        seasonal_adjustment="SA",
    )


# January is first published on Feb 5 (3.5) and revised on Mar 7 (3.6).
# February is first published on Mar 7 (3.8).
REVISED = [
    ("2024-01-01", "2024-02-05", 3.5),
    ("2024-01-01", "2024-03-07", 3.6),
    ("2024-02-01", "2024-03-07", 3.8),
]


def test_first_release_and_latest_vintage() -> None:
    series = _unrate(REVISED)

    assert series.first_release().tolist() == [3.5, 3.8]
    assert series.latest().tolist() == [3.6, 3.8]
    assert series.has_revisions
    assert len(series) == 2


def test_as_of_reconstructs_what_was_known_on_a_date() -> None:
    series = _unrate(REVISED)

    assert series.as_of("2024-03-01").to_dict() == {pd.Timestamp("2024-01-01"): 3.5}
    assert series.as_of("2024-03-07").tolist() == [3.6, 3.8]
    assert series.as_of("2024-01-31").empty


def test_known_values_at_never_look_ahead() -> None:
    series = _unrate(REVISED)
    dates = pd.DatetimeIndex(["2024-03-08", "2024-02-01", "2024-02-05", "2024-03-06"])

    values = series.known_values_at(dates)

    assert values.index.equals(dates)
    assert values.loc["2024-02-01"].item() != values.loc["2024-02-01"].item()  # NaN: unknown
    assert values.loc["2024-02-05"].item() == 3.5
    assert values.loc["2024-03-06"].item() == 3.5  # the revision is not public yet
    assert values.loc["2024-03-08"].item() == 3.8  # latest observation once published


def test_observations_accessor_is_a_copy() -> None:
    series = _unrate(REVISED)

    frame = series.observations
    frame.loc[0, "value"] = 99.0

    assert series.first_release().iloc[0] == 3.5
    assert "UNRATE" in repr(series)
    assert not _unrate(REVISED[:1]).has_revisions


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d.drop(columns=["published_at"]), "missing columns"),
        (lambda d: d.assign(extra=1), "unknown columns"),
        (lambda d: d.iloc[0:0], "at least one observation"),
        (lambda d: d.assign(value=[1.0, math.nan, 2.0]), "non-finite"),
        (lambda d: d.assign(value=["a", "b", "c"]), "numeric"),
        (
            lambda d: d.assign(published_at=d["published_at"].dt.tz_localize("UTC")),
            "timezone-naive",
        ),
        (lambda d: d.assign(observation_date=["2024-01-01", "2024-02-01", "x"]), "datetime64"),
        (lambda d: d.assign(published_at=d["published_at"] + pd.Timedelta(hours=9)), "midnight"),
        (
            lambda d: d.assign(published_at=pd.DatetimeIndex([pd.NaT, "2024-03-07", "2024-03-07"])),
            "missing dates",
        ),
        (lambda d: pd.concat([d, d.iloc[:1]]), "duplicated"),
    ],
)
def test_invalid_observations_are_rejected(
    mutate: Callable[[pd.DataFrame], pd.DataFrame], fragment: str
) -> None:
    data = pd.DataFrame(REVISED, columns=["observation_date", "published_at", "value"])
    data["observation_date"] = pd.to_datetime(data["observation_date"])
    data["published_at"] = pd.to_datetime(data["published_at"])

    with pytest.raises(InvalidSeriesError, match=fragment):
        EconomicSeries("UNRATE", "x", "Percent", Frequency.MONTH_1, SYNTHETIC_SOURCE, mutate(data))


def test_non_dataframe_is_rejected() -> None:
    with pytest.raises(InvalidSeriesError):
        EconomicSeries("X", "x", "u", Frequency.DAY_1, SYNTHETIC_SOURCE, [1, 2])  # type: ignore[arg-type]


def test_between_filters_observations_and_keeps_vintages() -> None:
    series = _unrate(REVISED)

    january = series.between("2024-01-01", "2024-01-31")

    assert january.first_release().tolist() == [3.5]
    assert january.has_revisions
    assert january.title == series.title
    assert series.between(start="2024-02-01").latest().tolist() == [3.8]
    with pytest.raises(InvalidSeriesError):
        series.between("2025-01-01")
