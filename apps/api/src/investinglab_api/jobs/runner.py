"""What a worker does with a job: start it, run its kind, report progress, record the outcome.

Nothing here knows the queue: the worker (:mod:`investinglab_api.worker`) calls
:func:`run_job` for every job Procrastinate hands it, and the tests call it directly on the
in-memory repository. Whatever happens, the job ends recorded (succeeded, failed or
cancelled): :func:`run_job` never raises for a failure of the job itself.

**Progress and cancellation.** A handler reports through :class:`Progress`, from the event
loop or from a thread (the Monte Carlo runs in one). Every :data:`FLUSH_SECONDS` the runner
writes the latest report and learns whether the owner asked to cancel; if so, the next
report raises :class:`JobCancelledError` in the handler, and a handler waiting on the network
is cancelled at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from investinglab.config import get_logger
from investinglab.domain.errors import DomainError
from investinglab.ports import JobError
from investinglab.services import DataUnavailableError
from investinglab_api.problems import ProblemType, data_problem

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping
    from typing import Any
    from uuid import UUID

    from investinglab.ports import Job, JobRepository, JsonValue
    from investinglab.toolkit import AsyncToolkit
    from investinglab_api.settings import ApiSettings

__all__ = [
    "FLUSH_SECONDS",
    "MAX_ATTEMPTS",
    "Handler",
    "JobCancelledError",
    "JobContext",
    "Progress",
    "job_error",
    "run_job",
]

log = get_logger(__name__)

FLUSH_SECONDS: Final = 1.0
"""How often a running job's progress is written, and its cancellation checked."""

MAX_ATTEMPTS: Final = 3
"""Times a job may start: more means its worker keeps dying while running it."""


class JobCancelledError(Exception):
    """The owner asked to stop the job; raised by :meth:`Progress.update` in the handler."""


class Progress:
    """How far a job is, written by its handler from any thread and read by the runner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fraction: float | None = None
        self._stage: str | None = None
        self.cancelled = threading.Event()

    def update(self, fraction: float | None = None, stage: str | None = None) -> None:
        """Report the fraction done (0 to 1) and the stage; the stage is kept if not given.

        Raises:
            JobCancelledError: The owner asked to stop the job.
        """
        if self.cancelled.is_set():
            raise JobCancelledError
        with self._lock:
            if fraction is not None:
                self._fraction = min(1.0, max(0.0, fraction))
            if stage is not None:
                self._stage = stage

    def snapshot(self) -> tuple[float | None, str | None]:
        """The latest fraction and stage."""
        with self._lock:
            return self._fraction, self._stage


@dataclass(frozen=True, slots=True)
class JobContext:
    """What a handler gets to run one job.

    Attributes:
        parameters: The job's parameters, as submitted.
        toolkit: The core, to read data and compute.
        settings: The API settings (limits).
        progress: Where to report how far it is.
    """

    parameters: Mapping[str, JsonValue]
    toolkit: AsyncToolkit
    settings: ApiSettings
    progress: Progress


type Handler = Callable[[JobContext], Coroutine[Any, Any, JsonValue]]
"""Runs the jobs of one kind and returns their result as plain JSON."""


def job_error(error: BaseException) -> JobError:
    """The error a job records for an exception, in the vocabulary of the API's problems."""
    if isinstance(error, DataUnavailableError):
        _, kind, title = data_problem(error)
        return JobError(kind.value, title, str(error))
    if isinstance(error, DomainError | ValidationError):
        return JobError(ProblemType.INVALID_REQUEST.value, "Invalid request", str(error))
    if isinstance(error, TimeoutError):
        detail = f"The job took too long: {str(error) or 'no detail'}"
        return JobError(ProblemType.TIMEOUT.value, "Timed out", detail)
    return JobError(
        ProblemType.INTERNAL_ERROR.value,
        "Internal error",
        "The job failed unexpectedly; the worker's log has the details.",
    )


