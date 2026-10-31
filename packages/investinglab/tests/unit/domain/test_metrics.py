from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics import VaRMethod
from investinglab.domain import DomainError, RiskMetrics
from support.factories import gbm_prices, make_series

INDEX = pd.bdate_range("2024-01-01", periods=6)
RETURNS = pd.Series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02], index=INDEX)


def test_metrics_from_returns() -> None:
    metrics = RiskMetrics.from_returns(RETURNS, periods_per_year=252, risk_free_rate=0.0)

    growth = float(np.prod(1 + RETURNS.to_numpy()))
    assert metrics.periods == 6
    assert metrics.start == INDEX[0]
    assert metrics.end == INDEX[-1]
    assert metrics.total_return == pytest.approx(growth - 1)
    assert metrics.annualized_return == pytest.approx(growth ** (252 / 6) - 1)
    assert metrics.annualized_volatility == pytest.approx(RETURNS.std() * math.sqrt(252))
    assert metrics.best_period == 0.02
    assert metrics.worst_period == -0.02
    assert metrics.positive_ratio == pytest.approx(4 / 6)
    assert metrics.max_drawdown == pytest.approx(1.01 * 0.98 / 1.01 - 1)
    assert metrics.calmar_ratio == pytest.approx(
        metrics.annualized_return / abs(metrics.max_drawdown)
    )
    assert len(metrics.tail) == 6  # 2 levels x 3 methods


def test_tail_risk_lookup() -> None:
    metrics = RiskMetrics.from_returns(RETURNS, periods_per_year=252, levels=(0.9,))

    entry = metrics.tail_risk(0.9, "gaussian")

    assert entry.method is VaRMethod.GAUSSIAN
    assert entry.conditional_value_at_risk >= entry.value_at_risk
    with pytest.raises(KeyError):
        metrics.tail_risk(0.99)


def test_risk_free_lowers_the_sharpe_ratio() -> None:
    gross = RiskMetrics.from_returns(RETURNS, periods_per_year=252)
    net = RiskMetrics.from_returns(RETURNS, periods_per_year=252, risk_free_rate=0.04)

    assert net.sharpe_ratio < gross.sharpe_ratio
    assert net.risk_free_rate == 0.04


def test_point_in_time_risk_free_series() -> None:
    rates = pd.Series([0.03, 0.03, 0.04, 0.04, 0.05, 0.05], index=INDEX)

    metrics = RiskMetrics.from_returns(RETURNS, periods_per_year=252, risk_free_rate=rates)

    assert metrics.risk_free_rate == pytest.approx(0.04)


def test_two_returns_are_required() -> None:
    with pytest.raises(DomainError):
        RiskMetrics.from_returns(RETURNS.iloc[:1], periods_per_year=252)


def test_price_series_metrics_and_beta() -> None:
    index = pd.bdate_range("2023-01-02", periods=260)
    market = make_series(gbm_prices(260, seed=11), symbol="MKT", index=index)
    asset = make_series(gbm_prices(260, seed=12), symbol="ASSET", index=index)

    metrics = asset.metrics(risk_free_rate=0.02)

    assert metrics.periods == 259
    assert metrics.annualized_volatility == pytest.approx(asset.stats.annualized_volatility)
    assert metrics.total_return == pytest.approx(asset.stats.total_return)
    assert market.beta(market) == pytest.approx(1.0)
    assert math.isfinite(asset.beta(market))
