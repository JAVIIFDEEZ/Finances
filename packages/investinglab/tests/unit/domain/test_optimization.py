from __future__ import annotations

import math

import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import covariance_matrix, ledoit_wolf
from investinglab.domain import (
    DomainError,
    EfficientFrontier,
    Objective,
    OptimizationConfig,
    OptimizationResult,
    Portfolio,
    RebalancePolicy,
    ReturnModel,
    View,
)
from investinglab.domain.optimization import Estimates, frontier_points
from support.factories import business_days, gbm_prices, make_series

N = 504
INDEX = business_days(N)
SYMBOLS = ("CALM", "WILD", "MID")


def _portfolio(**kwargs: object) -> Portfolio:
    assets = [
        make_series(gbm_prices(N, mu=0.04, sigma=0.10, seed=21), symbol="CALM", index=INDEX),
        make_series(gbm_prices(N, mu=0.12, sigma=0.35, seed=22), symbol="WILD", index=INDEX),
        make_series(gbm_prices(N, mu=0.08, sigma=0.20, seed=23), symbol="MID", index=INDEX),
    ]
    policy = RebalancePolicy.periodic("1mo")
    return Portfolio.from_weights("Synthetic", assets, [0.5, 0.2, 0.3], rebalance=policy, **kwargs)  # type: ignore[arg-type]


PORTFOLIO = _portfolio()
RETURNS = PORTFOLIO.asset_returns()


# ── Estimates ────────────────────────────────────────────────────────


def test_historical_estimates_are_annualised_sample_moments() -> None:
    result = PORTFOLIO.optimize(covariance="sample")

    estimates = result.estimates
    assert estimates.symbols == SYMBOLS
    assert estimates.observations == N - 1
    assert estimates.shrinkage is None
    assert estimates.expected_returns.to_numpy() == pytest.approx(RETURNS.mean() * 252)
    assert estimates.covariance.to_numpy() == pytest.approx(
        covariance_matrix(RETURNS).to_numpy() * 252
    )
    assert estimates.volatilities.to_numpy() == pytest.approx(RETURNS.std() * math.sqrt(252))


def test_ledoit_wolf_is_the_default_covariance() -> None:
    matrix, shrinkage = ledoit_wolf(RETURNS.to_numpy())

    estimates = PORTFOLIO.optimize().estimates

    assert estimates.shrinkage == pytest.approx(shrinkage)
    assert estimates.covariance.to_numpy() == pytest.approx(matrix * 252)


def test_lookback_and_frequency_change_the_sample() -> None:
    recent = PORTFOLIO.optimize(lookback=100).estimates
    weekly = PORTFOLIO.optimize(frequency="1w").estimates

    assert recent.observations == 100
    assert weekly.observations < 110
    assert weekly.covariance.to_numpy() == pytest.approx(
        ledoit_wolf(PORTFOLIO.asset_returns("1w").to_numpy())[0] * 52
    )


def test_the_sample_starts_when_every_holding_trades() -> None:
    late = make_series(gbm_prices(N - 200, seed=24), symbol="LATE", index=INDEX[200:])
    portfolio = Portfolio.from_weights("Late", [*PORTFOLIO.series, late], [0.25] * 4)

    assert portfolio.optimize().estimates.observations == N - 201


def test_ledoit_wolf_needs_overlapping_history() -> None:
    first = make_series(gbm_prices(10, seed=25), symbol="FIRST", index=INDEX[:10])
    second = make_series(gbm_prices(10, seed=26), symbol="SECOND", index=INDEX[20:30])
    portfolio = Portfolio.from_weights("Apart", [first, second], [0.5, 0.5])

    with pytest.raises(DomainError, match="Ledoit-Wolf needs"):
        portfolio.optimize()
    with pytest.raises(DomainError, match="never trade on the same dates"):
        portfolio.optimize(covariance="sample")


def test_assumed_expected_returns() -> None:
    assumed = {"CALM": 0.03, "WILD": 0.09, "MID": 0.06}

    result = PORTFOLIO.optimize(expected_returns=assumed)

    assert result.estimates.expected_returns.to_dict() == pytest.approx(assumed)
    with pytest.raises(DomainError, match="no value for"):
        PORTFOLIO.optimize(expected_returns={"CALM": 0.03})
    with pytest.raises(DomainError, match="must be finite"):
        PORTFOLIO.optimize(expected_returns={**assumed, "MID": math.nan})


