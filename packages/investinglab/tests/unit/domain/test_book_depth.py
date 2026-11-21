"""Order-book depth: validation, bands, imbalance, liquidity and periods (SYNTHETIC values)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    USD,
    AssetClass,
    BookDepthSeries,
    BookSide,
    DepthMeasure,
    DomainError,
    Frequency,
    InvalidSeriesError,
)
from support.factories import SYNTHETIC_SOURCE, make_instrument

SWAP = make_instrument("BTC/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None)
RAW = pd.date_range("2026-11-20 00:00:01", periods=360, freq="30s", tz="UTC")  # three hours
BANDS = (1.0, 2.0, 5.0)
Q, N = DepthMeasure.QUANTITY.value, DepthMeasure.NOTIONAL.value
BID, ASK = BookSide.BID.value, BookSide.ASK.value


def _raw(*, notional: bool = True, price: float = 50_000.0) -> pd.DataFrame:
    """SYNTHETIC snapshots: more resting the wider the band, bids growing over time."""
    step = np.arange(len(RAW), dtype="float64")
    columns: dict[tuple[str, str, float], np.ndarray] = {}
    for band in BANDS:
        bid = band * 100.0 + step
        ask = band * 80.0 + 0.0 * step
        columns[Q, BID, band] = bid
        columns[Q, ASK, band] = ask
        if notional:
            columns[N, BID, band] = bid * price
            columns[N, ASK, band] = ask * price
    frame = pd.DataFrame(columns, index=RAW)
    frame.columns = pd.MultiIndex.from_tuples(list(columns), names=["measure", "side", "band"])
    return frame


def _hourly(frame: pd.DataFrame | None = None) -> BookDepthSeries:
    return BookDepthSeries.from_snapshots(
        SWAP,
        "venue",
        SYNTHETIC_SOURCE,
        Frequency.HOUR_1,
        _raw() if frame is None else frame,
        notional_currency=USD,
    )


def test_the_last_snapshot_of_each_period_is_kept_labelled_by_its_start() -> None:
    depth = _hourly()

    assert len(depth) == 3
    assert list(depth.snapshots.index) == list(
        pd.date_range("2026-11-20", periods=3, freq="1h", tz="UTC")
    )
    position = RAW.searchsorted(pd.Timestamp("2026-11-20 01:00", tz="UTC")) - 1
    assert depth.depth("bid", 1.0).iloc[0] == pytest.approx(100.0 + position)
    assert depth.bands == BANDS
    assert depth.measures == (DepthMeasure.QUANTITY, DepthMeasure.NOTIONAL)
    assert "±1 %, ±2 %, ±5 %" in repr(depth)


def test_imbalance_and_liquidity_within_a_band() -> None:
    depth = _hourly()

    bid = depth.depth(BookSide.BID, 2.0)
    ask = depth.depth(BookSide.ASK, 2.0)
    imbalance = depth.imbalance(2.0)

    assert ((imbalance >= -1) & (imbalance <= 1)).all()
    assert imbalance.iloc[-1] == pytest.approx((bid.iloc[-1] - ask.iloc[-1]) / (bid + ask).iloc[-1])
    assert depth.liquidity(2.0).iloc[0] == pytest.approx((bid.iloc[0] + ask.iloc[0]) * 50_000.0)
    with pytest.raises(KeyError, match=r"no quantity of the bid side within ±3"):
        depth.depth("bid", 3.0)


def test_an_empty_band_has_no_imbalance_rather_than_a_made_up_one() -> None:
    frame = _raw()
    for side in (BID, ASK):
        frame[Q, side, 1.0] = 0.0
    depth = _hourly(frame)

    assert depth.imbalance(1.0).isna().all()


def test_without_a_notional_there_is_no_liquidity_in_money() -> None:
    depth = BookDepthSeries.from_snapshots(
        SWAP, "venue", SYNTHETIC_SOURCE, Frequency.HOUR_1, _raw(notional=False)
    )

    assert depth.measures == (DepthMeasure.QUANTITY,)
    assert depth.imbalance(1.0).notna().all()  # the quantity is enough for the imbalance
    with pytest.raises(KeyError, match="no notional"):
        depth.liquidity(1.0)


def test_depth_is_cumulative_a_wider_band_never_holds_less() -> None:
    frame = _raw()
    frame.loc[RAW[100], (Q, ASK, 5.0)] = 1.0  # less within ±5 % than within ±2 %

    # Not the last snapshot of its hour: still refused, a damaged source is not trusted.
    with pytest.raises(InvalidSeriesError, match=r"quantity of the ask side shrinks"):
        _hourly(frame.iloc[95:105])


def test_a_skipped_band_is_compared_with_the_next_narrower_one() -> None:
    frame = _raw()
    frame[Q, ASK, 2.0] = np.nan  # the venue skipped ±2 %
    frame.loc[RAW[-1], (Q, ASK, 5.0)] = 50.0  # less than within ±1 % (80)

    with pytest.raises(InvalidSeriesError, match="shrinks in a wider band"):
        _hourly(frame)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda f: f.set_axis(f.index.tz_localize(None), axis=0), "timezone-aware"),
        (lambda f: f.iloc[::-1], "increasing time order"),
        (lambda f: f.droplevel("band", axis=1), "MultiIndex"),
        (lambda f: f.rename(columns={1.0: -1.0}, level="band"), "distance in percent"),
        (lambda f: f.rename(columns={"bid": "buy"}, level="side"), "unknown side"),
        (lambda f: f.rename(columns={Q: "count"}, level="measure"), "unknown measure"),
        (lambda f: f.mul(-1.0), "cannot be negative"),
        (lambda f: f.replace(f.iloc[0, 0], np.inf), "must be finite"),
    ],
    ids=["naive", "unsorted", "flat-columns", "band", "side", "measure", "negative", "inf"],
)
def test_snapshots_are_validated(change: object, problem: str) -> None:
    hourly = _hourly().snapshots
    altered = change(hourly)  # type: ignore[operator]

    with pytest.raises(InvalidSeriesError, match=problem):
        BookDepthSeries(
            SWAP, "venue", SYNTHETIC_SOURCE, Frequency.HOUR_1, altered, notional_currency=USD
        )


def test_rows_are_labelled_by_the_start_of_their_period() -> None:
    hourly = _hourly().snapshots
    hourly.index = hourly.index + pd.Timedelta(minutes=7)

    with pytest.raises(InvalidSeriesError, match="start of its 1h period"):
        BookDepthSeries(
            SWAP, "venue", SYNTHETIC_SOURCE, Frequency.HOUR_1, hourly, notional_currency=USD
        )


def test_a_notional_needs_its_currency_a_venue_its_name_and_a_known_frequency() -> None:
    hourly = _hourly().snapshots

    with pytest.raises(DomainError, match="needs its currency"):
        BookDepthSeries(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.HOUR_1, hourly)
    with pytest.raises(DomainError, match="needs the venue"):
        BookDepthSeries(
            SWAP, " ", SYNTHETIC_SOURCE, Frequency.HOUR_1, hourly, notional_currency=USD
        )
    with pytest.raises(DomainError, match="read at"):
        BookDepthSeries(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.WEEK_1, hourly)
    with pytest.raises(DomainError, match="read at"):
        BookDepthSeries.from_snapshots(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.MINUTE_1, _raw())
    naive = _raw().set_axis(RAW.tz_localize(None), axis=0)
    with pytest.raises(InvalidSeriesError, match="timezone-aware"):
        BookDepthSeries.from_snapshots(SWAP, "venue", SYNTHETIC_SOURCE, Frequency.HOUR_1, naive)


def test_coarser_periods_take_whole_snapshots_never_mixed_instants() -> None:
    frame = _raw()
    # In the last snapshot of the third hour, the venue gave only the bids.
    frame.loc[RAW[-1], [(Q, ASK, b) for b in BANDS] + [(N, ASK, b) for b in BANDS]] = np.nan
    hourly = _hourly(frame)

    four = hourly.resample("4h")

    assert len(four) == 1
    assert four.depth("ask", 1.0).isna().all()  # not the ask of an earlier instant
    assert four.depth("bid", 1.0).iloc[0] == hourly.depth("bid", 1.0).iloc[-1]
    assert hourly.resample(Frequency.HOUR_1) is hourly
    with pytest.raises(DomainError, match="would invent"):
        four.resample("1h")
    with pytest.raises(DomainError, match="read at"):
        hourly.resample("1w")


def test_only_the_periods_that_had_ended_are_kept() -> None:
    hourly = _hourly()

    done = hourly.finished(pd.Timestamp("2026-11-20 02:30", tz="UTC"))

    assert len(done) == 2  # the hour from 02:00 is still in progress
    with pytest.raises(InvalidSeriesError):
        hourly.finished(pd.Timestamp("2026-11-20 00:59", tz="UTC"))


def test_between_equality_and_hash() -> None:
    hourly = _hourly()

    middle = hourly.between("2026-11-20 01:00", "2026-11-20 01:00")

    assert len(middle) == 1
    assert hourly == _hourly()
    assert hash(hourly) == hash(_hourly())
    assert hourly != middle
    assert hourly.__eq__(object()) is NotImplemented
