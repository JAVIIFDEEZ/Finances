"""Positioning snapshots: validation, fields, periods (SYNTHETIC values)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    USD,
    AssetClass,
    Currency,
    DomainError,
    Frequency,
    InvalidSeriesError,
    PositioningField,
    PositioningSeries,
)
from support.factories import SYNTHETIC_SOURCE, make_instrument

SWAP = make_instrument("BTC/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
FIVE = pd.date_range("2026-11-16 00:00", periods=36, freq="5min", tz="UTC")  # three hours
OI = PositioningField.OPEN_INTEREST
VALUE = PositioningField.OPEN_INTEREST_VALUE
ACCOUNTS = PositioningField.LONG_SHORT_ACCOUNTS


def _frame(**columns: Any) -> pd.DataFrame:
    data = {
        OI.value: np.linspace(100.0, 135.0, len(FIVE)),
        ACCOUNTS.value: np.linspace(2.0, 2.35, len(FIVE)),
    }
    frame = pd.DataFrame(data, index=FIVE)
    for name, values in columns.items():
        frame[name] = values
    return frame


def _series(
    frame: pd.DataFrame | None = None, value_currency: Currency | None = None
) -> PositioningSeries:
    data = _frame() if frame is None else frame
    return PositioningSeries(
        SWAP, "venue", SYNTHETIC_SOURCE, Frequency.MINUTE_5, data, value_currency=value_currency
    )


def test_the_fields_a_venue_publishes_are_kept_in_the_vocabulary_order() -> None:
    series = _series(_frame()[[ACCOUNTS.value, OI.value]])

    assert series.fields == (OI, ACCOUNTS)
    assert len(series) == 36
    assert (series.start, series.end) == (FIVE[0], FIVE[-1])
    assert series.column(OI).iloc[-1] == pytest.approx(135.0)
    with pytest.raises(KeyError, match="publishes no top_long_short_positions"):
        series.column(PositioningField.TOP_LONG_SHORT_POSITIONS)
    assert "BTC/USDT:USDT@venue, 5m" in repr(series)


@pytest.mark.parametrize(
    ("frame", "problem"),
    [
        (_frame().tz_localize(None), "timezone-aware"),
        (_frame().iloc[::-1], "increasing time order"),
        (pd.concat([_frame().iloc[:2], _frame().iloc[:1]]), "duplicated"),
        (_frame(oi_typo=1.0), "unknown field 'oi_typo'"),
        (_frame(**{OI.value: -np.ones(len(FIVE))}), "amount: it cannot be negative"),
        (_frame(**{ACCOUNTS.value: -np.ones(len(FIVE))}), "ratio of two amounts"),
        (_frame(**{OI.value: np.full(len(FIVE), np.inf)}), "must be finite"),
        (_frame(**{OI.value: ["x"] * len(FIVE)}), "must be numeric"),
        (pd.DataFrame(index=FIVE), "at least one field"),
        (_frame()[[OI.value]].iloc[:0], "at least one snapshot"),
    ],
)
def test_snapshots_are_validated(frame: pd.DataFrame, problem: str) -> None:
    with pytest.raises(InvalidSeriesError, match=problem):
        _series(frame)


def test_a_value_needs_its_currency_and_a_venue_its_name() -> None:
    valued = _frame(**{VALUE.value: np.linspace(1e6, 2e6, len(FIVE))})

    with pytest.raises(DomainError, match="needs its currency"):
        _series(valued)
    assert _series(valued, value_currency=USD).value_currency == USD
    with pytest.raises(DomainError, match="needs the venue"):
        PositioningSeries(SWAP, " ", SYNTHETIC_SOURCE, Frequency.MINUTE_5, _frame())
    with pytest.raises(DomainError, match="not 1m"):
        PositioningSeries(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.MINUTE_1, _frame())


def test_a_missing_snapshot_stays_missing_and_empty_rows_go() -> None:
    frame = _frame()
    frame.iloc[3, 1] = np.nan  # one ratio skipped
    frame.iloc[4, :] = np.nan  # a snapshot with nothing

    series = _series(frame)

    assert len(series) == 35
    assert np.isnan(series.column(ACCOUNTS).iloc[3])
    assert series.latest() == {OI: pytest.approx(135.0), ACCOUNTS: pytest.approx(2.35)}


def test_a_coarser_period_takes_its_last_snapshot_labelled_by_its_start() -> None:
    hourly = _series().resample("1h")

    assert hourly.frequency is Frequency.HOUR_1
    assert hourly.column(OI).index.tolist() == [
        pd.Timestamp("2026-11-16 00:00", tz="UTC"),
        pd.Timestamp("2026-11-16 01:00", tz="UTC"),
        pd.Timestamp("2026-11-16 02:00", tz="UTC"),
    ]
    five = _series().column(OI)
    assert hourly.column(OI).tolist() == [five.iloc[i] for i in (11, 23, 35)]  # :55 of each hour
    assert _series().resample("5m") is not None
    with pytest.raises(DomainError, match="invent the ones in between"):
        hourly.resample("5m")
    with pytest.raises(DomainError, match="not 1w"):
        hourly.resample("1w")


def test_an_hour_without_snapshots_is_absent_not_filled() -> None:
    frame = _frame().drop(FIVE[12:24])  # the second hour never came

    hourly = _series(frame).resample("1h")

    assert len(hourly) == 2
    assert pd.Timestamp("2026-11-16 01:00", tz="UTC") not in hourly.column(OI).index


def test_only_the_periods_that_had_ended_are_kept() -> None:
    hourly = _series().resample("1h")

    at_two_thirty = hourly.finished(pd.Timestamp("2026-11-16 02:30", tz="UTC"))
    at_three = hourly.finished(pd.Timestamp("2026-11-16 03:00", tz="UTC"))

    assert len(at_two_thirty) == 2  # the 02:00 hour still changes
    assert len(at_three) == 3
    with pytest.raises(InvalidSeriesError):
        hourly.finished(pd.Timestamp("2026-11-16 00:30", tz="UTC"))


def test_fields_from_different_instants_are_aligned_without_carrying_values() -> None:
    oi = pd.Series([100.0, 101.0], index=FIVE[[0, 2]])
    ratio = pd.Series([2.0], index=FIVE[[1]])

    series = PositioningSeries.from_fields(
        SWAP, "venue", SYNTHETIC_SOURCE, Frequency.MINUTE_5, [(OI, oi), (ACCOUNTS, ratio)]
    )

    assert len(series) == 3
    assert np.isnan(series.column(ACCOUNTS).iloc[0])
    assert np.isnan(series.column(OI).iloc[1])  # never carried forward


def test_between_equality_and_hash() -> None:
    series = _series()
    part = series.between("2026-11-16 01:00", "2026-11-16 01:55")

    assert len(part) == 12
    assert series == _series()
    assert series != part
    assert hash(series) == hash(_series())
    assert series.__eq__(object()) is NotImplemented
    assert list(series.snapshots.columns) == [OI.value, ACCOUNTS.value]
