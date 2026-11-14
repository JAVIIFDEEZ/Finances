"""Health, providers, modules, request ids, CORS and the OpenAPI document."""

from __future__ import annotations

from typing import TYPE_CHECKING

from investinglab import __version__ as core_version
from investinglab_api import __version__

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_health_reports_the_providers_and_the_offline_mode(client: TestClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == ready.status_code == 200
    body = ready.json()
    assert body == {
        "status": "ok",
        "version": __version__,
        "core_version": core_version,
        "providers": ["synthetic", "rates", "synthetic-flow", "synthetic-venue"],
        "offline": True,
        "database": "not_configured",
    }


def test_providers_describe_their_capabilities(client: TestClient) -> None:
    providers = client.get("/api/v1/providers").json()

    assert [p["name"] for p in providers] == [
        "synthetic",
        "rates",
        "synthetic-flow",
        "synthetic-venue",
    ]
    bars = providers[0]
    assert bars["datasets"] == ["bars"]
    assert "1d" in bars["frequencies"]
    assert bars["frequencies"][0] == "1m"  # ordered from the finest
    assert bars["requires_api_key"] is False
    assert bars["rate_kinds"] == []
    assert providers[1]["datasets"] == ["economic"]
    assert providers[2]["datasets"] == ["flow"]
    assert providers[3]["datasets"] == ["holding_rates"]
    assert providers[3]["rate_kinds"] == ["borrow", "financing", "funding"]


def test_modules_carry_their_traceability_in_both_languages(client: TestClient) -> None:
    spanish = client.get("/api/v1/modules").json()
    english = client.get("/api/v1/modules", params={"language": "en"}).json()
    one = client.get("/api/v1/modules/b1-toolkit", params={"language": "en"})

    assert [m["slug"] for m in spanish] == ["b1-toolkit"]
    assert spanish[0]["title"] != english[0]["title"]
    assert one.status_code == 200
    assert one.json() == english[0]
    requirement = one.json()["requirements"][0]
    assert {"id", "title", "status", "code", "tests", "note"} <= set(requirement)


def test_an_unknown_module_is_a_not_found_problem(client: TestClient) -> None:
    response = client.get("/api/v1/modules/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["type"].endswith("#not-found")
    assert problem["detail"] == "No module 'nope'"


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    generated = client.get("/health/live")
    given = client.get("/health/live", headers={"X-Request-ID": "trace-1234567"})
    unsafe = client.get("/health/live", headers={"X-Request-ID": "bad id\n"})

    assert len(generated.headers["X-Request-ID"]) == 32
    assert given.headers["X-Request-ID"] == "trace-1234567"
    assert unsafe.headers["X-Request-ID"] != "bad id\n"


def test_the_web_app_origin_may_call_the_api(client: TestClient) -> None:
    preflight = client.options(
        "/api/v1/market/compare",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    foreign = client.get("/health/live", headers={"Origin": "https://evil.example"})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in foreign.headers


def test_the_openapi_document_describes_every_endpoint(client: TestClient) -> None:
    document = client.get("/openapi.json").json()

    assert document["info"]["title"] == "InvestingLab API"
    assert {
        "/health/live",
        "/health/ready",
        "/api/v1/providers",
        "/api/v1/modules",
        "/api/v1/modules/{slug}",
        "/api/v1/market/bars",
        "/api/v1/market/compare",
        "/api/v1/market/flow",
        "/api/v1/market/technical",
        "/api/v1/market/patterns",
        "/api/v1/market/holding-rates",
        "/api/v1/market/quality",
        "/api/v1/rates/risk-free",
        "/api/v1/economic/series",
        "/api/v1/portfolios",
        "/api/v1/portfolios/{portfolio_id}",
        "/api/v1/portfolios/validate",
        "/api/v1/portfolios/analytics",
        "/api/v1/portfolios/report",
        "/api/v1/simulations",
        "/api/v1/optimizations",
        "/api/v1/plans",
    } == set(document["paths"])
    compare = document["paths"]["/api/v1/market/compare"]["post"]["responses"]
    assert "application/problem+json" in compare["404"]["content"]
    assert "Problem" in document["components"]["schemas"]
