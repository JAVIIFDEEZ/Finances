"""Saved portfolios over HTTP: versions, conflicts, owners and the missing database."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from investinglab.ports import RepositoryUnavailableError
from investinglab_api.app import create_app
from investinglab_api.settings import ApiSettings
from support.repositories import InMemoryPortfolioRepository

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from investinglab.config import Settings
    from investinglab.toolkit import AsyncToolkit

type Body = dict[str, object]

URL = "/api/v1/portfolios"
DOCS = "https://github.com/JAVIIFDEEZ/Finances/blob/development/docs/guide/api.md"


def save(client: TestClient, body: Body) -> dict[str, object]:
    response = client.post(URL, json=body)
    assert response.status_code == 201, response.text
    saved: dict[str, object] = response.json()
    return saved


def test_a_portfolio_is_saved_read_and_listed(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    body = portfolio(
        base_currency="EUR",
        start="2023-06-01",
        rebalance={"kind": "threshold", "band": 0.05},
    )

    created = client.post(URL, json=body)

    assert created.status_code == 201
    saved = created.json()
    assert created.headers["ETag"] == '"1"'
    assert created.headers["Location"].endswith(f"{URL}/{saved['id']}")
    assert saved["version"] == 1
    assert saved["portfolio"]["name"] == "Synthetic core"
    assert saved["portfolio"]["holdings"] == body["holdings"]
    assert saved["portfolio"]["rebalance"]["kind"] == "threshold"
    assert saved["portfolio"]["rebalance"]["band"] == 0.05
    assert (saved["portfolio"]["base_currency"], saved["portfolio"]["start"]) == (
        "EUR",
        "2023-06-01",
    )

    read = client.get(f"{URL}/{saved['id']}")
    assert read.json() == saved
    assert read.headers["ETag"] == '"1"'
    assert client.get(URL).json() == {"items": [saved], "next_cursor": None}


def test_a_saved_definition_is_ready_to_analyse(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    saved = save(client, portfolio())

    analysed = client.post(f"{URL}/analytics", json=saved["portfolio"])

    assert analysed.status_code == 200
    assert analysed.json()["name"] == "Synthetic core"


def test_a_change_quotes_the_version_it_read(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    saved = save(client, portfolio())
    url = f"{URL}/{saved['id']}"

    changed = client.put(url, json=portfolio(name="Renamed"), headers={"If-Match": '"1"'})

    assert changed.status_code == 200
    assert changed.headers["ETag"] == '"2"'
    assert (changed.json()["version"], changed.json()["portfolio"]["name"]) == (2, "Renamed")
    assert changed.json()["created_at"] == saved["created_at"]

    stale = client.put(url, json=portfolio(name="Lost update"), headers={"If-Match": '"1"'})

    assert stale.status_code == 412
    assert stale.headers["content-type"] == "application/problem+json"
    assert stale.headers["ETag"] == '"2"'
    problem = stale.json()
    assert problem["type"] == f"{DOCS}#version-conflict"
    assert problem["current_version"] == 2
    assert client.get(url).json()["portfolio"]["name"] == "Renamed"


@pytest.mark.parametrize("method", ["put", "delete"])
def test_a_change_without_a_version_is_refused(
    client: TestClient, portfolio: Callable[..., Body], method: str
) -> None:
    saved = save(client, portfolio())
    url = f"{URL}/{saved['id']}"
    send = client.put if method == "put" else client.delete
    body = {"json": portfolio()} if method == "put" else {}

    missing = send(url, **body)  # type: ignore[arg-type]
    malformed = send(url, headers={"If-Match": "latest"}, **body)  # type: ignore[arg-type]

    assert missing.status_code == 428
    assert missing.json()["type"] == f"{DOCS}#precondition-required"
    assert malformed.status_code == 422
    assert "If-Match" in malformed.json()["detail"]
    assert client.get(url).json()["version"] == 1


def test_a_portfolio_is_deleted_at_the_version_read(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    saved = save(client, portfolio())
    url = f"{URL}/{saved['id']}"

    assert client.delete(url, headers={"If-Match": '"3"'}).status_code == 412
    deleted = client.delete(url, headers={"If-Match": '"1"'})

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(url).status_code == 404
    assert client.get(URL).json()["items"] == []


def test_names_are_unique(client: TestClient, portfolio: Callable[..., Body]) -> None:
    save(client, portfolio())

    again = client.post(URL, json=portfolio())

    assert again.status_code == 409
    assert again.json()["type"] == f"{DOCS}#name-conflict"
    assert "Synthetic core" in again.json()["detail"]


def test_missing_and_malformed_identifiers(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    unknown = client.get(f"{URL}/{uuid4()}")
    update = client.put(f"{URL}/{uuid4()}", json=portfolio(), headers={"If-Match": '"1"'})
    malformed = client.get(f"{URL}/not-a-uuid")

    assert unknown.status_code == 404
    assert unknown.json()["type"] == f"{DOCS}#not-found"
    assert update.status_code == 404
    assert malformed.status_code == 422


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"holdings": [{"symbol": "AAA.MC", "weight": 0.7}]}, "sum"),
        (
            {
                "holdings": [
                    {"symbol": "AAA.MC", "weight": 1.5},
                    {"symbol": "BBB.MC", "weight": -0.5},
                ]
            },
            "short",
        ),
        ({"name": ""}, "schema"),
        ({"unknown": 1}, "schema"),
    ],
    ids=["weights-not-100", "short-not-allowed", "empty-name", "unknown-field"],
)
def test_only_valid_portfolios_are_stored(
    client: TestClient, portfolio: Callable[..., Body], changes: Body, message: str
) -> None:
    refused = client.post(URL, json=portfolio(**changes))

    assert refused.status_code == 422
    assert message in refused.text.lower()
    assert client.get(URL).json()["items"] == []


def test_the_holdings_limit_applies_to_saved_portfolios(
    toolkit: AsyncToolkit, core_settings: Settings, portfolio: Callable[..., Body]
) -> None:
    app = create_app(
        ApiSettings(max_symbols=2),
        core_settings=core_settings,
        toolkit=toolkit,
        portfolios=InMemoryPortfolioRepository(),
    )

    with TestClient(app) as client:
        refused = client.post(URL, json=portfolio())

    assert refused.status_code == 422
    assert "At most 2 holdings" in refused.json()["detail"]


def test_listings_are_paged(client: TestClient, portfolio: Callable[..., Body]) -> None:
    for number in range(3):
        save(client, portfolio(name=f"P{number}"))

    first = client.get(URL, params={"limit": 2}).json()
    second = client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}).json()

    names = [item["portfolio"]["name"] for item in first["items"] + second["items"]]
    assert sorted(names) == ["P0", "P1", "P2"]
    assert second["next_cursor"] is None
    assert client.get(URL, params={"cursor": "nonsense"}).status_code == 422
    assert client.get(URL, params={"limit": 0}).status_code == 422


def test_each_owner_has_their_own_portfolios(
    toolkit: AsyncToolkit, core_settings: Settings, portfolio: Callable[..., Body]
) -> None:
    shared = InMemoryPortfolioRepository()

    def client_of(owner: str) -> TestClient:
        settings = ApiSettings(local_owner=owner)
        return TestClient(
            create_app(settings, core_settings=core_settings, toolkit=toolkit, portfolios=shared)
        )

    with client_of("ana") as ana, client_of("bea") as bea:
        saved = save(ana, portfolio())
        url = f"{URL}/{saved['id']}"

        assert bea.get(URL).json()["items"] == []
        assert bea.get(url).status_code == 404  # not found, never "forbidden"
        assert bea.put(url, json=portfolio(), headers={"If-Match": '"1"'}).status_code == 404
        assert bea.delete(url, headers={"If-Match": '"1"'}).status_code == 404
        assert save(bea, portfolio())["id"] != saved["id"]  # the same name, another owner
        assert ana.get(url).status_code == 200


# ── Without a database, and with one that fails ────────────────────────────


@pytest.fixture
def stateless(toolkit: AsyncToolkit, core_settings: Settings) -> Iterator[TestClient]:
    """The API as it runs with no database configured."""
    with TestClient(
        create_app(ApiSettings(), core_settings=core_settings, toolkit=toolkit)
    ) as client:
        yield client


def test_without_a_database_only_the_stored_endpoints_are_unavailable(
    stateless: TestClient, portfolio: Callable[..., Body]
) -> None:
    listing = stateless.get(URL)
    saving = stateless.post(URL, json=portfolio())

    for response in (listing, saving):
        assert response.status_code == 503
        assert response.json()["type"] == f"{DOCS}#persistence-not-configured"
        assert "INVESTINGLAB_API_DATABASE_URL" in response.json()["detail"]
    assert stateless.post(f"{URL}/analytics", json=portfolio()).status_code == 200
    assert stateless.get("/health/ready").json()["database"] == "not_configured"


def test_an_unreachable_database_is_a_retryable_problem(
    toolkit: AsyncToolkit, core_settings: Settings
) -> None:
    class Broken(InMemoryPortfolioRepository):
        async def list(self, owner: str, *, limit: int = 50, cursor: str | None = None):  # type: ignore[no-untyped-def]
            raise RepositoryUnavailableError("down")

    app = create_app(
        ApiSettings(), core_settings=core_settings, toolkit=toolkit, portfolios=Broken()
    )

    with TestClient(app) as client:
        response = client.get(URL)

    assert response.status_code == 503
    assert response.json()["type"] == f"{DOCS}#persistence-unavailable"
    assert response.headers["Retry-After"] == "10"


def test_the_browser_may_send_versions_and_read_them(client: TestClient) -> None:
    preflight = client.options(
        URL,
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "If-Match, Content-Type",
        },
    )

    assert preflight.status_code == 200
    assert "PUT" in preflight.headers["access-control-allow-methods"]
    assert "DELETE" in preflight.headers["access-control-allow-methods"]
    assert "If-Match" in preflight.headers["access-control-allow-headers"]
    exposed = client.get("/health/live", headers={"Origin": "http://localhost:3000"})
    assert "ETag" in exposed.headers["access-control-expose-headers"]


# ── On PostgreSQL ──────────────────────────────────────────────────────────


@pytest.mark.integration
def test_the_api_stores_portfolios_in_postgresql(
    postgres: dict[str, str],
    toolkit: AsyncToolkit,
    core_settings: Settings,
    portfolio: Callable[..., Body],
) -> None:
    """End to end: the application builds its own repository from the settings."""
    owner = f"owner-{uuid4().hex[:8]}"
    settings = ApiSettings(database_url=postgres["app"], local_owner=owner)  # type: ignore[arg-type]

    with TestClient(create_app(settings, core_settings=core_settings, toolkit=toolkit)) as client:
        assert client.get("/health/ready").json()["database"] == "ok"
        saved = save(client, portfolio())
        url = f"{URL}/{saved['id']}"
        changed = client.put(url, json=portfolio(name="Renamed"), headers={"If-Match": '"1"'})
        listed = client.get(URL).json()["items"]
        conflict = client.post(URL, json=portfolio(name="Renamed"))
        deleted = client.delete(url, headers={"If-Match": '"2"'})

        assert (changed.status_code, changed.json()["version"]) == (200, 2)
        assert [item["portfolio"]["name"] for item in listed] == ["Renamed"]
        assert conflict.status_code == 409
        assert deleted.status_code == 204
        assert client.get(URL).json()["items"] == []


@pytest.mark.integration
def test_readiness_reports_a_database_that_needs_migrating(
    postgres: dict[str, str], toolkit: AsyncToolkit, core_settings: Settings
) -> None:
    """Also with the API listening beyond this machine, which it warns about."""
    unmigrated = make_url(postgres["owner"]).set(database="postgres")
    settings = ApiSettings(
        database_url=unmigrated.render_as_string(hide_password=False),  # type: ignore[arg-type]
        host="0.0.0.0",  # noqa: S104 - only the setting: the test client opens no socket
    )

    with TestClient(create_app(settings, core_settings=core_settings, toolkit=toolkit)) as client:
        ready = client.get("/health/ready")

    assert ready.status_code == 200  # the endpoints without state still work
    assert ready.json()["database"] == "migrations_pending"
