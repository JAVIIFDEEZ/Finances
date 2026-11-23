"""Background jobs: work that does not fit in a request, run by a worker (ADR-0046).

A job is a record of its owner: what to run (its ``kind`` and ``parameters``), how far it is
(``status``, ``progress``, ``stage``) and what came of it (``result`` or ``error``). The
store that keeps them is also how the workers get them: :meth:`JobRepository.submit` hands
the job over to the workers in the same transaction that records it, so there is never a
job nobody will run, nor a run without its job.

A job moves only forwards::

    queued ──> running ──> succeeded | failed | cancelled
       └──────────────────────────────────────> cancelled

Every transition is conditional on the state it leaves, so a worker that runs a job twice
(after a crash, say) cannot overwrite a job that has already finished.

The rules of every repository hold here too: everything has an owner, and another owner's
job does not exist for the caller.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from investinglab.domain.errors import DomainError
from investinglab.ports.audit_log import canonical_json
from investinglab.ports.repositories import RepositoryError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from investinglab.ports.audit_log import JsonValue
    from investinglab.ports.repositories import Page

__all__ = [
    "JOB_STREAM",
    "MAX_KIND_LENGTH",
    "Job",
    "JobError",
    "JobRepository",
    "JobStateError",
    "JobStatus",
    "check_submission",
    "job_outcome",
]

MAX_KIND_LENGTH: Final = 40

JOB_STREAM: Final = "jobs"
"""Stream of the audit log where every implementation records what happens to jobs."""


class JobStatus(StrEnum):
    """Where a job is in its life."""

    QUEUED = "queued"
    """Recorded and handed to the workers; none has started it yet."""
    RUNNING = "running"
    """A worker is running it."""
    SUCCEEDED = "succeeded"
    """Finished with a result."""
    FAILED = "failed"
    """Finished with an error."""
    CANCELLED = "cancelled"
    """Stopped because its owner asked, before it finished."""

    @property
    def finished(self) -> bool:
        """Whether the job can no longer change."""
        return self in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobStateError(RepositoryError):
    """The job is not in a state that allows the change (cancel a finished job...).

    Attributes:
        status: The state the job is in.
    """

    def __init__(self, message: str, status: JobStatus) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job failed, in the words its owner reads.

    Attributes:
        code: Stable slug of the kind of failure (``invalid-request``, ``data-not-found``,
            ``interrupted``, ``internal-error``...), the same vocabulary the API uses.
        title: Short summary.
        detail: What happened, without internal details (tracebacks stay in the logs).
    """

    code: str
    title: str
    detail: str

    def __post_init__(self) -> None:
        if not self.code or not self.title:
            raise DomainError("A job error needs a code and a title")


@dataclass(frozen=True, slots=True)
class Job:
    """A background job of an owner.

    Attributes:
        id: Identifier, assigned when the job is submitted.
        owner_id: Owner of the job.
        kind: What it runs (``simulation``...), which says what its parameters and result are.
        status: Where it is in its life.
        parameters: What to run, as its kind defines it.
        created_at: Instant it was submitted.
        started_at: Instant a worker last started it (``None`` while queued).
        finished_at: Instant it finished (``None`` until then).
        progress: Fraction done, from 0 to 1, when the job knows it.
        stage: What the job is doing (a slug its kind defines: ``loading``, ``simulating``);
            ``None`` once it has finished.
        result: What it produced, once succeeded.
        error: Why it failed, once failed.
        cancel_requested: Its owner asked to stop it while it was running.
        attempts: Times a worker has started it (more than one after a worker was lost).
    """

    id: UUID
    owner_id: str
    kind: str
    status: JobStatus
    parameters: Mapping[str, JsonValue]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float | None = None
    stage: str | None = None
    result: JsonValue = None
    error: JobError | None = None
    cancel_requested: bool = False
    attempts: int = 0

    def __post_init__(self) -> None:
        problems: list[str] = []
        if not self.kind or len(self.kind) > MAX_KIND_LENGTH:
            problems.append(f"a job kind takes 1 to {MAX_KIND_LENGTH} characters")
        if self.progress is not None and not (
            math.isfinite(self.progress) and 0.0 <= self.progress <= 1.0
        ):
            problems.append(f"progress must be between 0 and 1, got {self.progress}")
        if (self.status is JobStatus.SUCCEEDED) != (self.result is not None):
            problems.append("a job has a result exactly when it succeeded")
        if (self.status is JobStatus.FAILED) != (self.error is not None):
            problems.append("a job has an error exactly when it failed")
        if self.status.finished != (self.finished_at is not None):
            problems.append("a job has a finishing instant exactly when it finished")
        if self.attempts < 0:
            problems.append("attempts cannot be negative")
        if problems:
            raise DomainError("Invalid job: " + "; ".join(problems))


