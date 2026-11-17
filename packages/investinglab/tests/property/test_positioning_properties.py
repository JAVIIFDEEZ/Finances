"""Properties of positioning snapshots read at a coarser frequency (SYNTHETIC values).

Whatever the snapshots and the gaps between them, a coarser series only holds values that
were published: the last of each period, never one carried into an empty period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.domain import (
    USD,
    AssetClass,
    Frequency,
    PositioningField,
    PositioningSeries,
)
from support.factories import SYNTHETIC_SOURCE, make_instrument

SWAP = make_instrument("BTC/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
GRID = pd.date_range("2026-11-16", periods=288, freq="5min", tz="UTC")  # one day
OI = PositioningField.OPEN_INTEREST.value


@st.composite
def snapshots(draw: st.DrawFn) -> PositioningSeries:
    kept = draw(st.lists(st.booleans(), min_size=len(GRID), max_size=len(GRID)))
    if not any(kept):
        kept[0] = True
    values = draw(
        st.lists(
            st.floats(min_value=0, max_value=1e9, allow_nan=False),
            min_size=len(GRID),
            max_size=len(GRID),
        )
    )
    index = GRID[np.array(kept)]
    frame = pd.DataFrame({OI: np.array(values)[np.array(kept)]}, index=index)
    return PositioningSeries(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.MINUTE_5, frame)


COARSER = st.sampled_from(
    [Frequency.MINUTE_15, Frequency.MINUTE_30, Frequency.HOUR_1, Frequency.HOUR_4, Frequency.DAY_1]
)


@settings(max_examples=60, deadline=None)
@given(snapshots(), COARSER)
def test_a_coarser_series_only_holds_published_values(
    series: PositioningSeries, frequency: Frequency
) -> None:
    coarse = series.resample(frequency).column(OI)
    fine = series.column(OI)

    for label, value in coarse.items():
        start = pd.Timestamp(label)  # type: ignore[arg-type]  # a time index: labels are instants
        period = fine.loc[
            start : start + pd.Timedelta(frequency.pandas_rule) - pd.Timedelta(1, "ns")
        ]
        assert len(period) > 0  # a period without snapshots is absent
        assert value == period.iloc[-1]  # its value is its last snapshot


@settings(max_examples=40, deadline=None)
@given(snapshots(), COARSER)
def test_reading_coarser_twice_changes_nothing(
    series: PositioningSeries, frequency: Frequency
) -> None:
    once = series.resample(frequency)

    assert once.resample(frequency) == once
    assert len(once) <= len(series)
