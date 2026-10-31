from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    EXCHANGES,
    DomainError,
    Frequency,
    Portfolio,
    PriceSeries,
    RebalancePolicy,
)
from support.factories import gbm_prices, make_series

INDEX = pd.bdate_range("2024-01-01", "2024-06-28")


def _assets() -> list[PriceSeries]:
    n = len(INDEX)
    return [
        make_series(gbm_prices(n, seed=1, sigma=0.15), symbol="A", index=INDEX),
        make_series(gbm_prices(n, seed=2, sigma=0.30), symbol="B", index=INDEX),
        make_series(gbm_prices(n, seed=3, sigma=0.20), symbol="C", index=INDEX),
    ]


def _portfolio(policy: RebalancePolicy | None = None) -> Portfolio:
    return Portfolio.from_weights("Synthetic", _assets(), [0.5, 0.3, 0.2], rebalance=policy)


def test_monthly_rebalancing_happens_on_the_last_session_of_each_month() -> None:
    backtest = _portfolio().backtest(initial_value=100.0)

    month_ends = pd.Series(INDEX, index=INDEX).groupby(INDEX.to_period("M")).max()
    assert list(backtest.rebalance_dates) == list(month_ends.iloc[:-1])
    assert backtest.values.iloc[0] == 100.0
    assert backtest.start == INDEX[0]
    assert backtest.end == INDEX[-1]
    assert backtest.total_turnover > 0
    assert np.allclose(backtest.weights.loc[backtest.rebalance_dates[0]], [0.5, 0.3, 0.2])
    assert (backtest.staleness == 0).all().all()
    assert backtest.drawdown().max() == 0.0


@pytest.mark.parametrize(
    ("policy", "rebalances"),
    [
        (RebalancePolicy.buy_and_hold(), 0),
        (RebalancePolicy.periodic(Frequency.QUARTER_1), 1),
        (RebalancePolicy.periodic(Frequency.YEAR_1), 0),
        (RebalancePolicy.periodic(Frequency.WEEK_1), 25),
    ],
)
def test_rebalancing_policies(policy: RebalancePolicy, rebalances: int) -> None:
    assert len(_portfolio(policy).backtest().rebalance_dates) == rebalances


def test_daily_rebalancing_keeps_constant_weights() -> None:
    portfolio = _portfolio(RebalancePolicy.periodic(Frequency.DAY_1))

    returns = portfolio.returns()

    expected = portfolio.aligned().returns.iloc[1:].to_numpy() @ np.array([0.5, 0.3, 0.2])
    assert returns.to_numpy() == pytest.approx(expected)


def test_threshold_policy_uses_its_band() -> None:
    tight = _portfolio(RebalancePolicy.threshold(0.01)).backtest()
    loose = _portfolio(RebalancePolicy.threshold(0.5)).backtest()

    assert len(tight.rebalance_dates) > 0
    assert len(loose.rebalance_dates) == 0


def test_backtest_starts_when_every_holding_has_been_observed() -> None:
    late = make_series(gbm_prices(len(INDEX) - 10, seed=4), symbol="LATE", index=INDEX[10:])
    portfolio = Portfolio.from_weights("Late", [_assets()[0], late], [0.5, 0.5])

    assert portfolio.backtest().start == INDEX[10]
    assert portfolio.value_history(10.0).iloc[0] == 10.0


def test_holidays_are_marked_stale_not_invented() -> None:
    madrid = INDEX.drop([pd.Timestamp("2024-04-01")])  # Easter Monday
    san = make_series(gbm_prices(len(madrid), seed=5), symbol="SAN.MC", index=madrid)
    spy = make_series(gbm_prices(len(INDEX), seed=6), symbol="SPY", index=INDEX)

    backtest = Portfolio.from_weights("Global", [san, spy], [0.5, 0.5]).backtest()

    assert backtest.staleness.loc["2024-04-01", "SAN.MC"] == 1
    assert len(backtest.values) == len(INDEX)


def test_portfolio_metrics() -> None:
    metrics = _portfolio().metrics(risk_free_rate=0.02, levels=(0.95,))

    assert metrics.periods == len(INDEX) - 1
    assert metrics.periods_per_year == 252
    assert metrics.tail_risk(0.95).value_at_risk > 0


def test_correlation_daily_and_weekly() -> None:
    portfolio = _portfolio()

    daily = portfolio.correlation()
    weekly = portfolio.correlation("1w")

    assert list(daily.columns) == ["A", "B", "C"]
    assert np.allclose(np.diag(daily), 1.0)
    assert np.allclose(np.diag(weekly), 1.0)
    assert len(portfolio.asset_returns("1w")) < len(portfolio.asset_returns())


def test_risk_contributions_table() -> None:
    table = _portfolio().risk_contributions()

    assert list(table.index) == ["A", "B", "C"]
    assert table["share"].sum() == pytest.approx(1.0)
    assert table["share"]["B"] > table["weight"]["B"]  # the most volatile asset
    assert (table["annualized_contribution"] > table["contribution"]).all()


def test_concentration() -> None:
    portfolio = Portfolio.equal_weight("Equal", _assets())

    assert portfolio.herfindahl_index == pytest.approx(1 / 3)
    assert portfolio.effective_number_of_assets == pytest.approx(3.0)


def test_initial_value_must_be_positive() -> None:
    with pytest.raises(DomainError):
        _portfolio().backtest(initial_value=0.0)


def test_intraday_portfolio_rebalances_daily() -> None:
    index = pd.DatetimeIndex([])
    for day in pd.bdate_range("2024-03-04", periods=3):
        index = pd.DatetimeIndex(
            index.append(
                pd.date_range(day + pd.Timedelta(hours=15), periods=3, freq="1h", tz="UTC")
            )
        )
    a = make_series(
        gbm_prices(9, seed=7),
        symbol="A",
        index=index,
        frequency=Frequency.HOUR_1,
        exchange=EXCHANGES["XNYS"],
    )
    b = make_series(
        gbm_prices(9, seed=8),
        symbol="B",
        index=index,
        frequency=Frequency.HOUR_1,
        exchange=EXCHANGES["XNYS"],
    )
    portfolio = Portfolio.from_weights(
        "Intraday", [a, b], [0.5, 0.5], rebalance=RebalancePolicy.periodic(Frequency.DAY_1)
    )

    backtest = portfolio.backtest()

    assert len(backtest.rebalance_dates) == 2  # end of the first two sessions
    assert math.isfinite(portfolio.metrics().annualized_volatility)
