"""Failures of the data sources and of the server, as Problem Details."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from investinglab.ports import ProviderDataError, ProviderUnavailableError
from investinglab.toolkit import AsyncToolkit
from investinglab_api.app import create_app
from investinglab_api.settings import ApiSettings

if TYPE_CHECKING:
    from investinglab.config import Settings
    from support.fakes import FakeBarsProvider


def _client(bars: FakeBarsProvider, core_settings: Settings) -> TestClient:
    toolkit = AsyncToolkit.from_settings(core_settings, providers=[bars], cache=False)
    app = create_app(ApiSettings(), core_settings=core_settings, toolkit=toolkit)
    return TestClient(app, raise_server_exceptions=False)


def test_a_failing_source_is_unavailable_and_retryable(
    bars: FakeBarsProvider, core_settings: Settings
) -> None:
    bars.errors = {"AAA.MC": ProviderUnavailableError("synthetic", "HTTP 503")}

    with _client(bars, core_settings) as client:
        response = client.get("/api/v1/market/bars", params={"symbol": "AAA.MC"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.json()["type"].endswith("#data-unavailable")


def test_a_malformed_answer_is_unavailable_but_not_retried(
    bars: FakeBarsProvider, core_settings: Settings
) -> None:
    bars.errors = {"AAA.MC": ProviderDataError("synthetic", "garbled payload")}

    with _client(bars, core_settings) as client:
        response = client.get("/api/v1/market/bars", params={"symbol": "AAA.MC"})

    assert response.status_code == 503
    assert "Retry-After" not in response.headers


def test_a_wrong_method_is_an_http_problem_with_its_headers(
    bars: FakeBarsProvider, core_settings: Settings
) -> None:
    with _client(bars, core_settings) as client:
        response = client.delete("/api/v1/market/compare")

    assert response.status_code == 405
    assert response.json()["type"].endswith("#http-error")
    assert response.headers["Allow"] == "POST"


def test_a_timeout_is_a_gateway_timeout(bars: FakeBarsProvider, core_settings: Settings) -> None:
    bars.errors = {"AAA.MC": TimeoutError("provider took too long")}  # type: ignore[dict-item]

    with _client(bars, core_settings) as client:
        response = client.get("/api/v1/market/bars", params={"symbol": "AAA.MC"})

    assert response.status_code == 504
    assert response.json()["type"].endswith("#timeout")


def test_an_unexpected_error_hides_its_internals(
    bars: FakeBarsProvider, core_settings: Settings
) -> None:
    bars.errors = {"AAA.MC": RuntimeError("secret internals")}  # type: ignore[dict-item]

    with _client(bars, core_settings) as client:
        response = client.get("/api/v1/market/bars", params={"symbol": "AAA.MC"})

    assert response.status_code == 500
    problem = response.json()
    assert problem["type"].endswith("#internal-error")
    assert "secret" not in response.text
    assert problem["instance"] == f"urn:request:{response.headers['X-Request-ID']}"


def test_an_unknown_route_is_a_not_found_problem(
    bars: FakeBarsProvider, core_settings: Settings
) -> None:
    with _client(bars, core_settings) as client:
        response = client.get("/api/v1/nothing-here")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
