"""Background jobs on PostgreSQL, queued with Procrastinate in the same transaction (ADR-0046)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import delete, select, tuple_, update

from investinglab.ports import (
    JOB_STREAM,
    Job,
    JobError,
    JobStateError,
    JobStatus,
    Page,
    RecordNotFoundError,
    canonical_json,
    check_submission,
    decode_cursor,
    encode_cursor,
    job_outcome,
)
from investinglab_api import telemetry
from investinglab_api.persistence.audit import append_entry
from investinglab_api.persistence.models import JobRow
from investinglab_api.persistence.queue import QUEUE, RUN_JOB

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from procrastinate import App
    from procrastinate.types import JSONValue
    from sqlalchemy.ext.asyncio import AsyncSession

    from investinglab.ports import JsonValue
    from investinglab_api.persistence.database import Database

__all__ = ["SqlJobRepository", "job_of"]

RESTARTABLE: Final = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


def _now() -> datetime:
    return datetime.now(UTC)


def _error_of(document: dict[str, Any] | None) -> JobError | None:
    if document is None:
        return None
    return JobError(document["code"], document["title"], document["detail"])


def job_of(row: JobRow) -> Job:
    """The job a row holds."""
    return Job(
        id=row.id,
        owner_id=row.owner_id,
        kind=row.kind,
        status=JobStatus(row.status),
        parameters=row.parameters,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        progress=row.progress,
        stage=row.stage,
        result=row.result,
        error=_error_of(row.error),
        cancel_requested=row.cancel_requested,
        attempts=row.attempts,
    )


class SqlJobRepository:
    """:class:`investinglab.ports.JobRepository` on the ``jobs`` table and Procrastinate's queue.

    Like every repository, each statement filters by owner and each transaction tells the
    database who the owner is (row-level security). Every change of state is an ``UPDATE``
    conditional on the state it leaves, so two workers, or a worker and a cancellation,
    cannot both win.

    Args:
        database: Where the jobs are.
        queue: Procrastinate's application (:func:`~investinglab_api.persistence.queue.queue_app`);
            only its task configuration is used, never its connection pool.
        clock: Current time (injectable for tests).
    """

    def __init__(
        self, database: Database, queue: App, clock: Callable[[], datetime] = _now
    ) -> None:
        self._database = database
        self._queue = queue
        self._clock = clock

    async def _audit(self, session: AsyncSession, kind: str, job: Job) -> None:
        payload = job_outcome(job) if job.status.finished else {"id": str(job.id), "kind": job.kind}
        await append_entry(
            session, JOB_STREAM, kind, payload, owner_id=job.owner_id, clock=self._clock
        )

    async def _enqueue(self, session: AsyncSession, owner: str, job_id: UUID, kind: str) -> int:
        """Put the job in Procrastinate's queue on this transaction's own connection.

        The entry carries the trace context of the submission, so that the worker continues
        the same trace (ADR-0048); without tracing it is empty.
        """
        connection = await session.connection()
        raw = await connection.get_raw_connection()
        deferrer = self._queue.configure_task(
            RUN_JOB, queue=QUEUE, connection=raw.driver_connection
        )
        attributes = {
            **telemetry.messaging(QUEUE, "send"),
            "investinglab.job.id": str(job_id),
            "investinglab.job.kind": kind,
        }
        with telemetry.span(f"send {QUEUE}", kind="producer", attributes=attributes) as span:
            trace: dict[str, JSONValue] = dict(telemetry.current_carrier().items())
            queued = await deferrer.defer_async(job_id=str(job_id), owner_id=owner, trace=trace)
            span.set(**{"messaging.message.id": str(queued)})
        return queued

    async def _row(self, session: AsyncSession, owner: str, job_id: UUID) -> JobRow:
        row = await session.scalar(
            select(JobRow).where(JobRow.owner_id == owner, JobRow.id == job_id).with_for_update()
        )
        if row is None:
            raise RecordNotFoundError(f"No job {job_id}")
        return row

    async def submit(self, owner: str, kind: str, parameters: Mapping[str, JsonValue]) -> Job:
        """Record the job and queue it; neither happens without the other."""
        check_submission(kind, parameters)
        now = self._clock()
        row = JobRow(
            id=uuid4(),
            owner_id=owner,
            kind=kind,
            status=JobStatus.QUEUED.value,
            parameters=dict(parameters),
            cancel_requested=False,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        async with self._database.transaction(owner) as session:
            session.add(row)
            await session.flush()
            row.queue_job_id = await self._enqueue(session, owner, row.id, kind)
            job = job_of(row)
            await self._audit(session, "job.submitted", job)
        return job

    async def get(self, owner: str, job_id: UUID) -> Job:
        """One job of the owner."""
        async with self._database.transaction(owner) as session:
            row = await session.scalar(
                select(JobRow).where(JobRow.owner_id == owner, JobRow.id == job_id)
            )
            if row is None:
                raise RecordNotFoundError(f"No job {job_id}")
            return job_of(row)

    async def list(self, owner: str, *, limit: int = 50, cursor: str | None = None) -> Page[Job]:
        """The owner's jobs, most recently submitted first."""
        query = select(JobRow).where(JobRow.owner_id == owner)
        if cursor is not None:
            created, job_id = decode_cursor(cursor)
            query = query.where(tuple_(JobRow.created_at, JobRow.id) < (created, job_id))
        query = query.order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(limit + 1)
        async with self._database.transaction(owner) as session:
            rows = list((await session.scalars(query)).all())
        page = [job_of(row) for row in rows[:limit]]
        last = page[-1] if page else None
        more = len(rows) > limit
        return Page(tuple(page), encode_cursor(last.created_at, last.id) if more and last else None)

    async def cancel(self, owner: str, job_id: UUID) -> Job:
        """Cancel a queued job at once; ask a running one to stop."""
        async with self._database.transaction(owner) as session:
            row = await self._row(session, owner, job_id)
            status = JobStatus(row.status)
            if status.finished:
                raise JobStateError(f"Job {job_id} has already finished ({status})", status)
            now = self._clock()
            row.updated_at = now
            if status is JobStatus.RUNNING:
                row.cancel_requested = True
                return job_of(row)
            # Its queue entry stays: the worker that takes it finds it cancelled and skips it.
            row.status = JobStatus.CANCELLED.value
            row.finished_at = now
            row.stage = None
            job = job_of(row)
            await self._audit(session, "job.cancelled", job)
            return job

    async def remove(self, owner: str, job_id: UUID) -> None:
        """Delete a finished job."""
        async with self._database.transaction(owner) as session:
            row = await self._row(session, owner, job_id)
            status = JobStatus(row.status)
            if not status.finished:
                raise JobStateError(f"Job {job_id} is {status}: cancel it first", status)
            await session.execute(
                delete(JobRow).where(JobRow.owner_id == owner, JobRow.id == job_id)
            )
            await append_entry(
                session,
                JOB_STREAM,
                "job.removed",
                {"id": str(job_id)},
                owner_id=owner,
                clock=self._clock,
            )

    async def start(self, owner: str, job_id: UUID) -> Job | None:
        """Mark a queued (or orphaned running) job running; ``None`` if there is nothing to run."""
        now = self._clock()
        async with self._database.transaction(owner) as session:
            row = await session.scalar(
                update(JobRow)
                .where(
                    JobRow.owner_id == owner,
                    JobRow.id == job_id,
                    JobRow.status.in_(RESTARTABLE),
                )
                .values(
                    status=JobStatus.RUNNING.value,
                    started_at=now,
                    updated_at=now,
                    attempts=JobRow.attempts + 1,
                )
                .returning(JobRow)
            )
            return None if row is None else job_of(row)

    async def report(
        self, owner: str, job_id: UUID, *, progress: float | None, stage: str | None
    ) -> bool:
        """Record the progress of a running job; whether its owner asked to cancel it."""
        async with self._database.transaction(owner) as session:
            requested = await session.scalar(
                update(JobRow)
                .where(
                    JobRow.owner_id == owner,
                    JobRow.id == job_id,
                    JobRow.status == JobStatus.RUNNING.value,
                )
                .values(progress=progress, stage=stage, updated_at=self._clock())
                .returning(JobRow.cancel_requested)
            )
            return bool(requested)

    async def _finish(self, owner: str, job_id: UUID, status: JobStatus, **values: object) -> Job:
        now = self._clock()
        async with self._database.transaction(owner) as session:
            row = await session.scalar(
                update(JobRow)
                .where(
                    JobRow.owner_id == owner,
                    JobRow.id == job_id,
                    JobRow.status == JobStatus.RUNNING.value,
                )
                .values(status=status.value, finished_at=now, updated_at=now, stage=None, **values)
                .returning(JobRow)
            )
            if row is None:
                current = await session.scalar(
                    select(JobRow.status).where(JobRow.owner_id == owner, JobRow.id == job_id)
                )
                if current is None:
                    raise RecordNotFoundError(f"No job {job_id}")
                state = JobStatus(current)
                raise JobStateError(f"Job {job_id} is {state}, not running", state)
            job = job_of(row)
            await self._audit(session, f"job.{status.value}", job)
            return job

    async def succeed(self, owner: str, job_id: UUID, result: JsonValue) -> Job:
        """Finish a running job with its result."""
        canonical_json({"result": result})  # plain JSON with finite numbers, or ValueError
        return await self._finish(owner, job_id, JobStatus.SUCCEEDED, result=result, progress=1.0)

    async def fail(self, owner: str, job_id: UUID, error: JobError) -> Job:
        """Finish a running job with an error."""
        document = {"code": error.code, "title": error.title, "detail": error.detail}
        return await self._finish(owner, job_id, JobStatus.FAILED, error=document)

    async def stopped(self, owner: str, job_id: UUID) -> Job:
        """Finish a running job its owner asked to cancel."""
        return await self._finish(owner, job_id, JobStatus.CANCELLED)
