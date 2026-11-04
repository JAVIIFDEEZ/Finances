"""The only reporting module the domain may call (lazily, ADR-0017).

``PriceSeries.report()``, ``Portfolio.plots_report()``, ``SimulationResult.plot()``,
``EfficientFrontier.plot()`` and friends import this module inside the method, so the
domain package never loads reporting (or matplotlib) at import time. Chart functions
import matplotlib only when called, so Markdown reports work without the optional
``plots`` extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Unpack

from investinglab.reporting.markdown import MarkdownReport
from investinglab.reporting.options import ReportOptions, ReportSettings
from investinglab.reporting.plots import PlotsReport

if TYPE_CHECKING:
    from matplotlib.figure import Figure

    from investinglab.domain.optimization import EfficientFrontier
    from investinglab.domain.portfolio import Portfolio
    from investinglab.domain.series import PriceSeries
    from investinglab.domain.simulation import SimulationResult

__all__ = [
    "PLOTS_EXTRA_HINT",
    "MarkdownReport",
    "PlotsReport",
    "ReportOptions",
    "ReportSettings",
    "frontier_plot",
    "portfolio_plots",
    "portfolio_report",
    "series_plots",
    "series_report",
    "simulation_plot",
]


PLOTS_EXTRA_HINT = (
    "Charts need the optional 'plots' extra (matplotlib): "
    "uv add 'investinglab[plots]' or pip install 'investinglab[plots]'"
)


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


def series_plots(
    series: PriceSeries, options: ReportOptions | None = None, **settings: Unpack[ReportSettings]
) -> PlotsReport:
    """Charts of a series (needs the ``plots`` extra)."""
    try:
        from investinglab.reporting.charts import series_plots as build  # noqa: PLC0415
    except ModuleNotFoundError as error:
        raise ImportError(PLOTS_EXTRA_HINT) from error

    return build(series, ReportOptions.resolve(options, settings))


def portfolio_plots(
    portfolio: Portfolio,
    options: ReportOptions | None = None,
    **settings: Unpack[ReportSettings],
) -> PlotsReport:
    """Charts of a portfolio (needs the ``plots`` extra)."""
    try:
        from investinglab.reporting.charts import portfolio_plots as build  # noqa: PLC0415
    except ModuleNotFoundError as error:
        raise ImportError(PLOTS_EXTRA_HINT) from error

    return build(portfolio, ReportOptions.resolve(options, settings))


def frontier_plot(frontier: EfficientFrontier, **options: Any) -> Figure:  # noqa: ANN401
    """Risk-return chart of an efficient frontier (needs the ``plots`` extra)."""
    try:
        from investinglab.reporting.optimization import frontier_figure  # noqa: PLC0415
    except ModuleNotFoundError as error:
        raise ImportError(PLOTS_EXTRA_HINT) from error

    return frontier_figure(frontier, **options)


def simulation_plot(result: SimulationResult, **options: Any) -> Figure:  # noqa: ANN401
    """Fan chart and terminal distribution of a simulation (needs the ``plots`` extra)."""
    try:
        from investinglab.reporting.simulation import simulation_figure  # noqa: PLC0415
    except ModuleNotFoundError as error:
        raise ImportError(PLOTS_EXTRA_HINT) from error

    return simulation_figure(result, **options)
