from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    DomainError,
    DriftAssumption,
    PlanResult,
    Portfolio,
    SavingsPlan,
    SimulationConfig,
    VolatilityAssumption,
)
from investinglab.domain.planning import month_end_values
from support.factories import business_days, gbm_prices, make_series

N = 1_000
INDEX = business_days(N)
FUND = make_series(gbm_prices(N, mu=0.07, sigma=0.15, seed=5), symbol="FUND", index=INDEX)
QUICK = SimulationConfig(n_paths=2_000)
# No volatility and a 6 % annual return: every path is the same deterministic curve.
CERTAIN = SimulationConfig(
    n_paths=100,
    drift=DriftAssumption.ASSUMED,
    expected_returns=0.06,
    volatility=VolatilityAssumption.ASSUMED,
    volatilities=0.0,
)


# ── The plan ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"years": 0}, "years"),
        ({"years": 101}, "years"),
        ({"years": 0.01}, "years"),
        ({"years": 10, "initial": -1.0}, "initial"),
        ({"years": 10}, "invests nothing"),
        ({"years": 10, "initial": 1.0, "contribution": math.nan}, "contribution must be finite"),
        ({"years": 10, "initial": 1.0, "contribution_growth": -1.0}, "contribution_growth"),
        ({"years": 10, "initial": 1.0, "inflation": -1.5}, "inflation"),
        ({"years": 10, "initial": 1.0, "goal": 0.0}, "goal"),
    ],
)
def test_invalid_plans_are_rejected(settings: dict[str, float], message: str) -> None:
    with pytest.raises(DomainError, match=message):
        SavingsPlan(**settings)


def test_contributions_grow_and_prices_deflate_month_by_month() -> None:
    plan = SavingsPlan(years=2.5, contribution=100.0, contribution_growth=0.12, inflation=0.03)

    assert plan.months == 30
    flows = plan.contributions()
    assert flows[0] == 100.0
    assert flows[12] == pytest.approx(112.0)
    assert plan.deflator()[0] == 1.0
    assert plan.deflator()[24] == pytest.approx(1.03**2)


def test_month_end_values_keep_the_last_real_observation() -> None:
    days = pd.DatetimeIndex(["2024-01-30", "2024-01-31", "2024-02-28", "2024-02-29", "2024-03-01"])
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=days)
    hourly = pd.Series(
        [1.0, 2.0, 3.0],
        index=pd.DatetimeIndex(
            ["2024-01-31 22:00", "2024-02-01 10:00", "2024-02-02 10:00"], tz="UTC"
        ),
    )

    assert month_end_values(values).tolist() == [2.0, 4.0, 5.0]
    assert month_end_values(values).index[0] == pd.Timestamp("2024-01-31")
    assert month_end_values(hourly).tolist() == [1.0, 3.0]


# ── Simulation ───────────────────────────────────────────────────────


def test_a_certain_return_gives_the_annuity_formula() -> None:
    plan = SavingsPlan(years=10, initial=5_000, contribution=200)

    result = FUND.savings_plan(plan, CERTAIN)

    growth = 1.06 ** (1 / 12)
    months = np.arange(1, 121)
    expected = 5_000 * growth**120 + np.sum(200 * growth ** (120 - months))
    assert isinstance(result, PlanResult)
    assert (result.n_paths, result.months) == (100, 120)
    assert result.terminal_wealth(real=False) == pytest.approx(np.full(100, expected))
    assert result.contributed(real=False)[-1] == pytest.approx(5_000 + 200 * 120)


def test_terminal_wealth_is_linear_in_the_contribution() -> None:
    plan = SavingsPlan(years=15, initial=8_000, contribution=250, contribution_growth=0.02)

    result = FUND.savings_plan(plan, QUICK)

    linear = result._base + 250 * result._per_contribution
    assert result.terminal_wealth(real=False) == pytest.approx(linear, rel=1e-12)


