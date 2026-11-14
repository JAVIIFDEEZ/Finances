"""Market endpoints over SYNTHETIC data: bars, flow, holding rates, comparisons and quality."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from investinglab.domain import OVERNIGHT_ACT_360

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_bars_come_with_metadata_provenance_and_statistics(client: TestClient) -> None:
    response = client.get(
        "/api/v1/market/bars",
        params={"symbol": "AAA.MC", "start": "2023-03-01", "end": "2023-03-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["instrument"]["symbol"] == "AAA.MC"
    assert body["instrument"]["currency"] == "EUR"
    assert body["instrument"]["exchange"]["code"] == "XMAD"
    assert body["frequency"] == "1d"
    assert body["source"]["provider"] == "synthetic"
    assert body["bars"][0]["time"] == "2023-03-01"  # a session date, not an instant
    assert body["bars"][-1]["time"] == "2023-03-31"
    assert body["bars"][0]["open"] is None  # absent columns are null, never invented
    assert body["stats"]["n_observations"] == len(body["bars"])


def test_intraday_bars_are_instants_in_utc(client: TestClient) -> None:
    body = client.get(
        "/api/v1/market/bars", params={"symbol": "HOURLY.MC", "interval": "1h"}
    ).json()

    assert body["frequency"] == "1h"
    assert body["bars"][0]["time"] == "2024-03-04T08:00:00Z"


def test_an_unknown_symbol_is_a_data_not_found_problem(client: TestClient) -> None:
    response = client.get("/api/v1/market/bars", params={"symbol": "NOPE.MC"})

    assert response.status_code == 404
    problem = response.json()
    assert problem["type"].endswith("#data-not-found")
    assert problem["attempts"] == [
        {
            "provider": "synthetic",
            "error": "SymbolNotFoundError",
            "message": problem["attempts"][0]["message"],
        }
    ]
    assert problem["instance"] == f"urn:request:{response.headers['X-Request-ID']}"


@pytest.mark.parametrize(
    ("params", "location"),
    [
        ({"symbol": "bad symbol!"}, ["query", "symbol"]),
        ({"symbol": "AAA.MC", "interval": "2d"}, ["query", "interval"]),
        ({}, ["query", "symbol"]),
    ],
)
def test_malformed_queries_are_invalid_request_problems(
    client: TestClient, params: dict[str, str], location: list[str]
) -> None:
    response = client.get("/api/v1/market/bars", params=params)

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"].endswith("#invalid-request")
    assert problem["errors"][0]["location"] == location


def test_inverted_dates_are_a_domain_problem(client: TestClient) -> None:
    response = client.get(
        "/api/v1/market/bars",
        params={"symbol": "AAA.MC", "start": "2024-01-01", "end": "2023-01-01"},
    )

    assert response.status_code == 422
    assert "after end" in response.json()["detail"]


def test_comparisons_rebase_to_100_and_report_failures(client: TestClient) -> None:
    response = client.post(
        "/api/v1/market/compare",
        json={"symbols": ["AAA.MC", "BBB.MC", "NOPE.MC"], "start": "2023-01-02"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [s["instrument"]["symbol"] for s in body["series"]] == ["AAA.MC", "BBB.MC"]
    first = body["series"][0]
    assert first["performance"][0]["value"] == pytest.approx(100.0)
    assert first["drawdown"][0]["value"] == pytest.approx(0.0)
    assert first["metrics"]["risk_free_coverage"] > 0  # the synthetic €STR is used
    assert body["correlation"]["labels"] == ["AAA.MC", "BBB.MC"]
    assert body["correlation"]["values"][0][0] == pytest.approx(1.0)
    assert body["failed"][0]["symbol"] == "NOPE.MC"


def test_inverted_dates_in_a_body_are_an_invalid_request(client: TestClient) -> None:
    response = client.post(
        "/api/v1/market/compare",
        json={"symbols": ["AAA.MC"], "start": "2024-01-01", "end": "2023-01-01"},
    )

    assert response.status_code == 422
    assert "is after end" in response.json()["errors"][0]["message"]


def test_a_single_instrument_has_no_correlation(client: TestClient) -> None:
    body = client.post("/api/v1/market/compare", json={"symbols": ["AAA.MC"]}).json()

    assert body["correlation"] is None


def test_a_comparison_of_unknown_instruments_is_not_found(client: TestClient) -> None:
    response = client.post("/api/v1/market/compare", json={"symbols": ["NOPE.MC", "NADA.MC"]})

    assert response.status_code == 404
    assert len(response.json()["attempts"]) == 2


def test_requests_above_the_limits_are_refused(client: TestClient) -> None:
    symbols = [f"S{i}.MC" for i in range(26)]

    response = client.post("/api/v1/market/compare", json={"symbols": symbols})

    assert response.status_code == 422
    assert response.json()["detail"] == "At most 25 symbols per request, got 26"


def test_unknown_fields_are_refused(client: TestClient) -> None:
    response = client.post(
        "/api/v1/market/compare", json={"symbols": ["AAA.MC"], "unexpected": True}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["location"] == ["body", "unexpected"]


def test_quality_is_checked_against_the_official_calendar(client: TestClient) -> None:
    body = client.get("/api/v1/market/quality", params={"symbol": "AAA.MC"}).json()

    assert body["symbol"] == "AAA.MC"
    assert body["observations"] == 600
    assert body["expected_sessions"] is not None
    assert isinstance(body["ok"], bool)
    for issue in body["issues"]:
        assert len(issue["examples"]) <= min(issue["count"], 10) or issue["count"] == 0


def test_risk_free_rates_are_known_only_after_publication(client: TestClient) -> None:
    body = client.get(
        "/api/v1/rates/risk-free",
        params={"currency": "EUR", "start": "2022-11-28", "end": "2023-01-06"},
    ).json()

    rates = {point["time"]: point["value"] for point in body["rates"]}
    assert body["currency"] == "EUR"
    assert rates["2022-11-28"] is None  # nothing published yet
    # 3 % quoted ACT/360, compounded daily for a year.
    assert rates["2023-01-02"] == pytest.approx(OVERNIGHT_ACT_360.effective_annual(0.03))


# ── Trade flow and holding rates (SYNTHETIC) ─────────────────────────


def test_flow_with_aggressor_side_brings_delta_and_cvd(client: TestClient) -> None:
    response = client.get(
        "/api/v1/market/flow",
        params={"symbol": "SYN/USDT", "start": "2023-01-02", "end": "2023-01-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_aggressor_side"] is True
    assert body["columns"] == ["volume", "quote_volume", "trades", "buy_volume"]
    first, last = body["bars"][0], body["bars"][-1]
    assert first["time"] == "2023-01-02"
    assert first["delta"] == pytest.approx(2 * first["buy_volume"] - first["volume"])
    assert first["sell_volume"] == pytest.approx(first["volume"] - first["buy_volume"])
    assert first["vwap"] == pytest.approx(50.0)
    assert last["cvd"] == pytest.approx(sum(bar["delta"] for bar in body["bars"]))
    summary = body["summary"]
    assert summary["delta"] == pytest.approx(last["cvd"])
    assert summary["volume"] == pytest.approx(sum(bar["volume"] for bar in body["bars"]))
    assert 0.0 < summary["buy_ratio"] < 1.0
    assert body["source"]["provider"] == "synthetic"


def test_flow_of_a_listed_share_is_its_volume_only(client: TestClient) -> None:
    body = client.get("/api/v1/market/flow", params={"symbol": "AAA.MC"}).json()

    assert body["has_aggressor_side"] is False
    assert body["columns"] == ["volume"]
    bar = body["bars"][0]
    assert bar["delta"] is bar["cvd"] is bar["buy_ratio"] is bar["vwap"] is None
    assert body["summary"]["delta"] is None
    assert body["summary"]["buy_ratio"] is None


def test_flow_nobody_serves_is_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/market/flow", params={"symbol": "BBB.MC"})

    assert response.status_code == 404
    assert response.json()["type"].endswith("#data-not-found")


def test_funding_comes_with_its_interval_and_accumulation(client: TestClient) -> None:
    response = client.get(
        "/api/v1/market/holding-rates",
        params={"symbol": "SYN/USDT:USDT", "kind": "funding"},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["venue"], body["kind"], body["payer"], body["exchanged"]) == (
        "synthetic-venue",
        "funding",
        "long",
        True,
    )
    assert body["interval_hours"] == pytest.approx(8.0)
    assert body["periods_per_year"] == pytest.approx(1095.0)
    rates = body["rates"]
    assert rates[0]["time"] == "2024-03-01T00:00:00Z"
    assert rates[0]["annualized"] == pytest.approx(rates[0]["rate"] * 1095.0)
    assert rates[-1]["accumulated_long"] == pytest.approx(-sum(r["rate"] for r in rates))
    summary = body["summary"]
    assert summary["payments"] == 30
    assert summary["accumulated_short"] == pytest.approx(-summary["accumulated_long"])
    assert 0.0 <= summary["positive_share"] <= 1.0


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"symbol": "SYN/USDT:USDT", "venue": "other"}, 404),
        ({"symbol": "SYN/USDT:USDT", "kind": "rebate"}, 422),
        ({"symbol": "SYN/USDT:USDT", "venue": "Not A Venue"}, 422),
        ({"symbol": "NOPE/USDT:USDT"}, 404),
    ],
    ids=["other-venue", "unknown-kind", "bad-venue", "unknown-swap"],
)
def test_rates_requests_are_checked(
    client: TestClient, params: dict[str, str], status: int
) -> None:
    assert client.get("/api/v1/market/holding-rates", params=params).status_code == status


# ── Technical indicators (SYNTHETIC) ─────────────────────────────────


def test_technical_indicators_of_a_series_of_closes(client: TestClient) -> None:
    response = client.get(
        "/api/v1/market/technical",
        params={"symbol": "AAA.MC", "start": "2024-01-02", "end": "2024-06-28"},
    )

    assert response.status_code == 200
    body = response.json()
    names = {indicator["name"] for indicator in body["indicators"]}
    assert {"RSI", "MACD_LINE", "BB_UPPER", "SMA"} <= names
    unavailable = {item["name"]: item["missing"] for item in body["unavailable"]}
    assert unavailable["ADX"] == ["high", "low"]  # synthetic closes only
    assert names.isdisjoint(unavailable)
    rsi = next(i for i in body["indicators"] if i["name"] == "RSI")
    assert (rsi["kind"], rsi["parameters"], rsi["threshold"]) == (
        "oscillator",
        {"window": 14},
        [15.0, 85.0],
    )
    assert rsi["values"][0]["time"] == "2024-01-02"
    assert rsi["values"][0]["value"] is not None  # warmed up on the bars before the start
    assert rsi["latest"] == rsi["values"][-1]["value"]
    sma = next(i for i in body["indicators"] if i["name"] == "SMA")
    assert (sma["kind"], sma["threshold"]) == ("level", None)


def test_a_selection_of_indicators(client: TestClient) -> None:
    body = client.get(
        "/api/v1/market/technical",
        params=[("symbol", "AAA.MC"), ("name", "RSI"), ("name", "EMA")],
    ).json()

    assert [i["name"] for i in body["indicators"]] == ["RSI", "EMA"]
    assert body["unavailable"] == []


def test_an_unknown_indicator_is_an_invalid_request(client: TestClient) -> None:
    response = client.get("/api/v1/market/technical", params={"symbol": "AAA.MC", "name": "NOPE"})

    assert response.status_code == 422
    assert "Unknown indicators" in response.json()["detail"]
