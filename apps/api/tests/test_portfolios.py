"""Portfolio endpoints over SYNTHETIC series: validation, analytics and reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

    type Body = dict[str, object]


def test_valid_weights_pass_without_downloading(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post("/api/v1/portfolios/validate", json=portfolio())

    assert response.json() == {"valid": True, "total_weight": pytest.approx(1.0), "problems": []}


@pytest.mark.parametrize(
    ("holdings", "allow_short", "problem"),
    [
        ([{"symbol": "AAA.MC", "weight": 0.5}], False, "weights must sum to 1, got 0.500000"),
        (
            [{"symbol": "AAA.MC", "weight": 1.5}, {"symbol": "BBB.MC", "weight": -0.5}],
            False,
            "negative weights for ['BBB.MC']; pass allow_short=True to allow them",
        ),
    ],
)
def test_invalid_weights_are_explained(
    client: TestClient,
    portfolio: Callable[..., Body],
    holdings: list[dict[str, object]],
    allow_short: bool,
    problem: str,
) -> None:
    body = portfolio(holdings=holdings, allow_short=allow_short)

    response = client.post("/api/v1/portfolios/validate", json=body)

    assert response.json()["valid"] is False
    assert response.json()["problems"] == [problem]


def test_duplicated_holdings_are_an_invalid_request(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    holdings = [{"symbol": "AAA.MC", "weight": 0.5}, {"symbol": "AAA.MC", "weight": 0.5}]

    response = client.post("/api/v1/portfolios/validate", json=portfolio(holdings=holdings))

    assert response.status_code == 422
    assert "duplicated symbols" in response.json()["errors"][0]["message"]


def test_analytics_describe_history_risk_and_co_movement(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post("/api/v1/portfolios/analytics", json=portfolio())

    assert response.status_code == 200
    body = response.json()
    assert body["base_currency"] == "EUR"
    assert body["rebalance"] == "periodic (1mo)" or "1mo" in body["rebalance"]
    assert [h["symbol"] for h in body["holdings"]] == ["AAA.MC", "BBB.MC", "CCC.MC"]
    assert body["value"][0]["value"] == pytest.approx(100.0)
    assert len(body["value"]) == len(body["drawdown"])
    assert body["metrics"]["risk_free_coverage"] == pytest.approx(1.0)
    assert body["metrics"]["sharpe_ratio"] is not None
    assert body["correlation"]["labels"] == ["AAA.MC", "BBB.MC", "CCC.MC"]
    shares = [c["share"] for c in body["risk_contributions"]]
    assert sum(shares) == pytest.approx(1.0)
    assert 1.0 <= body["effective_number_of_assets"] <= 3.0
    assert body["drawdown_episodes"][0]["depth"] < 0


def test_foreign_holdings_are_converted_to_the_base_currency(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    holdings = [{"symbol": "AAA.MC", "weight": 0.6}, {"symbol": "USD.US", "weight": 0.4}]

    mixed = client.post("/api/v1/portfolios/analytics", json=portfolio(holdings=holdings))
    in_euros = client.post(
        "/api/v1/portfolios/analytics", json=portfolio(holdings=holdings, base_currency="EUR")
    )

    assert mixed.status_code == 422
    assert "pass base_currency" in mixed.json()["detail"]
    assert in_euros.status_code == 200
    usd = next(h for h in in_euros.json()["holdings"] if h["symbol"] == "USD.US")
    assert usd["currency"] == "EUR"  # converted with the synthetic USD→EUR fixings


def test_a_portfolio_with_an_unknown_holding_is_not_found(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    holdings = [{"symbol": "AAA.MC", "weight": 0.5}, {"symbol": "NOPE.MC", "weight": 0.5}]

    response = client.post("/api/v1/portfolios/analytics", json=portfolio(holdings=holdings))

    assert response.status_code == 404


def test_the_report_is_markdown_in_the_requested_language(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post("/api/v1/portfolios/report", params={"language": "en"}, json=portfolio())

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text.startswith("# ")
    assert "Synthetic core" in response.text


def test_rebalancing_policies_are_honoured(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    hold = client.post(
        "/api/v1/portfolios/analytics", json=portfolio(rebalance={"kind": "buy_and_hold"})
    ).json()
    band = client.post(
        "/api/v1/portfolios/analytics",
        json=portfolio(rebalance={"kind": "threshold", "band": 0.05}),
    ).json()

    assert hold["total_turnover"] == pytest.approx(0.0)
    assert "0.05" in band["rebalance"] or "5" in band["rebalance"]
