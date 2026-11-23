"""Background jobs over HTTP, on SYNTHETIC series: submit, read, run, cancel and delete.

A test plays the worker by running what the in-memory repository queued, on the
application's own event loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from investinglab_api.app import create_app
from investinglab_api.jobs import HANDLERS, run_job
from investinglab_api.settings import ApiSettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from investinglab.config import Settings
    from investinglab.toolkit import AsyncToolkit
    from support.repositories import InMemoryJobRepository

    type Body = dict[str, object]

URL = "/api/v1/jobs"
SIMULATIONS = f"{URL}/simulations"


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


def simulation(portfolio: Callable[..., Body], **changes: object) -> Body:
    body: Body = {"portfolio": portfolio(), "n_paths": 1_000, "horizon": 60, "seed": 7}
    body.update(changes)
    return body


def test_a_simulation_is_accepted_and_queued(
    client: TestClient, jobs: InMemoryJobRepository, portfolio: Callable[..., Body]
) -> None:
    response = client.post(SIMULATIONS, json=simulation(portfolio))

    assert response.status_code == 202
    job = response.json()
    assert response.headers["Location"].endswith(f"{URL}/{job['id']}")
    assert response.headers["Retry-After"] == "1"
    assert (job["kind"], job["status"], job["result"], job["error"]) == (
        "simulation",
        "queued",
        None,
        None,
    )
    assert job["parameters"]["n_paths"] == 1_000
    assert [job_id for _, job_id in jobs.queue] == [UUID(job["id"])]


def test_the_worker_runs_it_to_the_same_result_as_a_request(
    client: TestClient,
    jobs: InMemoryJobRepository,
    toolkit: AsyncToolkit,
    portfolio: Callable[..., Body],
) -> None:
    location = client.post(SIMULATIONS, json=simulation(portfolio)).headers["Location"]
    work(client, jobs, toolkit)

    read = client.get(location)
    direct = client.post("/api/v1/simulations", json=simulation(portfolio)).json()

    assert read.status_code == 200
    assert "Retry-After" not in read.headers  # finished: nothing more to wait for
    job = read.json()
    assert (job["status"], job["progress"], job["attempts"]) == ("succeeded", 1.0, 1)
    assert job["result"] == direct  # same seed, same simulation
    assert job["started_at"] <= job["finished_at"]


def test_a_simulation_larger_than_a_request_allows_runs_as_a_job(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    large = simulation(portfolio, n_paths=50_000, horizon=20)

    assert client.post("/api/v1/simulations", json=large).status_code == 422
    assert client.post(SIMULATIONS, json=large).status_code == 202


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"n_paths": 250_000}, "At most 200000 paths"),
        ({"n_paths": 200_000, "horizon": 252}, "memory bound"),
        ({"horizon": 3_000}, "periods of horizon"),
    ],
    ids=["paths", "memory", "horizon"],
)
def test_limits_are_checked_when_submitting_not_in_the_worker(
    client: TestClient,
    jobs: InMemoryJobRepository,
    portfolio: Callable[..., Body],
    changes: Body,
    message: str,
) -> None:
    response = client.post(SIMULATIONS, json=simulation(portfolio, **changes))

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert jobs.queue == []


def test_missing_data_ends_the_job_failed_with_its_problem(
    client: TestClient,
    jobs: InMemoryJobRepository,
    toolkit: AsyncToolkit,
    portfolio: Callable[..., Body],
) -> None:
    body = simulation(portfolio)
    body["portfolio"] = portfolio(holdings=[{"symbol": "NOPE.MC", "weight": 1.0}])
    location = client.post(SIMULATIONS, json=body).headers["Location"]
    work(client, jobs, toolkit)

    job = client.get(location).json()
    assert (job["status"], job["result"]) == ("failed", None)
    assert job["error"]["type"].endswith("#data-not-found")
    assert "NOPE.MC" in job["error"]["detail"]


def test_a_queued_job_is_cancelled_at_once_and_then_skipped(
    client: TestClient,
    jobs: InMemoryJobRepository,
    toolkit: AsyncToolkit,
    portfolio: Callable[..., Body],
) -> None:
    job_id = client.post(SIMULATIONS, json=simulation(portfolio)).json()["id"]

    cancelled = client.post(f"{URL}/{job_id}/cancel")
    work(client, jobs, toolkit)  # the worker takes it and finds it cancelled

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    job = client.get(f"{URL}/{job_id}").json()
    assert (job["status"], job["attempts"], job["result"]) == ("cancelled", 0, None)


def test_a_finished_job_cannot_be_cancelled_and_an_unfinished_one_cannot_be_deleted(
    client: TestClient,
    jobs: InMemoryJobRepository,
    toolkit: AsyncToolkit,
    portfolio: Callable[..., Body],
) -> None:
    job_id = client.post(SIMULATIONS, json=simulation(portfolio)).json()["id"]

    early = client.delete(f"{URL}/{job_id}")
    work(client, jobs, toolkit)
    late = client.post(f"{URL}/{job_id}/cancel")
    deleted = client.delete(f"{URL}/{job_id}")

    assert early.status_code == 409
    assert early.json()["type"].endswith("#job-state")
    assert early.json()["job_status"] == "queued"
    assert (late.status_code, late.json()["job_status"]) == (409, "succeeded")
    assert deleted.status_code == 204
    assert client.get(f"{URL}/{job_id}").status_code == 404


def test_jobs_are_listed_newest_first_page_by_page(
    client: TestClient, portfolio: Callable[..., Body]
) -> None:
    ids = [client.post(SIMULATIONS, json=simulation(portfolio)).json()["id"] for _ in range(3)]

    first = client.get(URL, params={"limit": 2}).json()
    second = client.get(URL, params={"limit": 2, "cursor": first["next_cursor"]}).json()

    assert [item["id"] for item in first["items"] + second["items"]] == ids[::-1]
    assert second["next_cursor"] is None
    assert "parameters" not in first["items"][0]  # listings are light


def test_another_owners_job_does_not_exist(
    toolkit: AsyncToolkit,
    core_settings: Settings,
    jobs: InMemoryJobRepository,
    portfolio: Callable[..., Body],
) -> None:
    def app(owner: str) -> TestClient:
        settings = ApiSettings(local_owner=owner)
        return TestClient(
            create_app(settings, core_settings=core_settings, toolkit=toolkit, jobs_repository=jobs)
        )

    with app("alice") as alice, app("bob") as bob:
        job_id = alice.post(SIMULATIONS, json=simulation(portfolio)).json()["id"]

        assert bob.get(f"{URL}/{job_id}").status_code == 404
        assert bob.post(f"{URL}/{job_id}/cancel").status_code == 404
        assert bob.get(URL).json()["items"] == []
        assert alice.get(f"{URL}/{job_id}").status_code == 200


def test_without_a_database_jobs_are_unavailable(
    toolkit: AsyncToolkit, core_settings: Settings, portfolio: Callable[..., Body]
) -> None:
    with TestClient(create_app(ApiSettings(), core_settings=core_settings, toolkit=toolkit)) as c:
        response = c.post(SIMULATIONS, json=simulation(portfolio))

    assert response.status_code == 503
    assert response.json()["type"].endswith("#persistence-not-configured")


def test_an_unknown_job_is_not_found(client: TestClient) -> None:
    response = client.get(f"{URL}/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"].endswith("#not-found")
