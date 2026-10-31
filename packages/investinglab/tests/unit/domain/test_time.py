from __future__ import annotations

import pandas as pd
import pytest

from investinglab.domain import (
    CRYPTO_SCHEDULE,
    EQUITY_SCHEDULE,
    FX_SCHEDULE,
    DomainError,
    Frequency,
    MarketSchedule,
)


def test_intraday_classification() -> None:
    assert Frequency.MINUTE_1.is_intraday
    assert Frequency.HOUR_4.is_intraday
    assert not Frequency.DAY_1.is_intraday
    assert Frequency.MINUTE_15.minutes == 15
    assert Frequency.DAY_1.minutes is None


def test_frequencies_are_ordered_from_finest_to_coarsest() -> None:
    ordered = list(Frequency)

    assert ordered[0] is Frequency.MINUTE_1
    assert ordered[-1] is Frequency.YEAR_1
    assert Frequency.DAY_1.is_finer_than(Frequency.WEEK_1)
    assert not Frequency.MONTH_1.is_finer_than(Frequency.DAY_1)


@pytest.mark.parametrize("frequency", list(Frequency))
def test_every_frequency_has_a_rule_and_a_minimum_spacing(frequency: Frequency) -> None:
    assert frequency.pandas_rule
    assert frequency.min_spacing > pd.Timedelta(0)


@pytest.mark.parametrize(
    ("schedule", "frequency", "expected"),
    [
        (EQUITY_SCHEDULE, Frequency.DAY_1, 252),
        (CRYPTO_SCHEDULE, Frequency.DAY_1, 365),
        (FX_SCHEDULE, Frequency.DAY_1, 260),
        (EQUITY_SCHEDULE, Frequency.HOUR_1, 252 * 7),  # 6.5 h → 7 hourly bars
        (EQUITY_SCHEDULE, Frequency.MINUTE_1, 252 * 390),
        (CRYPTO_SCHEDULE, Frequency.HOUR_1, 365 * 24),
        (EQUITY_SCHEDULE, Frequency.WEEK_1, 52),
        (EQUITY_SCHEDULE, Frequency.MONTH_1, 12),
        (EQUITY_SCHEDULE, Frequency.QUARTER_1, 4),
        (EQUITY_SCHEDULE, Frequency.YEAR_1, 1),
    ],
)
def test_periods_per_year(schedule: MarketSchedule, frequency: Frequency, expected: float) -> None:
    assert schedule.periods_per_year(frequency) == expected


def test_continuous_markets() -> None:
    assert CRYPTO_SCHEDULE.is_continuous
    assert not EQUITY_SCHEDULE.is_continuous


@pytest.mark.parametrize(("sessions", "hours"), [(0, 6.5), (400, 6.5), (252, 0), (252, 25)])
def test_schedule_bounds(sessions: float, hours: float) -> None:
    with pytest.raises(DomainError):
        MarketSchedule(sessions, hours)
