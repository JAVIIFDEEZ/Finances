from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from investinglab.analytics import (
    VaRMethod,
    beta,
    calmar_ratio,
    conditional_value_at_risk,
    downside_deviation,
    effective_number_of_assets,
    excess_returns,
    herfindahl_index,
    per_period_rate,
    sharpe_ratio,
    sortino_ratio,
    value_at_risk,
)

RETURNS = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, -0.005, 0.0, 0.012, -0.018])


def test_sharpe_ratio_matches_the_definition() -> None:
    rf = 0.0001
    excess = RETURNS - rf

    expected = excess.mean() / excess.std(ddof=1) * math.sqrt(252)

    assert sharpe_ratio(RETURNS, periods_per_year=252, risk_free=rf) == pytest.approx(expected)


def test_sharpe_with_a_risk_free_series_aligned_on_dates() -> None:
    returns = pd.Series([0.01, 0.02, 0.03], index=pd.bdate_range("2024-01-01", periods=3))
    rf = pd.Series([0.001, 0.001], index=returns.index[:2])  # last date unknown → ignored

    excess = excess_returns(returns, rf)

    assert excess.iloc[:2].tolist() == pytest.approx([0.009, 0.019])
    assert np.isnan(excess.iloc[2])
    assert math.isfinite(sharpe_ratio(returns, periods_per_year=252, risk_free=rf))


def test_sortino_uses_downside_deviation() -> None:
    downside = math.sqrt(np.mean(np.minimum(RETURNS.to_numpy(), 0.0) ** 2))

    assert downside_deviation(RETURNS) == pytest.approx(downside)
    assert sortino_ratio(RETURNS, periods_per_year=252) == pytest.approx(
        RETURNS.mean() / downside * math.sqrt(252)
    )


@pytest.mark.parametrize(
    "returns", [pd.Series([0.01]), pd.Series([0.01, 0.01, 0.01]), pd.Series([], dtype=float)]
)
def test_ratios_are_nan_when_undefined(returns: pd.Series) -> None:
    assert math.isnan(sharpe_ratio(returns, periods_per_year=252))
    assert math.isnan(sortino_ratio(returns, periods_per_year=252))


def test_downside_deviation_of_empty_input_is_nan() -> None:
    assert math.isnan(downside_deviation(np.array([])))


def test_calmar_ratio() -> None:
    assert calmar_ratio(0.12, -0.24) == pytest.approx(0.5)
    assert math.isnan(calmar_ratio(0.12, 0.0))


def test_historical_var_and_cvar() -> None:
    returns = pd.Series(np.linspace(-0.10, 0.09, 20))

    var = value_at_risk(returns, 0.90)
    cvar = conditional_value_at_risk(returns, 0.90)

    assert var == pytest.approx(-np.quantile(returns, 0.10))
    assert cvar == pytest.approx(-returns[returns <= -var].mean())
    assert cvar >= var


def test_gaussian_var_and_cvar_closed_forms() -> None:
    mu, sigma = RETURNS.mean(), RETURNS.std(ddof=1)
    z = stats.norm.ppf(0.05)

    assert value_at_risk(RETURNS, 0.95, "gaussian") == pytest.approx(-(mu + sigma * z))
    assert conditional_value_at_risk(RETURNS, 0.95, VaRMethod.GAUSSIAN) == pytest.approx(
        -(mu - sigma * stats.norm.pdf(z) / 0.05)
    )


def test_cornish_fisher_widens_var_for_fat_left_tails() -> None:
    rng = np.random.default_rng(3)
    crashes = np.where(rng.random(5000) < 0.02, -0.08, 0.0)  # synthetic jump risk
    returns = pd.Series(rng.normal(0.0005, 0.01, 5000) + crashes)

    gaussian = value_at_risk(returns, 0.99, VaRMethod.GAUSSIAN)
    corrected = value_at_risk(returns, 0.99, VaRMethod.CORNISH_FISHER)
    corrected_cvar = conditional_value_at_risk(returns, 0.99, VaRMethod.CORNISH_FISHER)

    assert corrected > gaussian
    assert corrected_cvar > corrected


def test_var_needs_a_valid_level_and_enough_data() -> None:
    with pytest.raises(ValueError, match="level"):
        value_at_risk(RETURNS, 1.0)
    with pytest.raises(ValueError, match="level"):
        conditional_value_at_risk(RETURNS, 0.0)
    assert math.isnan(value_at_risk(pd.Series([0.01]), 0.95))
    assert math.isnan(conditional_value_at_risk(pd.Series([0.01]), 0.95))


def test_beta_on_common_dates() -> None:
    index = pd.bdate_range("2024-01-01", periods=6)
    market = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02], index=index)
    asset = 2 * market.iloc[1:]  # one fewer observation

    assert beta(asset, market) == pytest.approx(2.0)
    assert math.isnan(beta(asset.iloc[:1], market))
    assert math.isnan(beta(market, pd.Series(0.0, index=index)))


def test_concentration_measures() -> None:
    assert herfindahl_index(np.array([0.25] * 4)) == pytest.approx(0.25)
    assert effective_number_of_assets(np.array([0.25] * 4)) == pytest.approx(4.0)
    assert herfindahl_index(np.array([1.0])) == 1.0
    assert herfindahl_index(np.array([1.3, -0.3])) == pytest.approx((1.3**2 + 0.3**2) / 1.6**2)
    assert math.isnan(herfindahl_index(np.zeros(2)))
    assert math.isnan(effective_number_of_assets(np.zeros(2)))


def test_per_period_rate_compounds_back_to_the_annual_rate() -> None:
    daily = per_period_rate(0.03, 252)

    assert (1 + daily) ** 252 == pytest.approx(1.03)
    series = per_period_rate(pd.Series([0.03, 0.0]), 12)
    assert isinstance(series, pd.Series)
    assert series.iloc[1] == 0.0


def test_cornish_fisher_is_close_to_gaussian_without_strong_skew() -> None:
    returns = pd.Series([-0.02, -0.01, 0.0, 0.01, 0.02])  # symmetric

    gaussian = value_at_risk(returns, 0.95, VaRMethod.GAUSSIAN)
    corrected = value_at_risk(returns, 0.95, VaRMethod.CORNISH_FISHER)

    assert corrected == pytest.approx(gaussian, rel=0.3)
