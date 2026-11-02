from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from investinglab.domain import Portfolio, PriceSeries, SimulationConfig
from investinglab.reporting.charts import identity_colors
from investinglab.reporting.plots import PlotsReport
from investinglab.reporting.theme import CATEGORICAL, MUTED
from support.factories import business_days, gbm_prices, make_series

if TYPE_CHECKING:
    from pathlib import Path

N = 300


def _series(
    symbol: str = "A", seed: int = 1, n: int = N, prices: np.ndarray | None = None
) -> PriceSeries:
    values = prices if prices is not None else gbm_prices(n, seed=seed)
    return make_series(values, symbol=symbol, index=business_days(len(values)))


def _portfolio(count: int = 3) -> Portfolio:
    assets = [_series(f"S{i:02d}", seed=i + 1) for i in range(count)]
    return Portfolio.equal_weight("P", assets)


def test_series_plots_contain_the_four_charts_in_spanish() -> None:
    plots = _series().plots_report()

    assert isinstance(plots, PlotsReport)
    assert list(plots) == ["price", "drawdown", "returns", "volatility"]
    assert all(isinstance(plots[name], Figure) for name in plots)
    assert plots.titles["price"] == "Precio de A (EUR)"
    assert plots.titles["volatility"] == "Volatilidad anualizada móvil (63 periodos)"
    assert len(plots) == 4


def test_series_plots_in_english_with_a_custom_window_and_simulation() -> None:
    plots = _series().plots_report(
        language="en",
        rolling_window=20,
        simulation=SimulationConfig(n_paths=200, horizon=10),
    )

    assert list(plots) == ["price", "drawdown", "returns", "volatility", "simulation"]
    assert plots.titles["volatility"] == "Rolling annualised volatility (20 periods)"
    assert plots.titles["simulation"].startswith("Monte Carlo · GBM · 200 paths")


def test_short_series_skip_the_rolling_volatility() -> None:
    assert "volatility" not in _series(n=8).plots_report()
    assert "volatility" not in _series().plots_report(rolling_window=N)


def test_return_distribution_shows_the_normal_fit_and_the_var() -> None:
    figure = _series().plots_report(language="en")["returns"]

    legend = figure.axes[0].get_legend()
    assert legend is not None
    labels = [text.get_text() for text in legend.get_texts()]
    assert labels[0] == "Fitted normal"
    assert labels[1].startswith("Historical VaR 95%")


def test_monotone_series_have_an_unannotated_drawdown_chart() -> None:
    figure = _series(prices=np.linspace(100, 130, 50)).plots_report()["drawdown"]

    assert len(figure.axes[0].texts) == 0


def test_drawdown_trough_is_labelled() -> None:
    figure = _series().plots_report()["drawdown"]

    (label,) = figure.axes[0].texts
    assert "%" in label.get_text()


def test_portfolio_plots() -> None:
    plots = _portfolio().plots_report(simulation=SimulationConfig(n_paths=200, horizon=10))

    assert list(plots) == [
        "growth",
        "drawdown",
        "correlation",
        "risk_contribution",
        "weights",
        "simulation",
    ]
    assert plots.titles["drawdown"] == "Caída desde máximos de la cartera"
    growth_legend = plots["growth"].axes[0].get_legend()
    assert growth_legend is not None
    assert [t.get_text() for t in growth_legend.get_texts()] == ["S00", "S01", "S02", "Cartera"]


def test_correlation_cells_are_annotated() -> None:
    figure = _portfolio().plots_report(language="en")["correlation"]

    heatmap = figure.axes[0]
    assert len(heatmap.texts) == 9
    assert {text.get_text() for text in heatmap.texts} >= {"1.00"}


def test_single_holding_portfolios_have_no_correlation_chart() -> None:
    plots = Portfolio.from_weights("One", [_series()], [1.0]).plots_report()

    assert "correlation" not in plots


def test_identity_colours_never_cycle() -> None:
    colors = identity_colors(10)

    assert colors[:8] == list(CATEGORICAL)
    assert colors[8:] == [MUTED, MUTED]


def test_holdings_beyond_the_eighth_are_folded_into_others() -> None:
    plots = _portfolio(10).plots_report(language="en")

    for name in ("growth", "weights"):
        legend = plots[name].axes[0].get_legend()
        assert legend is not None
        labels = [text.get_text() for text in legend.get_texts()]
        assert "Others (2)" in labels
        assert "S09" not in labels


def test_short_positions_draw_a_zero_line_on_the_weights_chart() -> None:
    assets = [_series("L", 1), _series("S", 2)]
    portfolio = Portfolio.from_weights("LS", assets, [1.5, -0.5], allow_short=True)

    figure = portfolio.plots_report()["weights"]

    assert figure.axes[0].get_ylim()[0] < 0


def test_large_dispersion_uses_a_log_scale() -> None:
    rocket = _series("ROCKET", prices=np.geomspace(1, 50, N))
    steady = _series("STEADY", 2)
    portfolio = Portfolio.from_weights("Mix", [rocket, steady], [0.5, 0.5])

    figure = portfolio.plots_report()["growth"]

    assert figure.axes[0].get_yscale() == "log"


def test_plots_can_be_saved_and_shown_in_notebooks(tmp_path: Path) -> None:
    plots = _series().plots_report()

    paths = plots.save(tmp_path / "charts", fmt="png", dpi=60)
    html = plots._repr_html_()

    assert sorted(p.name for p in paths.values()) == [
        "drawdown.png",
        "price.png",
        "returns.png",
        "volatility.png",
    ]
    assert all(p.stat().st_size > 0 for p in paths.values())
    assert html.count("data:image/png;base64,") == 4
    assert "<figcaption>Precio de A (EUR)</figcaption>" in html
    assert repr(plots) == "PlotsReport(['price', 'drawdown', 'returns', 'volatility'])"


def test_plots_report_defaults_titles_to_names() -> None:
    figure = Figure()

    plots = PlotsReport({"x": figure})

    assert plots.titles == {"x": "x"}
    assert plots["x"] is figure


def test_charts_never_touch_pyplot() -> None:
    import matplotlib.pyplot as plt  # noqa: PLC0415

    before = plt.get_fignums()
    _portfolio().plots_report()

    assert plt.get_fignums() == before


@pytest.mark.parametrize("language", ["es", "en"])
def test_charts_render_in_both_languages(language: str) -> None:
    plots = _portfolio().plots_report(language=language)

    for figure in plots.values():
        figure.canvas.draw()  # layout and formatters run without errors
    assert pd.notna(plots.titles["growth"])
