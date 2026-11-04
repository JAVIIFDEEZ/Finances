from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import OVERNIGHT_ACT_360, DayCount, DomainError, RateConvention

BILL = RateConvention(DayCount.ACT_365, term_days=91)


def test_overnight_act_360_rates_compound_every_calendar_day() -> None:
    # 3.5 % a year on ACT/360, rolled overnight for 365 days.
    assert OVERNIGHT_ACT_360.effective_annual(0.035) == pytest.approx((1 + 0.035 / 360) ** 365 - 1)
    assert OVERNIGHT_ACT_360.effective_annual(0.035) == pytest.approx(0.036121, abs=1e-6)


def test_three_month_bills_roll_four_times_a_year() -> None:
    assert BILL.effective_annual(0.0525) == pytest.approx((1 + 0.0525 * 91 / 365) ** (365 / 91) - 1)
    assert BILL.effective_annual(0.0525) == pytest.approx(0.053543, abs=1e-6)


def test_an_annual_act_365_rate_is_already_effective() -> None:
    annual = RateConvention(DayCount.ACT_365, term_days=365)

    assert annual.effective_annual(0.04) == pytest.approx(0.04)


def test_negative_and_missing_rates() -> None:
    rates = pd.Series([-0.005, math.nan, 0.0])

    effective = OVERNIGHT_ACT_360.effective_annual(rates)

    assert isinstance(effective, pd.Series)
    assert effective.iloc[0] == pytest.approx((1 - 0.005 / 360) ** 365 - 1)
    assert np.isnan(effective.iloc[1])  # nothing is filled in
    assert effective.iloc[2] == 0.0


def test_day_count_bases() -> None:
    assert DayCount.ACT_360.year_days == 360.0
    assert DayCount("act/365").year_days == 365.0


def test_a_term_shorter_than_a_day_is_rejected() -> None:
    with pytest.raises(DomainError, match="at least one day"):
        RateConvention(term_days=0)