def test_the_required_contribution_reaches_the_goal_that_often() -> None:
    plan = SavingsPlan(years=20, initial=10_000, contribution=200, goal=150_000, inflation=0.02)
    result = FUND.savings_plan(plan, QUICK)

    needed = result.required_contribution(0.9)
    retry = FUND.savings_plan(
        SavingsPlan(years=20, initial=10_000, contribution=needed, goal=150_000, inflation=0.02),
        QUICK,
    )

    assert needed > 200
    assert retry.probability_of_success is not None
    assert retry.probability_of_success >= 0.9
    assert retry.probability_of_success < 0.9 + 0.01


def test_an_initial_capital_that_suffices_needs_no_contribution() -> None:
    plan = SavingsPlan(years=10, initial=100_000, goal=10_000)

    result = FUND.savings_plan(plan, CERTAIN)

    assert result.required_contribution(0.5) == 0.0
    assert result.probability_of_success == 1.0
    assert result.expected_shortfall == 0.0


def test_goal_statistics_need_a_goal() -> None:
    result = FUND.savings_plan(SavingsPlan(years=5, contribution=100), QUICK)

    assert result.probability_of_success is None
    assert result.expected_shortfall is None
    assert "goal" not in result.summary().index
    with pytest.raises(DomainError, match="no goal"):
        result.required_contribution()


def test_probabilities_must_be_strictly_between_zero_and_one() -> None:
    result = FUND.savings_plan(SavingsPlan(years=5, contribution=100, goal=10_000), QUICK)

    with pytest.raises(DomainError, match=r"probability must be in \(0, 1\)"):
        result.required_contribution(1.0)


def test_shortfall_and_summary_with_a_goal() -> None:
    result = FUND.savings_plan(SavingsPlan(years=10, contribution=150, goal=40_000), QUICK)

    assert result.probability_of_success is not None
    assert 0 < result.probability_of_success < 1
    assert result.expected_shortfall is not None
    assert result.expected_shortfall > 0
    summary = result.summary()["value"]
    assert summary["goal"] == 40_000
    assert summary["contributed"] == pytest.approx(150 * 120)
    assert summary["required_contribution_90"] == pytest.approx(result.required_contribution(0.9))


def test_withdrawals_can_run_out_of_money_and_stay_at_zero() -> None:
    plan = SavingsPlan(years=30, initial=100_000, contribution=-1_000)

    result = FUND.savings_plan(plan, QUICK)

    wealth = result.wealth(real=False)
    assert 0 < result.probability_of_ruin <= 1
    assert (wealth >= 0).all()
    ruined = (wealth[:, 1:] <= 0).any(axis=1)
    assert (wealth[ruined, -1] == 0).all()


def test_results_are_in_todays_money() -> None:
    plan = SavingsPlan(years=10, initial=10_000, contribution=100, inflation=0.03)

    result = FUND.savings_plan(plan, CERTAIN)

    nominal = result.wealth(real=False)
    assert result.wealth() == pytest.approx(nominal / plan.deflator())
    assert result.median_terminal_wealth == pytest.approx(nominal[0, -1] / 1.03**10)
    assert result.percentile_paths().shape == (121, 5)


def test_portfolios_are_simulated_from_their_value() -> None:
    other = make_series(gbm_prices(N, mu=0.03, sigma=0.05, seed=6), symbol="BOND", index=INDEX)
    portfolio = Portfolio.from_weights("Mix", [FUND, other], [0.6, 0.4])

    result = portfolio.savings_plan(SavingsPlan(years=5, contribution=100), QUICK)

    assert result.currency == "EUR"
    assert (
        result.simulation.calibration.observations
        == len(month_end_values(portfolio.value_history())) - 1
    )


def test_a_plan_needs_three_months_of_history() -> None:
    short = make_series(gbm_prices(30, seed=7), symbol="NEW", index=business_days(30))

    with pytest.raises(DomainError, match="three months"):
        short.savings_plan(SavingsPlan(years=1, contribution=100))
