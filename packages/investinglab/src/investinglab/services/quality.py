"""Data-quality use case: diagnose series against their market's official calendar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab.config.logging import get_logger
from investinglab.domain.quality import DataQualityReport, QualityThresholds, assess_quality
from investinglab.ports.calendar import CalendarUnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pandas as pd

    from investinglab.domain.series import PriceSeries
    from investinglab.ports.calendar import TradingCalendar

__all__ = ["DataQualityService"]

log = get_logger(__name__)


class DataQualityService:
    """Builds :class:`~investinglab.domain.quality.DataQualityReport` objects.

    Args:
        calendar: Official trading calendars; without it, missing sessions are not checked.
        thresholds: Detector thresholds.
    """

    def __init__(
        self,
        calendar: TradingCalendar | None = None,
        *,
        thresholds: QualityThresholds | None = None,
    ) -> None:
        self._calendar = calendar
        self._thresholds = thresholds or QualityThresholds()

    def expected_sessions(self, series: PriceSeries) -> pd.DatetimeIndex | None:
        """Official sessions covering the series, or ``None`` when no calendar applies."""
        exchange = series.instrument.exchange
        if self._calendar is None or exchange is None:
            return None
        if not self._calendar.supports(exchange.code):
            return None
        start, end = series.start, series.end
        if series.frequency.is_intraday:
            start = start.tz_convert(series.timezone)
            end = end.tz_convert(series.timezone)
        try:
            return self._calendar.sessions(exchange.code, start.date(), end.date())
        except CalendarUnavailableError as error:
            log.info("calendar_unavailable", symbol=series.symbol, detail=str(error))
            return None

    def assess(self, series: PriceSeries) -> DataQualityReport:
        """Diagnose one series."""
        return assess_quality(
            series,
            expected_sessions=self.expected_sessions(series),
            thresholds=self._thresholds,
        )

    def assess_many(self, series: Iterable[PriceSeries]) -> dict[str, DataQualityReport]:
        """Diagnose several series, keyed by symbol."""
        return {item.symbol: self.assess(item) for item in series}
