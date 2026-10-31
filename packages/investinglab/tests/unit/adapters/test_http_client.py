from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
import respx
import structlog

from investinglab.adapters.http import HttpClient, RetryPolicy, redact
from investinglab.config import LogFormat, LogLevel, configure_logging
from investinglab.ports import (
    AuthenticationError,
    ProviderDataError,
    ProviderUnavailableError,
    RateLimit,
    RateLimitedError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)

BASE = "https://api.example.test"


class _Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _client(sleep: _Sleeps, attempts: int = 3, **kwargs: object) -> HttpClient:
    return HttpClient(
        "example",
        base_url=BASE,
        retry=RetryPolicy(max_attempts=attempts, initial_backoff=0.5, max_backoff=10),
        sleep=sleep,
        **kwargs,  # type: ignore[arg-type]
    )


@respx.mock
async def test_get_json_success_with_identifying_user_agent() -> None:
    route = respx.get(f"{BASE}/series").respond(json={"ok": True})

    async with _client(_Sleeps()) as client:
        assert await client.get_json("/series", {"id": "X", "unused": None}) == {"ok": True}

    request = route.calls.last.request
    assert request.headers["User-Agent"].startswith("InvestingLab/")
    assert request.url.params == httpx.QueryParams({"id": "X"})


@respx.mock
async def test_transient_errors_are_retried_with_backoff() -> None:
    respx.get(f"{BASE}/series").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("boom"),
            httpx.Response(200, text="a,b"),
        ]
    )
    sleeps = _Sleeps()

    async with _client(sleeps) as client:
        assert await client.get_text("/series") == "a,b"

    assert len(sleeps.waits) == 2
    assert all(0 < wait <= 10 for wait in sleeps.waits)


@respx.mock
async def test_retry_after_is_honoured_and_capped() -> None:
    respx.get(f"{BASE}/series").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(429, headers={"Retry-After": "120"}),
            httpx.Response(200, json=[]),
        ]
    )
    sleeps = _Sleeps()

    async with _client(sleeps) as client:
        assert await client.get_json("/series") == []

    assert sleeps.waits == [2.0, 10.0]


@respx.mock
async def test_retries_are_bounded() -> None:
    route = respx.get(f"{BASE}/series").respond(500)

    async with _client(_Sleeps(), attempts=2) as client:
        with pytest.raises(ProviderUnavailableError, match="HTTP 500"):
            await client.get_json("/series")

    assert route.call_count == 2


@respx.mock
async def test_timeouts_become_unavailable_errors() -> None:
    respx.get(f"{BASE}/series").mock(side_effect=httpx.ReadTimeout("slow"))

    async with _client(_Sleeps(), attempts=1) as client:
        with pytest.raises(ProviderUnavailableError, match="timeout"):
            await client.get_json("/series")


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (404, SymbolNotFoundError),
        (400, UnsupportedRequestError),
    ],
)
@respx.mock
async def test_client_errors_are_translated_and_not_retried(
    status: int, error: type[Exception]
) -> None:
    route = respx.get(f"{BASE}/series").respond(status)

    async with _client(_Sleeps()) as client:
        with pytest.raises(error):
            await client.get_json("/series")

    assert route.call_count == 1


@respx.mock
async def test_rate_limited_error_without_usable_retry_after() -> None:
    respx.get(f"{BASE}/series").respond(
        429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
    )

    async with _client(_Sleeps(), attempts=1) as client:
        with pytest.raises(RateLimitedError) as caught:
            await client.get_json("/series")

    assert caught.value.retry_after is None


@respx.mock
async def test_invalid_json_is_a_data_error() -> None:
    respx.get(f"{BASE}/series").respond(200, text="<html>")

    async with _client(_Sleeps()) as client:
        with pytest.raises(ProviderDataError, match="invalid JSON"):
            await client.get_json("/series")


@respx.mock
async def test_rate_limits_are_applied() -> None:
    respx.get(f"{BASE}/series").respond(json={})

    async with _client(_Sleeps(), rate_limits=[RateLimit(1, 3600)]) as client:
        await client.get_json("/series")
        with pytest.raises(TimeoutError):
            # The quota (1 call per hour) is exhausted: the next call must wait.
            await asyncio.wait_for(client.get_json("/series"), timeout=0.05)

    assert client.provider == "example"


def test_redact_hides_credentials() -> None:
    assert redact({"series_id": "UNRATE", "api_key": "secret", "apikey": "x", "Token": "t"}) == {
        "series_id": "UNRATE",
        "api_key": "***",
        "apikey": "***",
        "Token": "***",
    }
    assert redact(None) == {}


@respx.mock
async def test_credentials_never_reach_the_logs(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{BASE}/series").respond(json={})
    configure_logging(LogLevel.DEBUG, LogFormat.JSON)
    try:
        async with _client(_Sleeps()) as client:
            await client.get_json("/series", {"series_id": "UNRATE", "api_key": "super-secret"})
    finally:
        logging.getLogger().handlers.clear()
        structlog.reset_defaults()

    output = capsys.readouterr().err
    assert "super-secret" not in output
    record = next(json.loads(line) for line in output.splitlines() if "http_request" in line)
    assert record["params"] == {"series_id": "UNRATE", "api_key": "***"}
