from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from matplotlib.figure import Figure

from investinglab.domain import Portfolio, SimulationConfig, SimulationModel
from investinglab.reporting.simulation import simulation_figure
from investinglab.reporting.theme import SURFACE
from support.factories import business_days, gbm_prices, make_series

if TYPE_CHECKING:
    from investinglab.domain import SimulationResult


@pytest.fixture(scope="module")
def result() -> SimulationResult:
    index = business_days(300)
    assets = [
        make_series(gbm_prices(300, seed=1), symbol="A", index=index),
        make_series(gbm_prices(300, seed=2, sigma=0.3), symbol="B", index=index),
    ]
    portfolio = Portfolio.from_weights("Synthetic", assets, [0.5, 0.5])
    return portfolio.monte_carlo(SimulationConfig(n_paths=500, horizon=40))


def test_plot_draws_the_fan_and_the_terminal_distribution(result: SimulationResult) -> None:
    figure = result.plot()

    assert isinstance(figure, Figure)
    fan, hist = figure.axes
    assert fan.get_title(loc="left") == "Simulated value paths"
    assert hist.get_title(loc="left") == "Value at the horizon"
    legend = fan.get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == [
        "5-95 %",
        "25-75 %",
        "Median",
        "Initial value",
    ]
    assert figure.get_facecolor()[:3] == pytest.approx(
        tuple(int(SURFACE[i : i + 2], 16) / 255 for i in (1, 3, 5))
    )


def test_risk_thresholds_are_labelled_on_the_histogram(result: SimulationResult) -> None:
    figure = simulation_figure(result, level=0.99)

    labels = [text.get_text() for text in figure.axes[1].texts]
    assert any(label.strip().startswith("Median") for label in labels)
    assert any("VaR 99%" in label and "CVaR" not in label for label in labels)
    assert any("CVaR 99%" in label for label in labels)


def test_default_title_describes_the_simulation(result: SimulationResult) -> None:
    figure = result.plot()

    title = figure.get_suptitle()
    assert "gbm" in title
    assert "500 paths" in title
    assert "40 periods" in title


def test_options_are_forwarded(result: SimulationResult) -> None:
    figure = result.plot(title="Custom", sample_paths=3)

    assert figure.get_suptitle() == "Custom"
    # Three sample paths + the median line + the initial-value line.
    assert len(figure.axes[0].lines) == 5


def test_bootstrap_results_can_be_plotted() -> None:
    series = make_series(gbm_prices(100), symbol="A", index=business_days(100))
    config = SimulationConfig(n_paths=200, horizon=10, model=SimulationModel.BOOTSTRAP)

    figure = series.monte_carlo(config).plot()

    assert "bootstrap" in figure.get_suptitle()