def test_equilibrium_returns_make_the_current_weights_optimal() -> None:
    result = PORTFOLIO.optimize(
        objective="max_sharpe", expected_returns="equilibrium", risk_free_rate=0.02
    )

    assert result.weights.to_numpy() == pytest.approx([0.5, 0.2, 0.3], abs=1e-6)


# ── Objectives ───────────────────────────────────────────────────────


def test_minimum_variance_is_the_default_and_returns_a_portfolio() -> None:
    result = PORTFOLIO.optimize()

    assert isinstance(result, OptimizationResult)
    assert result.config.objective is Objective.MIN_VARIANCE
    portfolio = result.portfolio
    assert portfolio.name == "Synthetic"
    assert portfolio.rebalance == PORTFOLIO.rebalance
    assert portfolio.series == PORTFOLIO.series
    assert result.weights.sum() == pytest.approx(1.0)
    assert result.weights["CALM"] > result.weights["WILD"]
    assert result.previous_weights.tolist() == [0.5, 0.2, 0.3]


def test_ex_ante_figures_follow_the_estimates() -> None:
    result = PORTFOLIO.optimize(objective="max_sharpe", risk_free_rate=0.02)
    weights = result.weights.to_numpy()
    covariance = result.estimates.covariance.to_numpy()

    assert result.expected_return == pytest.approx(weights @ result.estimates.expected_returns)
    assert result.volatility == pytest.approx(math.sqrt(weights @ covariance @ weights))
    assert result.sharpe_ratio == pytest.approx((result.expected_return - 0.02) / result.volatility)
    assert result.risk_contributions["share"].sum() == pytest.approx(1.0)
    assert 1.0 <= result.effective_number_of_assets <= 3.0
    summary = result.summary()
    assert list(summary.columns) == [
        "previous_weight",
        "weight",
        "expected_return",
        "volatility",
        "risk_share",
    ]
    assert summary.index.tolist() == list(SYMBOLS)


def test_weight_bounds_are_respected() -> None:
    capped = PORTFOLIO.optimize(objective="max_sharpe", max_weight=0.4)
    floored = PORTFOLIO.optimize(min_weight={"WILD": 0.25})

    assert capped.weights.max() <= 0.4 + 1e-9
    assert floored.weights["WILD"] >= 0.25 - 1e-9
    with pytest.raises(DomainError, match="outside the portfolio"):
        PORTFOLIO.optimize(max_weight={"NOPE": 0.5})
    with pytest.raises(DomainError, match="Optimisation failed"):
        PORTFOLIO.optimize(max_weight=0.2)  # three holdings cannot reach 100 %


def test_shorts_build_a_short_portfolio() -> None:
    result = PORTFOLIO.optimize(objective="max_sharpe", min_weight=-0.5, max_weight=1.5)

    assert result.portfolio.allow_short == bool((result.weights < 0).any())
    assert result.weights.sum() == pytest.approx(1.0)


def test_target_return() -> None:
    target = float(PORTFOLIO.optimize().expected_return) + 0.01

    result = PORTFOLIO.optimize(objective="target_return", target_return=target)

    assert result.expected_return == pytest.approx(target, abs=1e-8)
    with pytest.raises(DomainError, match="out of reach"):
        PORTFOLIO.optimize(objective="target_return", target_return=5.0)


def test_risk_parity_with_and_without_budgets() -> None:
    equal = PORTFOLIO.optimize(objective="risk_parity")
    budgeted = PORTFOLIO.optimize(
        objective="risk_parity", risk_budgets={"CALM": 0.5, "WILD": 0.25, "MID": 0.25}
    )

    assert equal.risk_contributions["share"].to_numpy() == pytest.approx(np.full(3, 1 / 3))
    assert budgeted.risk_contributions["share"].to_numpy() == pytest.approx([0.5, 0.25, 0.25])
    with pytest.raises(DomainError, match="risk_budgets: missing"):
        PORTFOLIO.optimize(objective="risk_parity", risk_budgets={"CALM": 1.0})


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        (Objective.EQUAL_WEIGHT, None),
        (Objective.INVERSE_VOLATILITY, None),
        (Objective.HIERARCHICAL_RISK_PARITY, None),
    ],
)
def test_risk_based_objectives(objective: Objective, expected: None) -> None:
    result = PORTFOLIO.optimize(objective=objective)

    assert result.weights.min() > 0
    assert result.weights.sum() == pytest.approx(1.0)
    if objective is Objective.EQUAL_WEIGHT:
        assert result.weights.tolist() == pytest.approx([1 / 3] * 3)
    else:
        assert result.weights["CALM"] > result.weights["WILD"]  # calmer gets more
    assert expected is None


