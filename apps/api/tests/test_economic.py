"""Economic series endpoint over a SYNTHETIC €STR (never market data)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

ESTR = "ECBESTRVOLWGTTRMDMNRT"


def test_a_series_comes_with_its_publication_dates(client: TestClient) -> None:
    response = client.get(
        "/api/v1/economic/series",
        params={"series_id": ESTR, "start": "2024-01-01", "end": "2024-06-30"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["series_id"] == ESTR
    assert body["frequency"] == "1mo"
    assert body["has_revisions"] is False
    assert body["source"]["provider"] == "synthetic"
    first = body["observations"][0]
    assert first == {"time": "2024-01-01", "published_at": "2024-02-01", "value": 3.0}
    assert all(o["published_at"] >= o["time"] for o in body["observations"])


def test_an_unknown_series_is_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/economic/series", params={"series_id": "NOPE"})

    assert response.status_code == 404
    assert response.json()["type"].endswith("#data-not-found")


@pytest.mark.parametrize(
    "params",
    [
        {"series_id": "bad id"},
        {"series_id": ESTR, "mode": "sometimes"},
        {"series_id": ESTR, "start": "2024-06-01", "end": "2024-01-01"},
    ],
    ids=["id", "mode", "reversed"],
)
def test_invalid_requests_are_refused(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/api/v1/economic/series", params=params).status_code == 422
