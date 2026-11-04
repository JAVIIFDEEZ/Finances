"""Chart of the efficient frontier (ADR-0023)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from investinglab.reporting.i18n import Language, Translator
from investinglab.reporting.theme import (
    BASELINE,
    CATEGORICAL,
    MUTED,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    style_axes,
    style_figure,
)

if TYPE_CHECKING:
    from investinglab.domain.optimization import EfficientFrontier

__all__ = ["frontier_figure"]

_MAX_LABELLED_HOLDINGS = 12


def frontier_figure(
    frontier: EfficientFrontier,
    *,
    title: str | None = None,
    language: Language | str = Language.ES,
) -> Figure:
    """Risk-return chart: the frontier, each holding, both optimal portfolios and the CML.

    Holdings are labelled directly (up to twelve); the minimum-variance and the maximum
    Sharpe portfolios get their own markers, and the capital market line joins the
    risk-free rate with the tangency portfolio.

    Args:
        frontier: Frontier to plot.
        title: Figure title (``Efficient frontier`` by default).
        language: ``es`` (default) or ``en``.
    """
    tr = Translator(language)
    figure = Figure(figsize=(10.5, 6), layout="constrained")
    axes = figure.subplots()
    style_figure(figure)
    style_axes(axes, title=title or tr.text("chart.frontier.title"))
    points, assets = frontier.points, frontier.assets

    axes.plot(
        points["volatility"],
        points["expected_return"],
        color=CATEGORICAL[0],
        linewidth=2,
        label=tr.text("chart.frontier.curve"),
        zorder=2,
    )
    axes.scatter(
        assets["volatility"],
        assets["expected_return"],
        s=40,
        color=MUTED,
        edgecolors=SURFACE,
        linewidths=1.5,
        label=tr.text("chart.frontier.holdings"),
        zorder=3,
    )
    if len(assets) <= _MAX_LABELLED_HOLDINGS:
        for symbol, row in assets.iterrows():
            axes.annotate(
                str(symbol),
                (float(row["volatility"]), float(row["expected_return"])),
                xytext=(6, 4),
                textcoords="offset points",
                fontsize=8,
                color=TEXT_SECONDARY,
            )
    minimum = frontier.minimum_variance
    axes.scatter(
        [minimum.volatility],
        [minimum.expected_return],
        s=90,
        marker="D",
        color=CATEGORICAL[2],
        edgecolors=SURFACE,
        linewidths=1.5,
        label=tr.text("chart.frontier.minimum"),
        zorder=4,
    )
    returns = [*points["expected_return"], *assets["expected_return"]]
    right = 1.05 * max([*points["volatility"], *assets["volatility"]])
    best = frontier.maximum_sharpe
    if best is not None:
        risk_free = frontier.config.risk_free_rate
        axes.plot(
            [0.0, right],
            [risk_free, risk_free + best.sharpe_ratio * right],
            color=BASELINE,
            linestyle="--",
            linewidth=1.2,
            label=tr.text("chart.frontier.cml"),
            zorder=1,
        )
        axes.scatter(
            [best.volatility],
            [best.expected_return],
            s=160,
            marker="*",
            color=CATEGORICAL[1],
            edgecolors=SURFACE,
            linewidths=1.0,
            label=tr.text("chart.frontier.sharpe"),
            zorder=5,
        )
        returns.append(risk_free)
    low, high = min(returns), max(returns)
    margin = 0.1 * (high - low) or 0.01
    axes.set_xlim(0.0, right)
    axes.set_ylim(low - margin, high + margin)
    axes.set_xlabel(tr.text("chart.frontier.x"))
    axes.set_ylabel(tr.text("chart.frontier.y"))
    percent = FuncFormatter(lambda value, _: tr.percent(value, 0))
    axes.xaxis.set_major_formatter(percent)
    axes.yaxis.set_major_formatter(percent)
    # Outside the plot: the holdings can sit anywhere, so no corner is reliably empty.
    legend = axes.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(TEXT_PRIMARY)
    return figure
