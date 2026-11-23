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
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from uuid import UUID

from investinglab.config import configure_logging, get_logger
from investinglab.toolkit import AsyncToolkit
from investinglab_api.jobs import HANDLERS, run_job
from investinglab_api.persistence import Database, DatabaseStatus, SqlJobRepository, queue_app
from investinglab_api.persistence.queue import QUEUE, RUN_JOB

if TYPE_CHECKING:
    from collections.abc import Mapping

    from procrastinate import App

    from investinglab.config import Settings
    from investinglab.ports import JobRepository
    from investinglab_api.jobs import Handler
    from investinglab_api.settings import ApiSettings

__all__ = [
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

SHUTDOWN_SECONDS: Final = 30.0
"""Time the running jobs get to finish when the worker is asked to stop."""


class WorkerNotReadyError(Exception):
    """The worker cannot start: no database, or a database not migrated to this version."""


def register(
    app: App,
    repository: JobRepository,
    *,
    toolkit: AsyncToolkit,
    settings: ApiSettings,
    handlers: Mapping[str, Handler] = HANDLERS,
) -> App:
    """Teach Procrastinate's ``app`` the worker's tasks: run a job, retry stalled ones."""

    @app.task(name=RUN_JOB, queue=QUEUE)
    async def run(job_id: str, owner_id: str) -> None:
        await run_job(
            repository,
            handlers,
            toolkit=toolkit,
            settings=settings,
            owner=owner_id,
            job_id=UUID(job_id),
        )

    @app.periodic(cron="* * * * *")
    @app.task(name=RETRY_STALLED, queue=MAINTENANCE, queueing_lock=RETRY_STALLED)
    async def retry_stalled(timestamp: int) -> None:  # every periodic task gets its instant
        for stalled in await app.job_manager.get_stalled_jobs(task_name=RUN_JOB):
            log.warning("job_worker_lost", queue_job_id=stalled.id)
            await app.job_manager.retry_job(stalled)

    return app


async def serve(settings: ApiSettings, core: Settings) -> None:
    """Run the worker until it is asked to stop.

    Raises:
        WorkerNotReadyError: There is no database, or it is not at this version's schema.
    """
    configure_logging(core.log_level, core.effective_log_format)
    if settings.database_url is None:
        msg = "Set INVESTINGLAB_API_DATABASE_URL: the jobs and their queue live in the database."
        raise WorkerNotReadyError(msg)
    url = settings.database_url.get_secret_value()
    database = Database(url, pool_size=settings.worker_concurrency + 1)
    toolkit = AsyncToolkit.from_settings(core)
    try:
        status = await database.status()
        if status is not DatabaseStatus.OK:
            msg = f"The database is not ready ({status}): run `uv run just db-upgrade`."
            raise WorkerNotReadyError(msg)
        app = queue_app(url)
        register(app, SqlJobRepository(database, app), toolkit=toolkit, settings=settings)
        log.info("worker_started", concurrency=settings.worker_concurrency)
        async with app.open_async():
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
