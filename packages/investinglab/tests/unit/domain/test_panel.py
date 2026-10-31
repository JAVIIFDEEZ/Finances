from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from investinglab.domain import (
    AlignedPanel,
    AlignmentMethod,
    Frequency,
    IncompatibleSeriesError,
    PriceSeries,
    align,
)
from support.factories import make_series

if TYPE_CHECKING:
    from collections.abc import Callable

MADRID_DATES = pd.DatetimeIndex(["2024-03-26", "2024-03-27", "2024-03-28", "2024-04-02"])
NEW_YORK_DATES = pd.DatetimeIndex(
    ["2024-03-26", "2024-03-27", "2024-03-28", "2024-04-01", "2024-04-02"]
)  # Easter Monday (2024-04-01) is a holiday in Madrid, not in New York.


def _panel(method: AlignmentMethod = AlignmentMethod.UNION) -> AlignedPanel:
    san = make_series([100.0, 102.0, 101.0, 104.03], symbol="SAN.MC", index=MADRID_DATES)
    spy = make_series([50.0, 51.0, 52.0, 53.0, 54.0], symbol="SPY", index=NEW_YORK_DATES)
    return align([san, spy], method)


def test_union_keeps_every_date_and_marks_missing_observations() -> None:
    panel = _panel()

    assert list(panel.index) == list(NEW_YORK_DATES)
    assert panel.symbols == ("SAN.MC", "SPY")
    assert panel.prices["SAN.MC"].isna().loc["2024-04-01"]
    assert not panel.observed.loc["2024-04-01", "SAN.MC"]
    assert len(panel) == 5
    assert panel.method is AlignmentMethod.UNION


def test_a_holiday_is_a_missing_return_not_a_zero_return() -> None:
    returns = _panel().returns

    assert returns["SAN.MC"].isna().loc["2024-04-01"]
    # The move across the holiday is attributed to the next Madrid session.
    assert returns.loc["2024-04-02", "SAN.MC"] == pytest.approx(104.03 / 101.0 - 1)
    assert returns.loc["2024-04-01", "SPY"] == pytest.approx(53.0 / 52.0 - 1)


def test_valuation_prices_carry_the_last_observation_and_report_its_age() -> None:
    panel = _panel()

    assert panel.valuation_prices().loc["2024-04-01", "SAN.MC"] == 101.0
    staleness = panel.staleness()
    assert staleness["SAN.MC"].tolist() == [0, 0, 0, 1, 0]
    assert staleness["SPY"].tolist() == [0, 0, 0, 0, 0]


def test_staleness_is_nan_before_the_first_observation_and_common_start() -> None:
    late = make_series([10.0, 11.0, 12.0], symbol="LATE", index=NEW_YORK_DATES[2:])
    early = make_series([1.0, 2.0, 3.0, 4.0, 5.0], symbol="EARLY", index=NEW_YORK_DATES)

    panel = align([early, late])

    assert math.isnan(panel.staleness().iloc[0]["LATE"])
    assert panel.common_start() == NEW_YORK_DATES[2]


def test_intersection_keeps_only_common_dates() -> None:
    panel = _panel(AlignmentMethod.INTERSECTION)

    assert list(panel.index) == list(MADRID_DATES)
    assert not panel.prices.isna().any().any()
    assert panel.returns.loc["2024-04-02", "SPY"] == pytest.approx(54.0 / 52.0 - 1)


def test_accessors_return_copies() -> None:
    panel = _panel()

    prices = panel.prices
    prices.iloc[0, 0] = -1.0

    assert panel.prices.iloc[0, 0] == 100.0


@pytest.mark.parametrize(
    ("series_factory", "fragment"),
    [
        (list, "at least one series"),
        (lambda: [make_series(symbol="A"), make_series(symbol="A")], "duplicated symbols"),
        (
            lambda: [
                make_series(symbol="A"),
                make_series(
                    symbol="B",
                    index=pd.DatetimeIndex(
                        ["2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30", "2024-05-31"]
                    ),
                    frequency=Frequency.MONTH_1,
                ),
            ],
            "mixed frequencies",
        ),
    ],
)
def test_incompatible_series_are_rejected(
    series_factory: Callable[[], list[PriceSeries]], fragment: str
) -> None:
    with pytest.raises(IncompatibleSeriesError, match=fragment):
        align(series_factory())


def test_intersection_needs_two_common_dates() -> None:
    first = make_series(symbol="A", index=pd.bdate_range("2024-01-01", periods=5))
    second = make_series(symbol="B", index=pd.bdate_range("2024-01-05", periods=5))

    with pytest.raises(IncompatibleSeriesError, match="common timestamps"):
        align([first, second], "intersection")