def test_infeasible_tangency_is_a_domain_error() -> None:
    with pytest.raises(DomainError, match="risk-free rate"):
        PORTFOLIO.optimize(objective="max_sharpe", risk_free_rate=1.0)


# ── Black-Litterman views ────────────────────────────────────────────


def test_views_tilt_the_weights_towards_them() -> None:
    base = PORTFOLIO.optimize(
        objective="max_sharpe", expected_returns="equilibrium", risk_free_rate=0.02
    )
    bullish = PORTFOLIO.optimize(
        objective="max_sharpe",
        expected_returns="equilibrium",
        risk_free_rate=0.02,
        views=[View.absolute("MID", 0.20)],
    )
    relative = PORTFOLIO.optimize(
        objective="max_sharpe",
        expected_returns="equilibrium",
        risk_free_rate=0.02,
        views=[View.relative("CALM", "WILD", 0.10, uncertainty=0.0001)],
    )

    assert bullish.weights["MID"] > base.weights["MID"]
    assert bullish.estimates.expected_returns["MID"] > base.estimates.expected_returns["MID"]
    assert relative.weights["CALM"] > base.weights["CALM"]


def test_invalid_views() -> None:
    with pytest.raises(DomainError, match="outside the portfolio"):
        PORTFOLIO.optimize(objective="max_sharpe", views=[View.absolute("NOPE", 0.1)])
    with pytest.raises(DomainError, match="non-zero weight"):
        View({"CALM": 0.0}, 0.1)
    with pytest.raises(DomainError, match="finite"):
        View({"CALM": 1.0}, math.nan)
    with pytest.raises(DomainError, match="cannot be negative"):
        View({"CALM": 1.0}, 0.1, uncertainty=-1.0)
    with pytest.raises(DomainError, match="redundant"):
        PORTFOLIO.optimize(
            objective="max_sharpe",
            views=[View.absolute("MID", 0.1, 0.0), View.absolute("MID", 0.2, 0.0)],
        )


# ── Configuration ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"objective": "magic"}, "magic"),
        ({"objective": "target_return"}, "needs target_return"),
        ({"target_return": 0.05}, "only applies"),
        ({"risk_budgets": {"CALM": 1.0}}, "only apply"),
        ({"objective": "hrp", "max_weight": 0.5}, "do not apply"),
        ({"risk_aversion": 0.0}, "risk_aversion"),
        ({"tau": 0.0}, "tau"),
        ({"lookback": 2}, "lookback"),
        ({"risk_free_rate": math.inf}, "risk_free_rate"),
    ],
)
def test_invalid_configurations_are_rejected(settings: dict[str, object], message: str) -> None:
    with pytest.raises(DomainError, match=message):
        OptimizationConfig(**settings)  # type: ignore[arg-type]


def test_configurations_accept_strings_and_freeze_mappings() -> None:
    config = OptimizationConfig(
        objective="max_sharpe",  # type: ignore[arg-type]
        expected_returns="equilibrium",  # type: ignore[arg-type]
        frequency="1w",  # type: ignore[arg-type]
        max_weight={"CALM": 0.6},
    )

    assert config.objective is Objective.MAX_SHARPE
    assert config.expected_returns is ReturnModel.EQUILIBRIUM
    assert config.frequency is not None
    assert config.frequency.value == "1w"
    with pytest.raises(TypeError):
        config.max_weight["CALM"] = 1.0  # type: ignore[index]
    assert Objective.MAX_SHARPE.uses_expected_returns
    assert not Objective.RISK_PARITY.accepts_bounds


def test_explicit_config_and_overrides_combine() -> None:
    config = OptimizationConfig(objective=Objective.MAX_SHARPE, risk_free_rate=0.02)

    result = PORTFOLIO.optimize(config, max_weight=0.45)

    assert result.config.objective is Objective.MAX_SHARPE
    assert result.config.max_weight == 0.45
    assert result.weights.max() <= 0.45 + 1e-9


