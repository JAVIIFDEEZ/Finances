"""Monte Carlo, optimisation and savings plans over SYNTHETIC series."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

    type Body = dict[str, object]


def test_simulations_return_the_fan_the_distribution_and_tail_risk(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post(
        "/api/v1/simulations",
        json={"portfolio": portfolio(), "n_paths": 1_000, "horizon": 60, "seed": 7},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["n_paths"], body["horizon"], body["model"]) == (1_000, 60, "gbm")
    assert len(body["fan"]) == 61
    first, last = body["fan"][0], body["fan"][-1]
    assert first["p50"] == pytest.approx(10_000.0)
    assert last["p5"] <= last["p50"] <= last["p95"]
    assert sum(b["count"] for b in body["terminal_histogram"]) == 1_000
    assert [v["level"] for v in body["value_at_risk"]] == [0.95, 0.99]
    var95 = body["value_at_risk"][0]
    assert var95["lower"] <= var95["value"] <= var95["upper"]
    assert body["calibration"]["symbols"] == ["AAA.MC", "BBB.MC", "CCC.MC"]


def test_the_same_seed_gives_the_same_simulation(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    request = {"portfolio": portfolio(), "n_paths": 500, "horizon": 20, "seed": 3}

    first = client.post("/api/v1/simulations", json=request).json()
    second = client.post("/api/v1/simulations", json=request).json()

    assert first["fan"] == second["fan"]


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"n_paths": 50_000}, "At most 20000 paths per request, got 50000"),
        ({"horizon": 3_000}, "At most 2520 periods of horizon per request, got 3000"),
    ],
)
def test_simulations_above_the_limits_are_refused(
    client: TestClient, portfolio: Callable[..., Body], changes: Body, detail: str
) -> None:
    response = client.post("/api/v1/simulations", json={"portfolio": portfolio(), **changes})

    assert response.status_code == 422
    assert response.json()["detail"] == detail


def test_optimisation_returns_weights_and_the_frontier(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post(
        "/api/v1/optimizations",
        json={"portfolio": portfolio(), "objective": "min_variance", "frontier_points": 12},
    )

    assert response.status_code == 200
    body = response.json()
    weights = body["result"]["weights"]
    assert sum(w["weight"] for w in weights) == pytest.approx(1.0)
    assert [w["previous_weight"] for w in weights] == [0.5, 0.3, 0.2]
    assert len(body["frontier"]) == 12
    assert {a["symbol"] for a in body["assets"]} == {"AAA.MC", "BBB.MC", "CCC.MC"}
    minimum = body["minimum_variance"]
    assert minimum["volatility"] == pytest.approx(body["result"]["volatility"], rel=1e-6)
    assert body["observations"] > 50  # weekly returns by default


def test_optimisation_without_a_frontier(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    body = client.post(
        "/api/v1/optimizations",
        json={"portfolio": portfolio(), "objective": "risk_parity", "frontier_points": 0},
    ).json()

    assert body["frontier"] == []
    assert body["minimum_variance"] is None
    shares = [c["share"] for c in body["result"]["risk_contributions"]]
    assert shares == pytest.approx([1 / 3] * 3, abs=1e-4)


def test_infeasible_optimisation_bounds_are_a_problem(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post(
        "/api/v1/optimizations",
        json={"portfolio": portfolio(), "max_weight": 0.2, "frontier_points": 0},
    )

    assert response.status_code == 422


def test_savings_plans_give_the_odds_of_the_goal(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    response = client.post(
        "/api/v1/plans",
        json={
            "portfolio": portfolio(),
            "years": 10,
            "initial": 5_000,
            "contribution": 200,
            "goal": 40_000,
            "n_paths": 1_000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["months"] == 120
    assert len(body["fan"]) == 121
    assert body["fan"][0]["contributed"] == pytest.approx(5_000)
    assert 0 <= body["probability_of_success"] <= 1
    assert body["required_contribution"] is not None
    assert body["currency"] == "EUR"


def test_a_plan_without_a_goal_has_no_required_contribution(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    body = client.post(
        "/api/v1/plans", json={"portfolio": portfolio(), "years": 5, "n_paths": 200}
    ).json()

    assert body["goal"] is None
    assert body["probability_of_success"] is None
    assert body["required_contribution"] is None
