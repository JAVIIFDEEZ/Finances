"""Point-in-time universes: who was a member on each date."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from investinglab.domain import DomainError, Membership, Universe

AS_OF = date(2026, 6, 30)


def ibex() -> Universe:
    """A small index with a member that left, one that left and came back and a newcomer."""
    return Universe(
        "Mini index",
        (
            Membership("SAN.MC", date(2020, 1, 1)),
            Membership("POP.MC", date(2020, 1, 1), date(2021, 6, 7)),  # delisted
            Membership("MEL.MC", date(2020, 1, 1), date(2022, 3, 31)),  # left…
            Membership("MEL.MC", date(2024, 1, 2)),  # …and came back
            Membership("PUIG.MC", date(2025, 5, 2)),  # listed later
        ),
        as_of=AS_OF,
    )


def test_members_are_those_of_each_date() -> None:
    universe = ibex()

    assert universe.members(date(2020, 6, 1)) == ("MEL.MC", "POP.MC", "SAN.MC")
    assert universe.members(date(2023, 1, 2)) == ("SAN.MC",)
    assert universe.members(AS_OF) == ("MEL.MC", "PUIG.MC", "SAN.MC")
    assert universe.members(date(2019, 12, 31)) == ()
    assert universe.symbols == ("MEL.MC", "POP.MC", "PUIG.MC", "SAN.MC")


def test_stays_include_their_first_and_last_day() -> None:
    universe = ibex()

    assert universe.contains("POP.MC", date(2021, 6, 7))
    assert not universe.contains("POP.MC", date(2021, 6, 8))
    assert not universe.contains("MEL.MC", date(2023, 6, 1))
    assert universe.contains("MEL.MC", date(2024, 1, 2))
    assert not universe.contains("NOPE.MC", date(2024, 1, 2))


def test_nothing_is_known_after_as_of() -> None:
    universe = ibex()

    with pytest.raises(DomainError, match="in its future"):
        universe.members(date(2026, 7, 1))
    with pytest.raises(DomainError, match="in its future"):
        universe.contains("SAN.MC", date(2027, 1, 1))
    with pytest.raises(DomainError, match="in its future"):
        universe.mask(pd.DatetimeIndex(["2026-06-30", "2026-07-01"]))


def test_the_mask_marks_each_member_on_each_date() -> None:
    days = pd.DatetimeIndex(["2020-01-02", "2021-06-07", "2021-06-08", "2023-01-02", "2025-05-02"])

    mask = ibex().mask(days)

    assert list(mask.columns) == ["MEL.MC", "POP.MC", "PUIG.MC", "SAN.MC"]
    assert mask["POP.MC"].tolist() == [True, True, False, False, False]
    assert mask["MEL.MC"].tolist() == [True, True, True, False, True]
    assert mask["PUIG.MC"].tolist() == [False, False, False, False, True]
    assert mask["SAN.MC"].all()
    assert mask.index.equals(days)


def test_the_mask_takes_intraday_instants_by_their_date() -> None:
    instants = pd.DatetimeIndex(["2021-06-07 15:30", "2021-06-08 09:00"], tz="UTC")

    mask = ibex().mask(instants)

    assert mask["POP.MC"].tolist() == [True, False]
    assert ibex().mask(pd.DatetimeIndex([])).empty


def test_survivorship_counts_who_left() -> None:
    report = ibex().survivorship(date(2020, 6, 1))

    assert report.initial == ("MEL.MC", "POP.MC", "SAN.MC")
    assert report.survivors == ("MEL.MC", "SAN.MC")  # it came back: a member on both dates
    assert report.departed == ("POP.MC",)
    assert report.attrition == pytest.approx(1 / 3)
    assert (report.start, report.end) == (date(2020, 6, 1), AS_OF)

    until_2023 = ibex().survivorship(date(2020, 6, 1), date(2023, 1, 2))
    assert until_2023.departed == ("MEL.MC", "POP.MC")
    assert math.isnan(ibex().survivorship(date(2019, 1, 1)).attrition)
    with pytest.raises(DomainError, match="before start"):
        ibex().survivorship(date(2024, 1, 1), date(2023, 1, 1))


def test_a_fixed_list_says_it_is_not_point_in_time() -> None:
    today = Universe.fixed(
        "Today's list", ["SAN.MC", "ITX.MC", "SAN.MC"], since=date(2015, 1, 1), as_of=AS_OF
    )

    assert not today.point_in_time
    assert ibex().point_in_time
    assert today.members(date(2016, 1, 1)) == ("ITX.MC", "SAN.MC")
    assert today.survivorship(date(2016, 1, 1)).attrition == 0.0  # nobody ever leaves: the bias


@pytest.mark.parametrize(
    ("memberships", "message"),
    [
        ((), "has no members"),
        (
            (
                Membership("A", date(2020, 1, 1), date(2021, 1, 1)),
                Membership("A", date(2021, 1, 1)),
            ),
            "A: overlapping stays",
        ),
        (
            (Membership("A", date(2020, 1, 1)), Membership("A", date(2022, 1, 1))),
            "overlapping stays",
        ),
        ((Membership("A", date(2027, 1, 1)),), "is after as_of"),
        ((Membership("A", date(2020, 1, 1), date(2027, 1, 1)),), "after as_of"),
    ],
    ids=["empty", "touching", "open-then-again", "starts-in-the-future", "ends-in-the-future"],
)
def test_inconsistent_universes_are_refused(
    memberships: tuple[Membership, ...], message: str
) -> None:
    with pytest.raises(DomainError, match=message):
        Universe("Broken", memberships, as_of=AS_OF)


def test_memberships_and_names_are_validated() -> None:
    with pytest.raises(DomainError, match="needs a symbol"):
        Membership(" ", date(2020, 1, 1))
    with pytest.raises(DomainError, match="before joining"):
        Membership("A", date(2020, 1, 2), date(2020, 1, 1))
    with pytest.raises(DomainError, match="needs a name"):
        Universe(" ", (Membership("A", date(2020, 1, 1)),), as_of=AS_OF)