# ── Frontier ─────────────────────────────────────────────────────────


def test_efficient_frontier() -> None:
    frontier = PORTFOLIO.efficient_frontier(points=15, risk_free_rate=0.02)

    assert isinstance(frontier, EfficientFrontier)
    points = frontier.points
    assert list(points.columns) == ["expected_return", "volatility", "sharpe_ratio", *SYMBOLS]
    assert len(points) == 15
    assert (points["expected_return"].diff().dropna() > 0).all()
    assert points.loc[0, "volatility"] == pytest.approx(frontier.minimum_variance.volatility)
    assert frontier.maximum_sharpe is not None
    assert frontier.maximum_sharpe.sharpe_ratio >= points["sharpe_ratio"].max() - 1e-6
    assert frontier.assets.index.tolist() == list(SYMBOLS)
    assert frontier.config.objective is Objective.MIN_VARIANCE


def test_frontier_without_a_tangency_and_with_infeasible_bounds() -> None:
    flat = PORTFOLIO.efficient_frontier(points=5, risk_free_rate=1.0)

    assert flat.maximum_sharpe is None
    with pytest.raises(DomainError, match="Optimisation failed"):
        PORTFOLIO.efficient_frontier(max_weight=0.2)


def test_frontier_chart_in_both_languages() -> None:
    mpl.use("Agg")
    frontier = PORTFOLIO.efficient_frontier(points=8, risk_free_rate=0.02)

    spanish = frontier.plot()
    english = frontier.plot(language="en", title="Custom")

    axes = spanish.axes[0]
    assert axes.get_title(loc="left") == "Frontera eficiente"
    assert axes.get_xlabel() == "Volatilidad anual"
    legend = axes.get_legend()
    assert legend is not None
    labels = [text.get_text() for text in legend.get_texts()]
    assert labels == [
        "Frontera eficiente",
        "Activos",
        "Mínima varianza",
        "Línea del mercado de capitales",
        "Máximo Sharpe",
    ]
    assert english.axes[0].get_title(loc="left") == "Custom"
    assert english.axes[0].get_ylabel() == "Annual expected return"


def test_frontier_chart_without_tangency_or_labels() -> None:
    mpl.use("Agg")
    many = [
        make_series(gbm_prices(N, seed=30 + i), symbol=f"S{i:02d}", index=INDEX) for i in range(13)
    ]
    portfolio = Portfolio.equal_weight("Many", many)

    figure = portfolio.efficient_frontier(points=4, risk_free_rate=1.0).plot()

    axes = figure.axes[0]
    assert not axes.texts  # too many holdings to label
    legend = axes.get_legend()
    assert legend is not None
    assert len(legend.get_texts()) == 3


# ── Rebuilding portfolios ────────────────────────────────────────────


def test_with_weights_keeps_holdings_currency_and_policy() -> None:
    rebuilt = PORTFOLIO.with_weights({"CALM": 0.2, "WILD": 0.3, "MID": 0.5}, name="Other")
    short = PORTFOLIO.with_weights({"CALM": 1.2, "WILD": -0.5, "MID": 0.3})

    assert rebuilt.name == "Other"
    assert rebuilt.weights.tolist() == [0.2, 0.3, 0.5]
    assert rebuilt.base_currency == PORTFOLIO.base_currency
    assert rebuilt.rebalance == PORTFOLIO.rebalance
    assert short.allow_short
    assert isinstance(rebuilt.weights, pd.Series)


def test_frontier_points_report_infeasible_bounds() -> None:
    estimates = PORTFOLIO.optimize().estimates

    with pytest.raises(DomainError, match="Efficient frontier failed"):
        frontier_points(estimates, OptimizationConfig(max_weight=0.2), 5)


def test_a_riskless_portfolio_has_no_sharpe_ratio() -> None:
    symbols = list(SYMBOLS)
    riskless = Estimates(
        expected_returns=pd.Series(0.03, index=symbols),
        covariance=pd.DataFrame(0.0, index=symbols, columns=symbols),
        observations=10,
    )

    result = OptimizationResult(
        OptimizationConfig(), PORTFOLIO, riskless, previous_weights=PORTFOLIO.weights
    )

    assert result.volatility == 0.0
    assert math.isnan(result.sharpe_ratio)
