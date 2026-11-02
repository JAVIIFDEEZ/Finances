"""The only reporting module the domain may call (lazily, ADR-0017).

``PriceSeries.report()`` and ``Portfolio.report()`` import this module inside the method, so
the domain package never loads reporting at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from investinglab.reporting.markdown import MarkdownReport
from investinglab.reporting.options import ReportOptions, ReportSettings

if TYPE_CHECKING:
    from investinglab.domain.portfolio import Portfolio
    from investinglab.domain.series import PriceSeries

__all__ = [
    "MarkdownReport",
    "ReportOptions",
    "ReportSettings",
    "portfolio_report",
    "series_report",
]


def series_report(
    series: PriceSeries, options: ReportOptions | None = None, **settings: Unpack[ReportSettings]
) -> MarkdownReport:
    """Markdown report of a series (see :mod:`investinglab.reporting.series_report`)."""
    from investinglab.reporting.series_report import build_series_report  # noqa: PLC0415

    return build_series_report(series, ReportOptions.resolve(options, settings))


def portfolio_report(
    portfolio: Portfolio,
    options: ReportOptions | None = None,
    **settings: Unpack[ReportSettings],
) -> MarkdownReport:
    """Markdown report of a portfolio (see :mod:`investinglab.reporting.portfolio_report`)."""
    from investinglab.reporting.portfolio_report import build_portfolio_report  # noqa: PLC0415

    return build_portfolio_report(portfolio, ReportOptions.resolve(options, settings))
