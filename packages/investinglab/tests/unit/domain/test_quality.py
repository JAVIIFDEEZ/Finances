from __future__ import annotations

import pandas as pd
import pytest

from investinglab.domain import (
    EXCHANGES,
    Frequency,
    IssueKind,
    PriceAdjustment,
    PriceSeries,
    QualityThresholds,
    Severity,
    assess_quality,
)
from support.factories import SYNTHETIC_SOURCE, gbm_prices, make_instrument, make_series

INDEX = pd.bdate_range("2022-01-03", periods=600)


def _clean() -> PriceSeries:
    return make_series(gbm_prices(len(INDEX), seed=21), index=INDEX)


def test_a_clean_long_series_has_no_issues() -> None:
    report = _clean().quality(expected_sessions=INDEX)

    assert report.issues == ()
    assert report.ok
    assert report.worst_severity is None
    assert report.expected_sessions == len(INDEX)
    assert report.summary() == "TEST.MC: no data-quality issues"
    assert report.to_frame().empty


def test_outliers_are_flagged_not_removed() -> None:
    prices = gbm_prices(len(INDEX), seed=21)
    prices[300:] *= 1.6  # a 60 % jump in one session
    series = make_series(prices, index=INDEX)

    report = series.quality()

    (issue,) = report.issues_of(IssueKind.OUTLIER_RETURNS)
    assert issue.severity is Severity.WARNING
    assert issue.timestamps == (INDEX[300],)
    assert len(series) == len(INDEX)  # nothing was removed


@pytest.mark.parametrize(
    ("adjusted", "severity"),
    [(False, Severity.CRITICAL), (True, Severity.WARNING)],
)
def test_split_like_jumps(adjusted: bool, severity: Severity) -> None:
    prices = gbm_prices(len(INDEX), seed=22)
    prices[200:] /= 4  # looks like an unadjusted 4:1 split
    data = pd.DataFrame({"close": prices}, index=INDEX)
    adjustment = PriceAdjustment.SPLITS if adjusted else PriceAdjustment.RAW
    series = PriceSeries(make_instrument(), Frequency.DAY_1, SYNTHETIC_SOURCE, data, adjustment)

    report = series.quality()

    (issue,) = report.issues_of(IssueKind.SUSPECTED_SPLIT)
    assert issue.severity is severity
    assert issue.timestamps == (INDEX[200],)
    assert report.worst_severity is severity
    assert not report.ok


def test_stale_prices_ohlc_and_zero_volume() -> None:
    prices = gbm_prices(len(INDEX), seed=23)
    prices[100:110] = prices[100]
    series = make_series(prices, index=INDEX, ohlc=True, volume=[0] * 3 + [1] * 597)
    bars = series.bars
    bars.loc[INDEX[50], "high"] = bars["low"].iloc[50] * 0.5
    series = series.with_bars(bars)

    report = series.quality()

    kinds = {issue.kind for issue in report.issues}
    assert {IssueKind.STALE_PRICES, IssueKind.OHLC_INCONSISTENT, IssueKind.ZERO_VOLUME} <= kinds
    assert report.issues_of(IssueKind.ZERO_VOLUME)[0].severity is Severity.INFO
    assert report.issues[-1].severity is Severity.INFO  # sorted most severe first
    frame = report.to_frame()
    assert set(frame["kind"]) == {k.value for k in kinds}
    assert "runs of identical prices" in report.summary()


def test_missing_and_unexpected_sessions() -> None:
    observed = pd.DatetimeIndex(
        INDEX.delete(range(10, 30)).append(pd.DatetimeIndex(["2022-01-08"]))
    ).sort_values()
    series = make_series(gbm_prices(len(observed), seed=24), index=observed)

    report = series.quality(expected_sessions=INDEX)

    (missing,) = report.issues_of(IssueKind.MISSING_SESSIONS)
    assert missing.count == 20
    assert missing.severity is Severity.WARNING
    (extra,) = report.issues_of(IssueKind.UNEXPECTED_SESSIONS)
    assert extra.timestamps == (pd.Timestamp("2022-01-08"),)


def test_a_few_missing_sessions_are_informational() -> None:
    observed = INDEX.delete([100])
    series = make_series(gbm_prices(len(observed), seed=25), index=observed)

    report = series.quality(expected_sessions=INDEX)

    assert report.issues_of(IssueKind.MISSING_SESSIONS)[0].severity is Severity.INFO
    assert report.ok


def test_short_history() -> None:
    report = make_series(gbm_prices(60, seed=26), index=INDEX[:60]).quality()

    (issue,) = report.issues_of(IssueKind.SHORT_HISTORY)
    assert issue.count == 0
    assert "years of history" in issue.message


def test_thresholds_are_configurable() -> None:
    prices = gbm_prices(len(INDEX), seed=27)
    prices[300:] *= 1.2
    series = make_series(prices, index=INDEX)

    strict = assess_quality(series, thresholds=QualityThresholds(outlier_zscore=3.0))
    lenient = assess_quality(series, thresholds=QualityThresholds(outlier_zscore=50.0))

    assert strict.issues_of(IssueKind.OUTLIER_RETURNS)
    assert not lenient.issues_of(IssueKind.OUTLIER_RETURNS)


def test_intraday_series_are_checked_by_session_date() -> None:
    days = pd.bdate_range("2024-03-04", periods=6)
    index = pd.DatetimeIndex([])
    for day in days.delete(2):
        index = pd.DatetimeIndex(
            index.append(
                pd.date_range(day + pd.Timedelta(hours=15), periods=2, freq="1h", tz="UTC")
            )
        )
    series = make_series(
        gbm_prices(len(index), seed=28),
        index=index,
        frequency=Frequency.HOUR_1,
        exchange=EXCHANGES["XNYS"],
    )

    report = series.quality(expected_sessions=days)

    assert report.issues_of(IssueKind.MISSING_SESSIONS)[0].timestamps == (days[2],)
