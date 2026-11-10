"""TARGET business days: the days the euro-area payment system, and €STR, operate.

TARGET is closed on weekends, New Year's Day, Good Friday, Easter Monday, 1 May,
Christmas Day and 26 December. The ECB publishes €STR for a TARGET day at 08:00 CET on the
next TARGET day, so that is the first day its value was known.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd
from pandas.tseries.holiday import AbstractHolidayCalendar, EasterMonday, GoodFriday, Holiday

__all__ = ["TargetCalendar", "next_target_days"]


class TargetCalendar(AbstractHolidayCalendar):
    """TARGET closing days besides weekends."""

    rules: Final = [  # type: ignore[misc]  # pandas declares ``rules`` as a mutable list
        Holiday("New Year's Day", month=1, day=1),
        GoodFriday,
        EasterMonday,
        Holiday("Labour Day", month=5, day=1),
        Holiday("Christmas Day", month=12, day=25),
        Holiday("Christmas Holiday", month=12, day=26),
    ]


def next_target_days(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The first TARGET business day strictly after each date."""
    if dates.empty:
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    holidays = TargetCalendar().holidays(start=dates.min(), end=dates.max() + pd.Timedelta(days=14))
    following = (dates.normalize() + pd.Timedelta(days=1)).to_numpy(dtype="datetime64[D]")
    shifted = np.busday_offset(
        following, 0, roll="forward", holidays=holidays.to_numpy(dtype="datetime64[D]")
    )
    return pd.DatetimeIndex(shifted.astype("datetime64[ns]"))
