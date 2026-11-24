"""Backtests over HTTP on SYNTHETIC series: in the request, in the background, and refused."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from investinglab.analytics.search import CLASSICS
from investinglab.domain import COST_PROFILES
from investinglab_api.jobs import HANDLERS, run_job
from investinglab_api.schemas.backtest import CLASSIC_NAMES
from investinglab_api.settings import ApiSettings

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from investinglab.toolkit import AsyncToolkit
    from support.repositories import InMemoryJobRepository

    type Body = dict[str, Any]

BACKTESTS = "/api/v1/backtests"


def work(client: TestClient, jobs: InMemoryJobRepository, toolkit: AsyncToolkit) -> None:
    """Run every queued job, as a worker would."""

    async def drain() -> None:
        while jobs.queue:
            owner, job_id = jobs.queue.pop(0)
            await run_job(
                jobs, HANDLERS, toolkit=toolkit, settings=ApiSettings(), owner=owner, job_id=job_id
            )

    assert client.portal is not None
    client.portal.call(drain)


def _slope(op: str) -> Body:
    return {"type": "slope", "indicator": "PRICE", "op": op, "bars": 1}


SWING: Body = {
    "entry": {"conditions": [_slope("rising")]},
    "exit": {"conditions": [_slope("falling")]},
    "risk": {"stop_loss_pct": 0.05},
}


def test_a_classic_strategy_with_its_markets_costs(client: TestClient) -> None:
    response = client.post(
        BACKTESTS, json={"symbol": "BARS.MC", "strategy": "sma_crossover", "start": "2024-06-03"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BARS.MC"
    assert body["start"] == "2024-06-03"  # it trades from the start...
    assert body["ready_at"] < "2024-06-03"  # ...with its averages warmed up before it
    assert body["definition_hash"] == CLASSICS["sma_crossover"].definition_hash
    market = body["market"]
    assert market["profile"]["key"] == "XMAD"
    assert market["profile"]["tax"] == "ITF"
    assert "commission_bps" in market["profile"]["assumed"]
    assert market["tax_presumed"] is True
    assert body["costs"]["tax"] > 0
    assert len(body["equity"]) > 100
    assert body["equity"][-1]["value"] == pytest.approx(body["final_equity"])
    assert body["statistics"]["count"] == len(body["trades"])
    assert body["metrics"]["periods_per_year"] == 252


def test_a_strategy_as_data_with_your_brokers_fees(client: TestClient) -> None:
    response = client.post(
        BACKTESTS,
        json={
            "symbol": "BARS.MC",
            "strategy": SWING,
            "commission_bps": 2,
            "taxable": False,
            "initial_capital": 50_000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"]["risk"]["stop_loss_pct"] == 0.05
    assert body["market"]["commission_bps"] == 2
    assert body["costs"]["tax"] == 0
    assert body["initial_capital"] == 50_000
    assert {trade["exit_reason"] for trade in body["trades"]} <= {
        "signal",
        "stop_loss",
        "end_of_data",
    }


@pytest.mark.parametrize(
    ("strategy", "detail"),
    [
        ({**SWING, "risk": {"stop_loss_pct": 5.0}}, "stop_loss_pct must be between 0 and 1"),
        (
            {**SWING, "exit": {"conditions": [{**_slope("rising"), "indicator": "NOPE"}]}},
            "exit.conditions[0]: unknown indicator",
        ),
        ({**SWING, "direction": "both"}, "needs short_entry and short_exit"),
    ],
)
def test_an_invalid_strategy_is_a_problem_saying_where(
    client: TestClient, strategy: Body, detail: str
) -> None:
    response = client.post(BACKTESTS, json={"symbol": "BARS.MC", "strategy": strategy})

    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_what_the_schema_refuses(client: TestClient) -> None:
    unknown = client.post(BACKTESTS, json={"symbol": "BARS.MC", "strategy": "nope"})
    cross = {"type": "cross", "a": {"indicator": "PRICE"}, "b": {"indicator": "SMA"}}
    negated = client.post(
        BACKTESTS,
        json={
            "symbol": "BARS.MC",
            "strategy": {
                **SWING,
                "entry": {"conditions": [{**cross, "op": "cross_above", "negate": True}]},
            },
        },
    )

    assert unknown.status_code == 422
    assert negated.status_code == 422  # a cross has no negation


def test_a_market_that_cannot_be_traded_so(client: TestClient) -> None:
    short = {**SWING, "direction": "short"}

    response = client.post(
        BACKTESTS, json={"symbol": "BARS.MC", "strategy": short, "profile": "binance-spot"}
    )
    unknown = client.post(
        BACKTESTS, json={"symbol": "BARS.MC", "strategy": SWING, "profile": "NOPE"}
    )

    assert response.status_code == 422
    assert "cannot be sold short" in response.json()["detail"]
    assert unknown.status_code == 422
    assert "Unknown cost profile" in unknown.json()["detail"]


def test_the_classics_and_the_cost_profiles_are_listed(client: TestClient) -> None:
    classics = client.get("/api/v1/strategies/classics").json()
    profiles = client.get("/api/v1/cost-profiles").json()

    assert [c["name"] for c in classics] == list(CLASSICS) == list(CLASSIC_NAMES)
    assert classics[0]["definition_hash"] == CLASSICS["rsi_reversal"].definition_hash
    assert {p["key"] for p in profiles} == set(COST_PROFILES)
    paris = next(p for p in profiles if p["key"] == "XPAR")
    assert (paris["tax"], paris["tax_bps"]) == ("TTF", 40.0)
    assert next(p for p in profiles if p["key"] == "binance-usdm")["product"] == "perpetual"


def test_a_backtest_in_the_background_gives_what_the_request_gives(
    client: TestClient, jobs: InMemoryJobRepository, toolkit: AsyncToolkit
) -> None:
    body = {"symbol": "BARS.MC", "strategy": "rsi_reversal", "start": "2024-06-03"}

    submitted = client.post("/api/v1/jobs/backtests", json=body)
    work(client, jobs, toolkit)
    read = client.get(submitted.headers["Location"])
    direct = client.post(BACKTESTS, json=body).json()

    assert submitted.status_code == 202
    assert submitted.json()["kind"] == "backtest"
    job = read.json()
    assert (job["kind"], job["status"], job["progress"]) == ("backtest", "succeeded", 1.0)
    assert job["parameters"]["strategy"] == "rsi_reversal"
    assert job["result"] == direct


def test_a_background_backtest_is_checked_before_it_is_queued(
    client: TestClient, jobs: InMemoryJobRepository
) -> None:
    wrong = {"symbol": "BARS.MC", "strategy": {**SWING, "risk": {"max_bars": 0}}}
    unknown = {"symbol": "BARS.MC", "strategy": SWING, "profile": "NOPE"}

    assert client.post("/api/v1/jobs/backtests", json=wrong).status_code == 422
    assert client.post("/api/v1/jobs/backtests", json=unknown).status_code == 422
    assert not jobs.queue
