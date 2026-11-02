"""Charts of Monte Carlo results: fan chart of paths and terminal-value distribution."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from investinglab.reporting.diagnostics import level_label
from investinglab.reporting.i18n import Language, Translator
from investinglab.reporting.theme import (
    SEQUENTIAL_BLUE,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    style_axes,
    style_figure,
)

if TYPE_CHECKING:
    from investinglab.domain.simulation import SimulationResult

__all__ = ["simulation_figure"]


def simulation_figure(
    result: SimulationResult,
    *,
    level: float = 0.95,
    sample_paths: int = 40,
    bins: int = 60,
    title: str | None = None,
    language: Language | str = Language.ES,
) -> Figure:
    """Fan chart of simulated values and histogram of terminal values.

    Left: 5-95 % and 25-75 % percentile bands, the median path, a few sample paths and
    the initial value. Right: distribution of terminal values with the median, the VaR
    and the CVaR thresholds at ``level`` labelled directly.

    Args:
        result: Simulation to plot.
        level: Confidence level of the VaR/CVaR markers.
        sample_paths: Number of individual paths drawn in the background.
        bins: Histogram bins.
        title: Figure title (defaults to a description of the simulation).
        language: ``es`` (default) or ``en``.
    """
    tr = Translator(language)
    config = result.config
    initial = config.initial_value
    figure = Figure(figsize=(13, 5), layout="constrained")
    fan, hist = figure.subplots(1, 2, gridspec_kw={"width_ratios": [3, 2]})
    style_figure(figure)

    # ── Fan chart ──
    bands = result.percentile_paths((5, 25, 50, 75, 95))
    steps = bands.index.to_numpy()
    samples = result.sample_paths(sample_paths)
    fan.plot(steps, samples.to_numpy(), color=TEXT_SECONDARY, linewidth=0.6, alpha=0.15)
    fan.fill_between(
        steps,
        bands["p5"],
        bands["p95"],
        color=SEQUENTIAL_BLUE[150],
        linewidth=0,
        label=tr.text("chart.simulation.outer"),
    )
    fan.fill_between(
        steps,
        bands["p25"],
        bands["p75"],
        color=SEQUENTIAL_BLUE[300],
        linewidth=0,
        label=tr.text("chart.simulation.inner"),
    )
    fan.plot(
        steps,
        bands["p50"],
        color=SEQUENTIAL_BLUE[600],
        linewidth=2,
        label=tr.text("chart.simulation.median"),
    )
    fan.axhline(
        initial,
        color=TEXT_SECONDARY,
        linewidth=1,
        linestyle="--",
        label=tr.text("chart.simulation.initial"),
    )
    style_axes(fan, title=tr.text("chart.simulation.paths"))
    fan.set_xlabel(tr.text("chart.simulation.ahead"))
    fan.set_ylabel(tr.text("chart.simulation.value"))
    fan.yaxis.set_major_formatter(FuncFormatter(lambda value, _: tr.number(value, 0)))
    fan.set_xlim(steps[0], steps[-1])
    legend = fan.legend(loc="upper left", frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(TEXT_PRIMARY)

    # ── Terminal distribution ──
    terminal = result.terminal_values
    hist.hist(terminal, bins=bins, color=SEQUENTIAL_BLUE[250], edgecolor="white", linewidth=0.5)
    var = result.value_at_risk(level)
    cvar = result.conditional_value_at_risk(level)
    label = level_label(level, tr)
    # CVaR lies left of VaR: its label hangs to the left of its line and the VaR label to
    # the right, one step lower, so neither collides however close the thresholds are.
    markers = (
        (float(np.median(terminal)), ":", tr.text("chart.simulation.median"), "left", 0.97),
        (
            initial * (1 - var.value),
            "-",
            tr.text("chart.simulation.var", level=label),
            "left",
            0.80,
        ),
        (
            initial * (1 - cvar.value),
            "--",
            tr.text("chart.simulation.cvar", level=label),
            "right",
            0.97,
        ),
    )
    top = hist.get_ylim()[1]
    for position, style, text, align, height in markers:
        hist.axvline(position, color=TEXT_PRIMARY, linewidth=1.2, linestyle=style)
        pad = " " if align == "left" else ""
        tail = "" if align == "left" else " "
        hist.text(
            position,
            top * height,
            f"{pad}{text}{tail}\n{pad}{tr.number(position, 0)}{tail}",
            color=TEXT_PRIMARY,
            fontsize=8,
            va="top",
            ha=align,
            bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85, "pad": 1.5},
        )
    style_axes(hist, title=tr.text("chart.simulation.terminal"))
    hist.set_xlabel(tr.text("chart.simulation.value"))
    hist.set_ylabel(tr.text("chart.simulation.count"))
    hist.xaxis.set_major_formatter(FuncFormatter(lambda value, _: tr.number(value, 0)))

    figure.suptitle(
        title
        or tr.text(
            "chart.simulation.title",
            model=tr.text(f"model_short.{config.model.value}"),
            paths=tr.integer(result.n_paths),
            horizon=tr.plural("count.periods", result.horizon),
            loss=tr.percent(result.probability_of_loss),
        ),
        color=TEXT_PRIMARY,
        fontsize=12,
        x=0.01,
        ha="left",
    )
    return figure