def _interrupted(reason: str) -> JobError:
    return JobError(ProblemType.JOB_INTERRUPTED.value, "Interrupted", reason)


async def _flush(
    repository: JobRepository,
    owner: str,
    job_id: UUID,
    *,
    progress: Progress,
    handler: asyncio.Task[JsonValue],
    every: float,
) -> None:
    """Write the progress every ``every`` seconds; stop the handler if the owner cancels."""
    while True:
        await asyncio.sleep(every)
        fraction, stage = progress.snapshot()
        if await repository.report(owner, job_id, progress=fraction, stage=stage):
            progress.cancelled.set()
            # A handler waiting on I/O stops now; one in a thread, at its next report.
            handler.cancel()
            return


async def _record(
    repository: JobRepository,
    owner: str,
    job_id: UUID,
    handler: asyncio.Task[JsonValue],
    progress: Progress,
) -> Job:
    """Wait for the handler and record what came of it."""
    try:
        result = await handler
    except JobCancelledError:
        return await repository.stopped(owner, job_id)
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if progress.cancelled.is_set() and (current is None or not current.cancelling()):
            return await repository.stopped(owner, job_id)  # cancelled by its owner
        raise  # the worker itself is stopping
    except Exception as error:  # any failure of the job is recorded, never lost
        return await _failed(repository, owner, job_id, error)
    try:
        return await repository.succeed(owner, job_id, result)
    except ValueError as error:  # a result that is not plain JSON (NaN...) is a bug of its kind
        return await _failed(repository, owner, job_id, error)


async def _failed(repository: JobRepository, owner: str, job_id: UUID, error: Exception) -> Job:
    recorded = job_error(error)
    if recorded.code == ProblemType.INTERNAL_ERROR.value:
        log.error("job_crashed", job_id=str(job_id), error=type(error).__name__, exc_info=error)
    return await repository.fail(owner, job_id, recorded)


async def run_job(
    repository: JobRepository,
    handlers: Mapping[str, Handler],
    *,
    toolkit: AsyncToolkit,
    settings: ApiSettings,
    owner: str,
    job_id: UUID,
    flush_seconds: float = FLUSH_SECONDS,
) -> Job | None:
    """Run one job to its end and record the outcome; ``None`` if there was nothing to run.

    Raises:
        asyncio.CancelledError: The worker is stopping; the job is recorded as interrupted.
    """
    job = await repository.start(owner, job_id)
    if job is None:
        log.info("job_skipped", job_id=str(job_id))  # finished, cancelled or removed meanwhile
        return None
    log.info("job_started", job_id=str(job_id), kind=job.kind, attempt=job.attempts)
    if job.cancel_requested:
        return await repository.stopped(owner, job_id)
    if job.attempts > MAX_ATTEMPTS:
        reason = f"The worker stopped {job.attempts - 1} times while running it; submit it again."
        return await repository.fail(owner, job_id, _interrupted(reason))
    handler = handlers.get(job.kind)
    if handler is None:
        error = JobError(
            ProblemType.INVALID_REQUEST.value,
            "Unknown kind of job",
            f"No worker runs jobs of kind {job.kind!r}.",
        )
        return await repository.fail(owner, job_id, error)

    progress = Progress()
    context = JobContext(job.parameters, toolkit, settings, progress)
    running: asyncio.Task[JsonValue] = asyncio.create_task(handler(context))
    flusher = asyncio.create_task(
        _flush(repository, owner, job_id, progress=progress, handler=running, every=flush_seconds)
    )
    try:
        outcome = await _record(repository, owner, job_id, running, progress)
    except asyncio.CancelledError:
        progress.cancelled.set()  # a handler in a thread stops at its next report
        running.cancel()
        reason = "The worker stopped while running it; submit it again."
        with contextlib.suppress(Exception):
            await asyncio.shield(repository.fail(owner, job_id, _interrupted(reason)))
        raise
    finally:
        flusher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await flusher
    log.info("job_finished", job_id=str(job_id), kind=job.kind, status=outcome.status.value)
    return outcome
