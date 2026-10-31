from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pytest

from investinglab.domain import (
    EUR,
    USD,
    DomainError,
    Frequency,
    Holding,
    InvalidPortfolioError,
    Portfolio,
    PriceSeries,
    RebalanceKind,
    RebalancePolicy,
)
from support.factories import make_series


def _assets() -> list[PriceSeries]:
    return [
        make_series(symbol="SAN.MC"),
        make_series(symbol="ITX.MC"),
        make_series(symbol="BBVA.MC"),
    ]


def test_portfolio_from_a_weight_mapping() -> None:
    portfolio = Portfolio.from_weights(
        "Ibex core", _assets(), {"SAN.MC": 0.5, "ITX.MC": 0.3, "BBVA.MC": 0.2}
    )

    assert portfolio.symbols == ("SAN.MC", "ITX.MC", "BBVA.MC")
    assert portfolio.weights.to_dict() == {"SAN.MC": 0.5, "ITX.MC": 0.3, "BBVA.MC": 0.2}
    assert portfolio.base_currency == EUR
    assert portfolio.frequency is Frequency.DAY_1
    assert portfolio.rebalance == RebalancePolicy.periodic(Frequency.MONTH_1)
    assert portfolio.gross_exposure == pytest.approx(1.0)
    assert len(portfolio) == 3
    assert [h.symbol for h in portfolio] == list(portfolio.symbols)
    assert len(portfolio.series) == 3
    assert "Ibex core" in repr(portfolio)


def test_equal_weight_portfolio() -> None:
    portfolio = Portfolio.equal_weight("Equal", _assets(), rebalance=RebalancePolicy.buy_and_hold())

    assert portfolio.weights.tolist() == pytest.approx([1 / 3] * 3)
    assert portfolio.rebalance.kind is RebalanceKind.BUY_AND_HOLD


def test_aligned_panel_of_the_holdings() -> None:
    panel = Portfolio.equal_weight("Equal", _assets()).aligned()

    assert panel.symbols == ("SAN.MC", "ITX.MC", "BBVA.MC")


def test_short_positions_need_explicit_permission() -> None:
    assets = _assets()[:2]

    with pytest.raises(InvalidPortfolioError, match="allow_short=True"):
        Portfolio.from_weights("Long/short", assets, [1.3, -0.3])

    portfolio = Portfolio.from_weights("Long/short", assets, [1.3, -0.3], allow_short=True)
    assert portfolio.gross_exposure == pytest.approx(1.6)


@pytest.mark.parametrize(
    ("weights", "fragment"),
    [
        ([0.5, 0.3, 0.1], "sum to 1"),
        ([0.6, 0.3, 0.2], "sum to 1"),
        ([0.5, 0.5], "2 weights for 3 series"),
        ({"SAN.MC": 1.0}, "weights missing"),
        ({"SAN.MC": 0.5, "ITX.MC": 0.3, "BBVA.MC": 0.1, "XXX": 0.1}, "unknown symbols"),
    ],
)
def test_invalid_weights_are_rejected(
    weights: dict[str, float] | list[float], fragment: str
) -> None:
    with pytest.raises(InvalidPortfolioError, match=fragment):
        Portfolio.from_weights("Bad", _assets(), weights)


def test_weights_within_tolerance_are_accepted() -> None:
    portfolio = Portfolio.from_weights("Rounded", _assets(), [0.3333333, 0.3333333, 0.3333334])

    assert math.isclose(portfolio.weights.sum(), 1.0)


def test_every_problem_is_reported() -> None:
    usd_asset = make_series(symbol="SPY", currency=USD)
    weekly = make_series(
        symbol="W",
        index=pd.date_range("2024-01-05", periods=5, freq="W-FRI"),
        frequency=Frequency.WEEK_1,
    )
    holdings = (
        Holding(make_series(symbol="A"), 0.5),
        Holding(make_series(symbol="A"), 0.5),
        Holding(usd_asset, 0.4),
        Holding(weekly, -0.1),
    )

    with pytest.raises(InvalidPortfolioError) as caught:
        Portfolio(" ", holdings, EUR)

    problems = " | ".join(caught.value.problems)
    for fragment in (
        "name",
        "duplicated symbols",
        "sum to 1",
        "negative weights",
        "mixed frequencies",
        "base currency",
    ):
        assert fragment in problems


def test_empty_portfolio_is_rejected() -> None:
    with pytest.raises(InvalidPortfolioError, match="at least one holding"):
        Portfolio("Empty", (), EUR)


def test_mixed_currencies_need_an_explicit_base_currency() -> None:
    assets = [make_series(symbol="SAN.MC"), make_series(symbol="SPY", currency=USD)]

    with pytest.raises(InvalidPortfolioError, match="several currencies"):
        Portfolio.from_weights("Global", assets, [0.5, 0.5])
    with pytest.raises(InvalidPortfolioError, match="not in base currency"):
        Portfolio.from_weights("Global", assets, [0.5, 0.5], base_currency=EUR)


def test_holding_weight_must_be_finite() -> None:
    with pytest.raises(DomainError):
        Holding(make_series(), math.nan)


def test_rebalance_policies() -> None:
    assert str(RebalancePolicy.buy_and_hold()) == "buy and hold"
    assert str(RebalancePolicy.periodic("1q")) == "periodic (1q)"
    assert str(RebalancePolicy.threshold(0.05)) == "threshold (±5.0%)"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": RebalanceKind.PERIODIC},
        {"kind": RebalanceKind.PERIODIC, "frequency": Frequency.HOUR_1},
        {"kind": RebalanceKind.PERIODIC, "frequency": Frequency.MONTH_1, "band": 0.1},
        {"kind": RebalanceKind.THRESHOLD},
        {"kind": RebalanceKind.THRESHOLD, "band": 1.5},
        {"kind": RebalanceKind.THRESHOLD, "band": 0.1, "frequency": Frequency.MONTH_1},
        {"kind": RebalanceKind.BUY_AND_HOLD, "band": 0.1},
    ],
)
def test_invalid_rebalance_policies(kwargs: dict[str, Any]) -> None:
    with pytest.raises(DomainError):
        RebalancePolicy(**kwargs)
