"""Chart of a savings plan: wealth fan in today's money, money put in and goal (ADR-0024)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from investinglab.domain.planning import MONTHS_PER_YEAR
from investinglab.reporting.i18n import Language, Translator
from investinglab.reporting.theme import (
    CATEGORICAL,
    SEQUENTIAL_BLUE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    style_axes,
    style_figure,
)

if TYPE_CHECKING:
    from investinglab.domain.planning import PlanResult

__all__ = ["plan_figure"]


def plan_figure(
    result: PlanResult,
    *,
    title: str | None = None,
    language: Language | str = Language.ES,
) -> Figure:
    """Fan chart of the simulated wealth in today's money.

    Shows the 5-95 % and 25-75 % percentile bands, the median path, the money put in (initial
    capital plus contributions) and, when the plan has one, the goal. The title states the
    probability of reaching it.

    Args:
        result: Simulated plan.
        title: Figure title (a description of the plan by default).
        language: ``es`` (default) or ``en``.
    """
    tr = Translator(language)
    plan = result.plan
    figure = Figure(figsize=(11, 5.5), layout="constrained")
    axes = figure.subplots()
    style_figure(figure)
    years = np.arange(plan.months + 1) / MONTHS_PER_YEAR
    bands = result.percentile_paths((5, 25, 50, 75, 95))

    axes.fill_between(
        years,
        bands["p5"],
        bands["p95"],
        color=SEQUENTIAL_BLUE[150],
        linewidth=0,
        label=tr.text("chart.plan.outer"),
    )
    axes.fill_between(
        years,
        bands["p25"],
        bands["p75"],
        color=SEQUENTIAL_BLUE[300],
        linewidth=0,
        label=tr.text("chart.plan.inner"),
    )
    axes.plot(
        years,
        bands["p50"],
        color=SEQUENTIAL_BLUE[600],
        linewidth=2,
        label=tr.text("chart.plan.median"),
    )
    axes.plot(
        years,
        result.contributed(),
        color=TEXT_SECONDARY,
        linewidth=1.2,
        linestyle="--",
        label=tr.text("chart.plan.contributed"),
    )
    if plan.goal is not None:
        axes.axhline(
            plan.goal,
            color=CATEGORICAL[1],
            linewidth=1.5,
            label=tr.text("chart.plan.goal"),
        )

    horizon = (
        tr.plural("count.years", plan.months // MONTHS_PER_YEAR)
        if plan.months % MONTHS_PER_YEAR == 0
        else tr.plural("count.months", plan.months)
    )
    probability = result.probability_of_success
    default_title = (
        tr.text("chart.plan.title_no_goal", horizon=horizon)
        if probability is None
        else tr.text("chart.plan.title", horizon=horizon, probability=tr.percent(probability, 0))
    )
    style_axes(axes, title=title or default_title)
    axes.set_xlabel(tr.text("chart.plan.x"))
    axes.set_ylabel(tr.text("chart.plan.y", currency=result.currency))
    axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: tr.number(value, 0)))
    axes.set_xlim(0.0, float(years[-1]))
    axes.set_ylim(bottom=0.0)
    legend = axes.legend(loc="upper left", frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(TEXT_PRIMARY)
    return figure
