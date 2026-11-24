"""The worker: takes jobs from the queue and runs them (``investinglab-api worker``, ADR-0046).

It is the API's code in another process: the same settings, core, persistence and job kinds,
but instead of answering requests it waits on Procrastinate's queue (``LISTEN``/``NOTIFY``
on the same PostgreSQL) and runs each job with :func:`~investinglab_api.jobs.run_job`.

* **Concurrency.** ``INVESTINGLAB_API_WORKER_CONCURRENCY`` jobs at once per worker; start
  more workers for more.
* **A lost worker.** Workers send a heartbeat. Every minute a maintenance task puts back in
  the queue the jobs of a worker that stopped sending it; their next start counts as another
  attempt, and a job that keeps losing its worker ends as ``job-interrupted``.
* **Stopping.** Ctrl+C (or ``SIGTERM``) stops taking jobs and gives the running ones
  :data:`SHUTDOWN_SECONDS` to finish; those that do not are recorded as interrupted.
* **The data sources.** Every quarter of an hour, and once when it starts, it asks every
  source its canary and keeps the status of each (ADR-0047).
* **Traces.** With ``INVESTINGLAB_API_TRACING`` on, each attempt of a job is a ``process``
  span that continues the trace of the request that submitted it (ADR-0048).
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Final
from uuid import UUID

from procrastinate.exceptions import AlreadyEnqueued

from investinglab.config import configure_logging, get_logger
from investinglab.ports import JobStatus
from investinglab.toolkit import AsyncToolkit
from investinglab_api import telemetry
from investinglab_api.jobs import HANDLERS, run_job
from investinglab_api.jobs.sources import SOURCES_CRON, check_and_record
from investinglab_api.persistence import (
    Database,
    DatabaseStatus,
    SqlHeartbeatStore,
    SqlJobRepository,
    queue_app,
)
from investinglab_api.persistence.queue import QUEUE, RUN_JOB

if TYPE_CHECKING:
    from collections.abc import Mapping

    from procrastinate import App

    from investinglab.config import Settings
    from investinglab.ports import HeartbeatStore, JobRepository
    from investinglab_api.jobs import Handler
    from investinglab_api.settings import ApiSettings

__all__ = [
    "CHECK_SOURCES",
    "MAINTENANCE",
    "RETRY_STALLED",
    "SHUTDOWN_SECONDS",
    "WorkerNotReadyError",
    "register",
    "serve",
]

log = get_logger(__name__)

MAINTENANCE: Final = "maintenance"
"""Queue of the worker's own housekeeping."""

RETRY_STALLED: Final = "investinglab.retry_stalled"

CHECK_SOURCES: Final = "investinglab.check_sources"

SHUTDOWN_SECONDS: Final = 30.0
"""Time the running jobs get to finish when the worker is asked to stop."""


class WorkerNotReadyError(Exception):
    """The worker cannot start: no database, one that does not answer, or one behind its schema."""


def register(
    app: App,
    repository: JobRepository,
    *,
    toolkit: AsyncToolkit,
    settings: ApiSettings,
    handlers: Mapping[str, Handler] = HANDLERS,
    heartbeats: HeartbeatStore | None = None,
) -> App:
    """Teach Procrastinate's ``app`` the worker's tasks.

    Run a job, retry the stalled ones and, given where to keep them, check the sources.
    """

    @app.task(name=RUN_JOB, queue=QUEUE)
    async def run(job_id: str, owner_id: str, trace: dict[str, str] | None = None) -> None:
        # Each attempt continues the trace of the request that submitted the job (ADR-0048).
        attributes = {**telemetry.messaging(QUEUE, "process"), "investinglab.job.id": job_id}
        with telemetry.span(
            f"process {QUEUE}", kind="consumer", attributes=attributes, parent=trace
        ) as span:
            job = await run_job(
                repository,
                handlers,
                toolkit=toolkit,
                settings=settings,
                owner=owner_id,
                job_id=UUID(job_id),
            )
            if job is None:
                span.set(**{"investinglab.job.status": "skipped"})
                return
            span.set(
                **{
                    "investinglab.job.kind": job.kind,
                    "investinglab.job.status": job.status.value,
                    "investinglab.job.attempt": job.attempts,
                }
            )
            if job.status is JobStatus.FAILED and job.error is not None:
                span.fail(f"{job.error.code}: {job.error.title}")

    @app.periodic(cron="* * * * *")
    @app.task(name=RETRY_STALLED, queue=MAINTENANCE, queueing_lock=RETRY_STALLED)
    async def retry_stalled(timestamp: int) -> None:  # every periodic task gets its instant
        for stalled in await app.job_manager.get_stalled_jobs(task_name=RUN_JOB):
            log.warning("job_worker_lost", queue_job_id=stalled.id)
            await app.job_manager.retry_job(stalled)

    if heartbeats is not None:
        store = heartbeats

        @app.periodic(cron=SOURCES_CRON)
        @app.task(name=CHECK_SOURCES, queue=MAINTENANCE, queueing_lock=CHECK_SOURCES)
        async def check_sources(timestamp: int) -> None:  # every periodic task gets its instant
            await check_and_record(toolkit, store)

    return app


async def serve(settings: ApiSettings, core: Settings) -> None:
    """Run the worker until it is asked to stop.

    Raises:
        WorkerNotReadyError: There is no database, or it is not at this version's schema.
    """
    configure_logging(
        core.log_level, core.effective_log_format, processors=(telemetry.add_trace_context,)
    )
    if settings.database_url is None:
        msg = "Set INVESTINGLAB_API_DATABASE_URL: the jobs and their queue live in the database."
        raise WorkerNotReadyError(msg)
    traces = not telemetry.tracing_enabled()  # a process of its own: it stops what it starts
    telemetry.configure_tracing(settings.tracing, service="investinglab-worker")
    url = settings.database_url.get_secret_value()
    database = Database(url, pool_size=settings.worker_concurrency + 1)
    toolkit = AsyncToolkit.from_settings(core)
    try:
        status = await database.status()
        if status is DatabaseStatus.UNAVAILABLE:
            msg = (
                "The database does not answer at INVESTINGLAB_API_DATABASE_URL: is PostgreSQL "
                f"running (`uv run just db-up`) and is the URL right? ({database.last_error})"
            )
            raise WorkerNotReadyError(msg)
        if status is not DatabaseStatus.OK:
            msg = "The database is behind this version's schema: run `uv run just db-upgrade`."
            raise WorkerNotReadyError(msg)
        app = queue_app(url)
        register(
            app,
            SqlJobRepository(database, app),
            toolkit=toolkit,
            settings=settings,
            heartbeats=SqlHeartbeatStore(database),
        )
        async with app.open_async():
            # The sources' status from the start, not a quarter of an hour later.
            with contextlib.suppress(AlreadyEnqueued):
                await app.configure_task(CHECK_SOURCES).defer_async(timestamp=int(time.time()))
            log.info("worker_started", concurrency=settings.worker_concurrency)
            await app.run_worker_async(
                name="investinglab-worker",
                queues=[QUEUE, MAINTENANCE],
                concurrency=settings.worker_concurrency,
                delete_jobs="successful",
                shutdown_graceful_timeout=SHUTDOWN_SECONDS,
                install_signal_handlers=True,
            )
    finally:
        await toolkit.aclose()
        await database.dispose()
        log.info("worker_stopped")
        if traces:
            telemetry.shutdown_tracing()
