"""Static charts of series and portfolios (``plots_report()``, B1-T1 §4.5).

Every chart has a single y-axis; magnitudes use the sequential blue ramp, identities the
fixed-order categorical palette (one colour per holding, never cycled: holdings beyond the
eighth are folded into "Others"), and correlations the red ↔ blue diverging ramp with a
neutral midpoint. Figures are created without pyplot (thread-safe, never shown twice) and
date axes use numeric formats, so the charts read the same in Spanish and English.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from investinglab.analytics import VaRMethod, value_at_risk
from investinglab.reporting.analysis import PortfolioAnalysis
from investinglab.reporting.diagnostics import level_label
from investinglab.reporting.plots import PlotsReport
from investinglab.reporting.sections import resolve_simulation
from investinglab.reporting.simulation import simulation_figure
from investinglab.reporting.theme import (
    BASELINE,
    CATEGORICAL,
    DIVERGING,
    MUTED,
    SEQUENTIAL_BLUE,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    style_axes,
    style_figure,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from investinglab.domain.portfolio import Portfolio, PortfolioBacktest
    from investinglab.domain.series import PriceSeries
    from investinglab.domain.time import Frequency
    from investinglab.reporting.i18n import Translator
    from investinglab.reporting.options import ReportOptions

__all__ = ["portfolio_plots", "series_plots"]

_WIDE: Final = (10.0, 4.2)
_MIN_ROLLING: Final = 5
_MAX_ANNOTATED_CELLS: Final = 12
_LOG_SCALE_RATIO: Final = 10.0
_DIVERGING_MAP: Final = LinearSegmentedColormap.from_list("investinglab_diverging", DIVERGING)


# ── Building blocks ─────────────────────────────────────────────────


def _figure(title: str, size: tuple[float, float] = _WIDE) -> tuple[Figure, Axes]:
    figure = Figure(figsize=size, layout="constrained")
    style_figure(figure)
    axes = figure.subplots()
    style_axes(axes, title=title)
    return figure, axes


def _date_axis(axes: Axes) -> None:
    locator = AutoDateLocator()  # type: ignore[no-untyped-call]
    axes.xaxis.set_major_locator(locator)
    axes.xaxis.set_major_formatter(
        ConciseDateFormatter(  # type: ignore[no-untyped-call]
            locator,
            formats=["%Y", "%Y-%m", "%Y-%m-%d", "%H:%M", "%H:%M", "%S.%f"],
            zero_formats=["", "%Y", "%Y-%m", "%Y-%m-%d", "%H:%M", "%H:%M"],
            offset_formats=["", "%Y", "%Y-%m", "%Y-%m-%d", "%Y-%m-%d", "%Y-%m-%d %H:%M"],
        )
    )


def _percent_axis(axes: Axes, tr: Translator, *, axis: str = "y", decimals: int = 0) -> None:
    formatter = FuncFormatter(lambda value, _: tr.percent(value, decimals))
    (axes.yaxis if axis == "y" else axes.xaxis).set_major_formatter(formatter)


def _number_axis(axes: Axes, tr: Translator, decimals: int = 0) -> None:
    axes.yaxis.set_major_formatter(FuncFormatter(lambda value, _: tr.number(value, decimals)))


type _Corner = Literal["upper left", "upper right", "lower right", "best"]


def _legend(
    axes: Axes,
    *,
    loc: _Corner = "upper left",
    ncols: int = 1,
    bbox_to_anchor: tuple[float, float] | None = None,
) -> None:
    legend = axes.legend(
        frameon=False, fontsize=9, loc=loc, ncols=ncols, bbox_to_anchor=bbox_to_anchor
    )
    for text in legend.get_texts():
        text.set_color(TEXT_PRIMARY)


def identity_colors(count: int) -> list[str]:
    """Categorical colour of each holding, in order; the ninth and later share a muted grey."""
    return [CATEGORICAL[i] if i < len(CATEGORICAL) else MUTED for i in range(count)]


def _rolling_window(options: ReportOptions, periods: int, periods_per_year: float) -> int | None:
    if options.rolling_window is not None:
        return options.rolling_window if options.rolling_window < periods else None
    window = max(_MIN_ROLLING, round(periods_per_year / 4))
    window = min(window, periods // 2)
    return window if window >= _MIN_ROLLING else None


# ── Series charts ───────────────────────────────────────────────────


def price_figure(series: PriceSeries, tr: Translator) -> Figure:
    """Price evolution with the last value labelled."""
    prices = series.prices
    figure, axes = _figure(
        tr.text("chart.price", symbol=series.symbol, currency=str(series.currency))
    )
    axes.plot(prices.index, prices.to_numpy(), color=CATEGORICAL[0], linewidth=1.6)
    last = float(prices.iloc[-1])
    axes.annotate(
        tr.number(last),
        xy=(prices.index[-1], last),
        xytext=(4, 0),
        textcoords="offset points",
        va="center",
        fontsize=8,
        color=TEXT_PRIMARY,
    )
    axes.set_ylabel(tr.text("chart.axis.price"))
    _number_axis(axes, tr, 2 if last < 10 else 0)  # noqa: PLR2004
    _date_axis(axes)
    return figure


def drawdown_figure(drawdown: pd.Series, tr: Translator, title: str) -> Figure:
    """Underwater chart: decline from the running peak, with the trough labelled."""
    figure, axes = _figure(title)
    values = drawdown.to_numpy(dtype="float64")
    axes.fill_between(drawdown.index, values, 0.0, color=SEQUENTIAL_BLUE[150], linewidth=0)
    axes.plot(drawdown.index, values, color=SEQUENTIAL_BLUE[600], linewidth=1.0)
    axes.axhline(0.0, color=BASELINE, linewidth=0.8)
    if len(values) and values.min() < 0:
        position = int(np.argmin(values))
        trough = pd.Timestamp(drawdown.index[position])
        depth = float(values[position])
        near_end = position > 0.7 * len(values)
        axes.annotate(
            tr.text("chart.label.trough", value=tr.percent(depth), date=tr.date(trough)),
            xy=(trough, depth),
            xytext=(-6 if near_end else 6, -2),
            textcoords="offset points",
            ha="right" if near_end else "left",
            va="top",
            fontsize=8,
            color=TEXT_PRIMARY,
        )
        axes.set_ylim(depth * 1.15, abs(depth) * 0.05)
    axes.set_ylabel(tr.text("chart.axis.drawdown"))
    _percent_axis(axes, tr)
    _date_axis(axes)
    return figure


def returns_figure(
    returns: pd.Series, tr: Translator, frequency: Frequency, level: float = 0.95
) -> Figure:
    """Histogram of returns with the fitted normal and the historical VaR."""
    values = returns.dropna().to_numpy(dtype="float64")
    figure, axes = _figure(tr.text("chart.returns", frequency=tr.frequency(frequency.value)))
    bins = int(np.clip(math.sqrt(values.size) * 2, 10, 60))
    counts, edges, _ = axes.hist(
        values, bins=bins, color=SEQUENTIAL_BLUE[250], edgecolor=SURFACE, linewidth=0.5
    )
    mean, std = float(values.mean()), float(values.std(ddof=1))
    if std > 0:
        grid = np.linspace(edges[0], edges[-1], 200)
        density = np.exp(-0.5 * ((grid - mean) / std) ** 2) / (std * math.sqrt(2 * math.pi))
        width = float(edges[1] - edges[0])
        axes.plot(
            grid,
            density * values.size * width,
            color=TEXT_SECONDARY,
            linewidth=1.4,
            label=tr.text("chart.legend.normal"),
        )
    var = value_at_risk(values, level, VaRMethod.HISTORICAL)
    axes.axvline(
        -var,
        color=TEXT_PRIMARY,
        linewidth=1.1,
        linestyle="--",
        label=tr.text("chart.legend.var", level=level_label(level, tr)) + f" ({tr.percent(-var)})",
    )
    axes.set_ylim(0, float(np.max(counts)) * 1.12 if len(counts) else 1)
    axes.set_xlabel(tr.text("chart.axis.return"))
    axes.set_ylabel(tr.text("chart.axis.periods"))
    _percent_axis(axes, tr, axis="x", decimals=1)
    _legend(axes, loc="upper right")
    return figure


def volatility_figure(
    returns: pd.Series, window: int, periods_per_year: float, tr: Translator
) -> Figure:
    """Rolling annualised volatility against the whole-period figure."""
    figure, axes = _figure(tr.text("chart.volatility", window=window))
    clean = returns.dropna()
    rolling = clean.rolling(window).std(ddof=1) * math.sqrt(periods_per_year)
    axes.plot(rolling.index, rolling.to_numpy(), color=CATEGORICAL[0], linewidth=1.4)
    average = float(clean.std(ddof=1) * math.sqrt(periods_per_year))
    axes.axhline(
        average,
        color=TEXT_SECONDARY,
        linewidth=1.0,
        label=tr.text("chart.legend.average", value=tr.percent(average)),
    )
    axes.set_ylim(bottom=0)
    axes.set_ylabel(tr.text("chart.axis.volatility"))
    _percent_axis(axes, tr)
    _date_axis(axes)
    _legend(axes, loc="upper left")
    return figure


def series_plots(series: PriceSeries, options: ReportOptions) -> PlotsReport:
    """Charts of a series.

    Price, drawdown, return distribution, rolling volatility and, when requested, the
    Monte Carlo simulation.
    """
    tr = options.translator
    returns = series.returns()
    figures: dict[str, Figure] = {
        "price": price_figure(series, tr),
        "drawdown": drawdown_figure(
            series.drawdown(), tr, tr.text("chart.drawdown", subject=series.symbol)
        ),
        "returns": returns_figure(returns, tr, series.frequency, min(options.confidence_levels)),
    }
    window = _rolling_window(options, len(returns), series.periods_per_year)
    if window is not None:
        figures["volatility"] = volatility_figure(returns, window, series.periods_per_year, tr)
    simulation = resolve_simulation(options.simulation, series.monte_carlo, (series.symbol,))
    if simulation is not None:
        figures["simulation"] = simulation_figure(
            simulation, level=min(options.confidence_levels), language=tr.language
        )
    return _with_titles(figures)


# ── Portfolio charts ────────────────────────────────────────────────


def growth_figure(analysis: PortfolioAnalysis, tr: Translator) -> Figure:
    """Portfolio and holdings growth over the common period, indexed to 100."""
    backtest = analysis.backtest
    start, end = backtest.start, backtest.end
    figure, axes = _figure(tr.text("chart.growth"), (10.0, 4.8))
    series = analysis.portfolio.series
    colors = identity_colors(len(series))
    folded = 0
    lows, highs = [], []
    for item, color in zip(series, colors, strict=True):
        prices = item.prices
        base = float(prices.loc[:start].iloc[-1])
        window = prices.loc[start:end]
        growth = window / base * 100.0
        lows.append(float(growth.min()))
        highs.append(float(growth.max()))
        if color == MUTED:
            folded += 1
            label = tr.text("common.others", count=len(series) - len(CATEGORICAL))
            label = label if folded == 1 else "_nolegend_"
        else:
            label = item.symbol
        axes.plot(growth.index, growth.to_numpy(), color=color, linewidth=1.2, label=label)
    values = backtest.values / float(backtest.values.iloc[0]) * 100.0
    axes.plot(
        values.index,
        values.to_numpy(),
        color=TEXT_PRIMARY,
        linewidth=2.4,
        label=tr.text("common.portfolio"),
        zorder=5,
    )
    axes.annotate(
        tr.number(float(values.iloc[-1]), 0),
        xy=(values.index[-1], float(values.iloc[-1])),
        xytext=(4, 0),
        textcoords="offset points",
        va="center",
        fontsize=8,
        color=TEXT_PRIMARY,
    )
    axes.axhline(100.0, color=BASELINE, linewidth=0.8)
    if min(lows) > 0 and max(highs) / min(lows) > _LOG_SCALE_RATIO:
        axes.set_yscale("log")
    axes.set_ylabel(tr.text("chart.axis.index"))
    _number_axis(axes, tr)
    _date_axis(axes)
    _legend(axes, loc="best", ncols=min(len(series) + 1, 5))
    return figure


def correlation_figure(correlation: pd.DataFrame, tr: Translator, frequency: Frequency) -> Figure:
    """Heatmap of correlations on the diverging ramp, with the values written in the cells."""
    symbols = [str(c) for c in correlation.columns]
    side = min(10.0, 3.0 + 0.55 * len(symbols))
    figure, axes = _figure(
        tr.text("chart.correlation", frequency=tr.frequency(frequency.value)),
        (side + 1.4, side),
    )
    values = correlation.to_numpy(dtype="float64")
    image = axes.imshow(values, cmap=_DIVERGING_MAP, vmin=-1.0, vmax=1.0)
    axes.set_xticks(range(len(symbols)), symbols, rotation=45, ha="right")
    axes.set_yticks(range(len(symbols)), symbols)
    axes.grid(visible=False)
    for spine in axes.spines.values():
        spine.set_visible(False)
    if len(symbols) <= _MAX_ANNOTATED_CELLS:
        for (row, col), value in np.ndenumerate(values):
            if math.isnan(value):
                continue
            axes.text(
                col,
                row,
                tr.number(float(value)),
                ha="center",
                va="center",
                fontsize=8,
                color="#ffffff" if abs(value) > 0.65 else TEXT_PRIMARY,  # noqa: PLR2004
            )
    colorbar = figure.colorbar(
        image, ax=axes, fraction=0.046, pad=0.04, ticks=[-1.0, -0.5, 0.0, 0.5, 1.0]
    )
    colorbar.set_label(tr.text("chart.colorbar"), color=TEXT_SECONDARY)
    colorbar.ax.tick_params(colors=TEXT_SECONDARY, labelsize=8)
    colorbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: tr.number(v, 1)))
    colorbar.outline.set_visible(False)
    return figure


def risk_contribution_figure(risk: pd.DataFrame, tr: Translator) -> Figure:
    """Target weight next to share of risk for every holding."""
    symbols = [str(s) for s in risk.index]
    height = max(3.0, 1.2 + 0.45 * len(symbols))
    figure, axes = _figure(tr.text("chart.risk_contribution"), (10.0, height))
    positions = np.arange(len(symbols))
    bar = 0.38
    weights = risk["weight"].to_numpy(dtype="float64")
    shares = risk["share"].to_numpy(dtype="float64")
    axes.barh(
        positions - bar / 2,
        weights,
        height=bar,
        color=CATEGORICAL[0],
        edgecolor=SURFACE,
        label=tr.text("chart.legend.weight"),
    )
    bars = axes.barh(
        positions + bar / 2,
        shares,
        height=bar,
        color=CATEGORICAL[1],
        edgecolor=SURFACE,
        label=tr.text("chart.legend.risk"),
    )
    for rect, share in zip(bars, shares, strict=True):
        axes.annotate(
            tr.percent(float(share)),
            xy=(rect.get_width(), rect.get_y() + rect.get_height() / 2),
            xytext=(4 if share >= 0 else -4, 0),
            textcoords="offset points",
            ha="left" if share >= 0 else "right",
            va="center",
            fontsize=8,
            color=TEXT_PRIMARY,
        )
    axes.set_yticks(positions, symbols)
    axes.invert_yaxis()
    axes.axvline(0.0, color=BASELINE, linewidth=0.8)
    axes.grid(axis="y", visible=False)
    limit = float(np.nanmax(np.abs(np.concatenate([weights, shares]))))
    axes.set_xlim(
        min(0.0, float(np.nanmin(shares)), float(np.nanmin(weights))) * 1.25, limit * 1.25
    )
    _percent_axis(axes, tr, axis="x")
    _legend(axes, loc="best")
    return figure


def weights_figure(backtest: PortfolioBacktest, targets: pd.Series, tr: Translator) -> Figure:
    """Effective weights through time against their targets: drift between rebalances."""
    weights = backtest.weights
    symbols = [str(c) for c in weights.columns]
    figure, axes = _figure(tr.text("chart.weights"))
    others = tr.text("common.others", count=len(symbols) - len(CATEGORICAL))
    for position, (symbol, color) in enumerate(
        zip(symbols, identity_colors(len(symbols)), strict=True)
    ):
        named = position < len(CATEGORICAL)
        label = symbol if named else (others if position == len(CATEGORICAL) else "_nolegend_")
        axes.plot(
            weights.index,
            weights[symbol].to_numpy(dtype="float64"),
            color=color,
            linewidth=1.4 if named else 0.8,
            label=label,
        )
        axes.axhline(float(targets[symbol]), color=color, linewidth=0.8, alpha=0.45)
    if (weights.to_numpy() < 0).any():
        axes.axhline(0.0, color=BASELINE, linewidth=0.8)
    else:
        axes.set_ylim(bottom=0)
    axes.set_ylabel(tr.text("chart.axis.weight"))
    _percent_axis(axes, tr)
    _date_axis(axes)
    _legend(axes, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return figure


def portfolio_plots(portfolio: Portfolio, options: ReportOptions) -> PlotsReport:
    """Charts of a portfolio.

    Growth versus holdings, drawdown, correlations, risk contribution, effective weights
    and, when requested, the Monte Carlo simulation.
    """
    tr = options.translator
    analysis = PortfolioAnalysis.compute(portfolio, options)
    figures: dict[str, Figure] = {
        "growth": growth_figure(analysis, tr),
        "drawdown": drawdown_figure(
            analysis.backtest.drawdown(), tr, tr.text("chart.drawdown_portfolio")
        ),
    }
    if len(portfolio) > 1:
        figures["correlation"] = correlation_figure(
            analysis.correlation, tr, analysis.choice.frequency
        )
    figures["risk_contribution"] = risk_contribution_figure(analysis.risk, tr)
    figures["weights"] = weights_figure(analysis.backtest, portfolio.weights, tr)
    simulation = resolve_simulation(options.simulation, portfolio.monte_carlo, portfolio.symbols)
    if simulation is not None:
        figures["simulation"] = simulation_figure(
            simulation, level=min(options.confidence_levels), language=tr.language
        )
    return _with_titles(figures)


def _with_titles(figures: dict[str, Figure]) -> PlotsReport:
    titles = {}
    for name, figure in figures.items():
        suptitle = figure.get_suptitle()
        titles[name] = suptitle or figure.axes[0].get_title(loc="left")
    return PlotsReport(figures, titles)
