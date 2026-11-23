"""The worker on PostgreSQL: Procrastinate's real queue, the application's restricted role.

These are G0b's acceptance tests: a long job is submitted, read while it waits, run by a
worker and read again finished; a job and its place in the queue are written together or
not at all; a job whose worker vanished goes back to the queue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from investinglab.ports import JobStatus
from investinglab_api import worker
from investinglab_api.__main__ import main
from investinglab_api.app import create_app
from investinglab_api.persistence import Database, SqlJobRepository, queue_app
from investinglab_api.persistence import jobs as jobs_module
from investinglab_api.persistence.queue import QUEUE, RUN_JOB, conninfo
from investinglab_api.settings import ApiSettings, get_api_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from investinglab.config import Settings
    from investinglab.ports import JsonValue
    from investinglab.toolkit import AsyncToolkit

    type Body = dict[str, object]

pytestmark = pytest.mark.integration

PARAMETERS: dict[str, JsonValue] = {"n_paths": 500, "horizon": 20, "seed": 3}


def _queue_rows(postgres: dict[str, str], job_id: str) -> list[tuple[str, str]]:
    with psycopg.connect(conninfo(postgres["owner"])) as connection:
        return [
            (str(status), str(task))
            for status, task in connection.execute(
                "SELECT status, task_name FROM procrastinate_jobs WHERE args->>'job_id' = %s",
                (job_id,),
            )
        ]


async def _work(postgres: dict[str, str], toolkit: AsyncToolkit, database: Database) -> None:
    """Run a real worker until the queue is empty."""
    app = queue_app(postgres["app"])
    worker.register(app, SqlJobRepository(database, app), toolkit=toolkit, settings=ApiSettings())
    async with app.open_async():
        await app.run_worker_async(
            queues=[QUEUE], wait=False, install_signal_handlers=False, delete_jobs="successful"
        )


async def test_a_submitted_job_is_queued_in_the_same_transaction(
    postgres: dict[str, str], database: Database
) -> None:
    jobs = SqlJobRepository(database, queue_app(postgres["app"]))
    owner = f"owner-{uuid4().hex[:8]}"

    job = await jobs.submit(owner, "simulation", PARAMETERS)

    assert _queue_rows(postgres, str(job.id)) == [("todo", RUN_JOB)]


async def test_a_job_that_cannot_be_recorded_is_not_queued(
    postgres: dict[str, str], database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = SqlJobRepository(database, queue_app(postgres["app"]))
    owner = f"owner-{uuid4().hex[:8]}"

    async def broken(*_: object, **__: object) -> None:
        msg = "the audit log refused the entry"
        raise RuntimeError(msg)

    monkeypatch.setattr(jobs_module, "append_entry", broken)
    with pytest.raises(RuntimeError, match="audit log"):
        await jobs.submit(owner, "simulation", PARAMETERS)

    assert (await jobs.list(owner)).items == ()
    with psycopg.connect(conninfo(postgres["owner"])) as connection:
        queued = connection.execute(
            "SELECT count(*) FROM procrastinate_jobs WHERE args->>'owner_id' = %s", (owner,)
        ).fetchone()
    assert queued == (0,)  # rolled back with the job


async def test_the_api_queues_a_job_a_worker_runs_and_the_api_reads_finished(
    postgres: dict[str, str],
    toolkit: AsyncToolkit,
    core_settings: Settings,
    database: Database,
    portfolio: Callable[..., Body],
) -> None:
    owner = f"owner-{uuid4().hex[:8]}"
    settings = ApiSettings(database_url=postgres["app"], local_owner=owner)  # type: ignore[arg-type]
    body = {"portfolio": portfolio(), **PARAMETERS}

    with TestClient(create_app(settings, core_settings=core_settings, toolkit=toolkit)) as client:
        submitted = client.post("/api/v1/jobs/simulations", json=body)
        location = submitted.headers["Location"]
        waiting = client.get(location)
        assert client.portal is not None
        client.portal.call(_work, postgres, toolkit, database)
        finished = client.get(location)
        direct = client.post("/api/v1/simulations", json=body).json()

    assert submitted.status_code == 202
    assert (waiting.json()["status"], waiting.headers["Retry-After"]) == ("queued", "1")
    job = finished.json()
    assert (job["status"], job["attempts"], job["progress"]) == ("succeeded", 1, 1.0)
    assert job["result"] == direct
    assert _queue_rows(postgres, job["id"]) == []  # done: the queue forgets it


async def test_a_job_whose_worker_vanished_goes_back_to_the_queue(
    postgres: dict[str, str], toolkit: AsyncToolkit, database: Database
) -> None:
    app = queue_app(postgres["app"])
    jobs = SqlJobRepository(database, app)
    worker.register(app, jobs, toolkit=toolkit, settings=ApiSettings())
    owner = f"owner-{uuid4().hex[:8]}"
    job = await jobs.submit(owner, "simulation", PARAMETERS)
    await jobs.start(owner, job.id)
    with psycopg.connect(conninfo(postgres["owner"])) as connection:  # a worker that died
        (dead,) = connection.execute(
            "INSERT INTO procrastinate_workers (last_heartbeat) "
            "VALUES (now() - interval '1 hour') RETURNING id"
        ).fetchone() or (None,)
        connection.execute(
            "UPDATE procrastinate_jobs SET status = 'doing', worker_id = %s "
            "WHERE args->>'job_id' = %s",
            (dead, str(job.id)),
        )

    async with app.open_async():
        await app.tasks[worker.RETRY_STALLED].func(timestamp=0)

    assert _queue_rows(postgres, str(job.id)) == [("todo", RUN_JOB)]
    assert (await jobs.get(owner, job.id)).status is JobStatus.RUNNING  # it will start again


def test_the_worker_needs_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVESTINGLAB_API_DATABASE_URL", raising=False)
    get_api_settings.cache_clear()
    try:
        assert main(["worker"]) == 2
    finally:
        get_api_settings.cache_clear()


def test_the_worker_command_reports_how_it_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes: list[BaseException | None] = [None, KeyboardInterrupt()]

    async def serve(*_: object) -> None:
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(worker, "serve", serve)

    assert main(["worker"]) == 0  # stopped on its own
    assert main(["worker"]) == 130  # Ctrl+C


async def test_the_worker_refuses_a_database_behind_its_schema(
    postgres: dict[str, str], core_settings: Settings
) -> None:
    unmigrated = postgres["owner"].rsplit("/", 1)[0] + "/postgres"
    settings = ApiSettings(database_url=unmigrated)  # type: ignore[arg-type]

    with pytest.raises(worker.WorkerNotReadyError, match="db-upgrade"):
        await worker.serve(settings, core_settings)


async def test_the_worker_serves_both_queues_and_closes_what_it_opened(
    postgres: dict[str, str], core_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: dict[str, object] = {}

    async def run_worker_async(self: object, **options: object) -> None:
        started.update(options)
        started["tasks"] = sorted(self.tasks)  # type: ignore[attr-defined]

    monkeypatch.setattr("procrastinate.App.run_worker_async", run_worker_async)
    settings = ApiSettings(database_url=postgres["app"], worker_concurrency=3)  # type: ignore[arg-type]

    await worker.serve(settings, core_settings)

    assert started["queues"] == [QUEUE, worker.MAINTENANCE]
    assert (started["concurrency"], started["delete_jobs"]) == (3, "successful")
    assert started["shutdown_graceful_timeout"] == worker.SHUTDOWN_SECONDS
    assert {RUN_JOB, worker.RETRY_STALLED, worker.CHECK_SOURCES} <= set(started["tasks"])  # type: ignore[call-overload]
    with psycopg.connect(conninfo(postgres["owner"])) as connection:  # checked from the start
        waiting = connection.execute(
            "SELECT queue_name FROM procrastinate_jobs WHERE task_name = %s AND status = 'todo'",
            (worker.CHECK_SOURCES,),
        ).fetchall()
    assert waiting == [(worker.MAINTENANCE,)]
