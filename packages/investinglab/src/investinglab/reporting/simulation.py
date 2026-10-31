"""Charts of Monte Carlo results: fan chart of paths and terminal-value distribution."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

from investinglab.reporting.theme import (
    SEQUENTIAL_BLUE,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    style_axes,
    style_figure,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure

    from investinglab.domain.simulation import SimulationResult

__all__ = ["simulation_figure"]


def _money(value: float, _: object = None) -> str:
    return f"{value:,.0f}"


def simulation_figure(
    result: SimulationResult,
    *,
    level: float = 0.95,
    sample_paths: int = 40,
    bins: int = 60,
    title: str | None = None,
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
    """
    config = result.config
    initial = config.initial_value
    figure, (fan, hist) = plt.subplots(
        1, 2, figsize=(13, 5), gridspec_kw={"width_ratios": [3, 2]}, layout="constrained"
    )
    style_figure(figure)

    # ── Fan chart ──
    bands = result.percentile_paths((5, 25, 50, 75, 95))
    steps = bands.index.to_numpy()
    samples = result.sample_paths(sample_paths)
    fan.plot(steps, samples.to_numpy(), color=TEXT_SECONDARY, linewidth=0.6, alpha=0.15)
    fan.fill_between(
        steps, bands["p5"], bands["p95"], color=SEQUENTIAL_BLUE[150], linewidth=0, label="5-95 %"
    )
    fan.fill_between(
        steps, bands["p25"], bands["p75"], color=SEQUENTIAL_BLUE[300], linewidth=0, label="25-75 %"
    )
    fan.plot(steps, bands["p50"], color=SEQUENTIAL_BLUE[600], linewidth=2, label="Median")
    fan.axhline(initial, color=TEXT_SECONDARY, linewidth=1, linestyle="--", label="Initial value")
    style_axes(fan, title="Simulated value paths")
    fan.set_xlabel("Periods ahead")
    fan.set_ylabel("Value")
    fan.yaxis.set_major_formatter(FuncFormatter(_money))
    fan.set_xlim(steps[0], steps[-1])
    legend = fan.legend(loc="upper left", frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(TEXT_PRIMARY)

    # ── Terminal distribution ──
    terminal = result.terminal_values
    hist.hist(terminal, bins=bins, color=SEQUENTIAL_BLUE[250], edgecolor="white", linewidth=0.5)
    var = result.value_at_risk(level)
    cvar = result.conditional_value_at_risk(level)
    # CVaR lies left of VaR: its label hangs to the left of its line and the VaR label to
    # the right, one step lower, so neither collides however close the thresholds are.
    markers = (
        (float(np.median(terminal)), ":", "Median", "left", 0.97),
        (initial * (1 - var.value), "-", f"VaR {level:.0%}", "left", 0.80),
        (initial * (1 - cvar.value), "--", f"CVaR {level:.0%}", "right", 0.97),
    )
    top = hist.get_ylim()[1]
    for position, style, label, align, height in markers:
        hist.axvline(position, color=TEXT_PRIMARY, linewidth=1.2, linestyle=style)
        pad = " " if align == "left" else ""
        tail = "" if align == "left" else " "
        hist.text(
            position,
            top * height,
            f"{pad}{label}{tail}\n{pad}{_money(position)}{tail}",
            color=TEXT_PRIMARY,
            fontsize=8,
            va="top",
            ha=align,
            bbox={"facecolor": SURFACE, "edgecolor": "none", "alpha": 0.85, "pad": 1.5},
        )
    style_axes(hist, title="Value at the horizon")
    hist.set_xlabel("Value")
    hist.set_ylabel("Paths")
    hist.xaxis.set_major_formatter(FuncFormatter(_money))

    figure.suptitle(
        title
        or (
            f"Monte Carlo · {config.model.value} · {result.n_paths:,} paths · "
            f"{result.horizon} periods · P(loss) {result.probability_of_loss:.1%}"
        ),
        color=TEXT_PRIMARY,
        fontsize=12,
        x=0.01,
        ha="left",
    )
    return figure
