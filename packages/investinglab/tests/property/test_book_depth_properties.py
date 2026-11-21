"""Properties of order-book depth read at coarser frequencies (SYNTHETIC values).

Whatever the snapshots and the gaps between them, a coarser series only holds whole
snapshots that were taken (never a mix of instants, never one carried into an empty period),
stays cumulative, and its imbalance is always between -1 and +1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.domain import (
    USD,
    AssetClass,
    BookDepthSeries,
    BookSide,
    DepthMeasure,
    Frequency,
)
from support.factories import SYNTHETIC_SOURCE, make_instrument

SWAP = make_instrument("BTC/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
GRID = pd.date_range("2026-11-20", periods=288, freq="5min", tz="UTC")  # one day
BANDS = (1.0, 2.0, 5.0)
Q = DepthMeasure.QUANTITY.value


@st.composite
def depth(draw: st.DrawFn) -> BookDepthSeries:
    kept = np.array(draw(st.lists(st.booleans(), min_size=len(GRID), max_size=len(GRID))))
    if not kept.any():
        kept[0] = True
    rows = int(kept.sum())
    columns = {}
    for side in BookSide:
        # Increments per band: cumulative by construction (zero is allowed).
        steps = draw(
            st.lists(
                st.lists(
                    st.floats(min_value=0, max_value=1e6, allow_nan=False),
                    min_size=len(BANDS),
                    max_size=len(BANDS),
                ),
                min_size=rows,
                max_size=rows,
            )
        )
        cumulative = np.cumsum(np.array(steps), axis=1)
        for position, band in enumerate(BANDS):
            columns[Q, side.value, band] = cumulative[:, position]
    frame = pd.DataFrame(columns, index=GRID[kept])
    frame.columns = pd.MultiIndex.from_tuples(list(columns))
    return BookDepthSeries(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.MINUTE_5, frame)


COARSER = st.sampled_from(
    [Frequency.MINUTE_15, Frequency.MINUTE_30, Frequency.HOUR_1, Frequency.HOUR_4, Frequency.DAY_1]
)


@settings(max_examples=60, deadline=None)
@given(depth(), COARSER)
def test_a_coarser_period_holds_a_whole_snapshot_that_was_taken(
    series: BookDepthSeries, frequency: Frequency
) -> None:
    coarse = series.resample(frequency)
    source = series.snapshots

    for label, row in coarse.snapshots.iterrows():
        start = pd.Timestamp(label)  # type: ignore[arg-type]
        inside = source.loc[start : start + pd.Timedelta(frequency.pandas_rule)]
        inside = inside[inside.index < start + pd.Timedelta(frequency.pandas_rule)]
        assert len(inside) > 0  # no period without a snapshot
        assert row.equals(inside.iloc[-1])  # the last one, whole


@settings(max_examples=60, deadline=None)
@given(depth(), COARSER)
def test_the_imbalance_is_bounded_and_depth_stays_cumulative(
    series: BookDepthSeries, frequency: Frequency
) -> None:
    coarse = series.resample(frequency)

    for band in BANDS:
        imbalance = coarse.imbalance(band).dropna()
        assert ((imbalance >= -1 - 1e-12) & (imbalance <= 1 + 1e-12)).all()
    for side in BookSide:
        narrow, wide = coarse.depth(side, 1.0), coarse.depth(side, 5.0)
        assert (wide >= narrow).all()