def check_submission(kind: str, parameters: Mapping[str, JsonValue]) -> None:
    """The rules :meth:`JobRepository.submit` applies before recording a job.

    Raises:
        DomainError: The kind is empty or too long, or the parameters are not plain JSON.
    """
    if not kind or len(kind) > MAX_KIND_LENGTH:
        raise DomainError(f"A job kind takes 1 to {MAX_KIND_LENGTH} characters")
    try:
        canonical_json(parameters)
    except ValueError as error:
        raise DomainError(f"Job parameters must be plain JSON: {error}") from error


def job_outcome(job: Job) -> dict[str, JsonValue]:
    """What the audit log keeps of a finished job: its outcome and a digest of its result.

    The digest (SHA-256 of the canonical JSON of ``{"result": ...}``) proves later that a
    stored result is the one the job produced, without copying it into the log.
    """
    payload: dict[str, JsonValue] = {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status.value,
    }
    if job.result is not None:
        text = canonical_json({"result": job.result})
        payload["result_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    if job.error is not None:
        payload["error"] = job.error.code
    return payload


@runtime_checkable
class JobRepository(Protocol):
    """The jobs each owner has submitted, and the queue the workers take them from.

    The first group of methods serves the owner (through the API); the second, the worker
    that runs a job. Both take the owner first.
    """

    async def submit(self, owner: str, kind: str, parameters: Mapping[str, JsonValue]) -> Job:
        """Record a new job and hand it to the workers, in one transaction.

        Raises:
            DomainError: The kind is empty or too long, or the parameters are not JSON.
        """
        ...

    async def get(self, owner: str, job_id: UUID) -> Job:
        """One job of the owner.

        Raises:
            RecordNotFoundError: The owner has no such job.
        """
        ...

    async def list(self, owner: str, *, limit: int = 50, cursor: str | None = None) -> Page[Job]:
        """The owner's jobs, most recently submitted first.

        Raises:
            DomainError: ``cursor`` does not come from a previous page.
        """
        ...

    async def cancel(self, owner: str, job_id: UUID) -> Job:
        """Stop a job: at once if it is queued, at its next report if it is running.

        Raises:
            RecordNotFoundError: The owner has no such job.
            JobStateError: It has already finished.
        """
        ...

    async def remove(self, owner: str, job_id: UUID) -> None:
        """Delete a finished job.

        Raises:
            RecordNotFoundError: The owner has no such job.
            JobStateError: It has not finished: cancel it first.
        """
        ...

    # ── What a worker does ───────────────────────────────────────────

    async def start(self, owner: str, job_id: UUID) -> Job | None:
        """Mark the job running and count the attempt; ``None`` if there is nothing to run.

        A queued job starts; a running one starts again (its worker was lost). A finished
        or cancelled job, or one that no longer exists, gives ``None``: the worker skips it.
        """
        ...

    async def report(
        self, owner: str, job_id: UUID, *, progress: float | None, stage: str | None
    ) -> bool:
        """Record how far a running job is; ``True`` if its owner asked to cancel it."""
        ...

    async def succeed(self, owner: str, job_id: UUID, result: JsonValue) -> Job:
        """Finish a running job with its result.

        Raises:
            JobStateError: The job is not running.
        """
        ...

    async def fail(self, owner: str, job_id: UUID, error: JobError) -> Job:
        """Finish a running job with an error.

        Raises:
            JobStateError: The job is not running.
        """
        ...

    async def stopped(self, owner: str, job_id: UUID) -> Job:
        """Finish a running job its owner asked to cancel.

        Raises:
            JobStateError: The job is not running.
        """
        ...
