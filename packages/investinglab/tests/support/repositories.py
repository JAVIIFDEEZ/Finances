"""In-memory repositories: the reference behaviour the relational ones must match.

They hold everything in dictionaries, so they are for tests and for trying the use cases
without a database. Both pass the same contract tests as the SQL implementations.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from investinglab.ports import (
    JOB_STREAM,
    ChainReport,
    DuplicateNameError,
    Job,
    JobError,
    JobStateError,
    JobStatus,
    LogEntry,
    Page,
    PortfolioSpec,
    RecordNotFoundError,
    Stored,
    VersionConflictError,
    canonical_json,
    check_submission,
    decode_cursor,
    encode_cursor,
    job_outcome,
    verify_chain,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from investinglab.ports import JsonValue

__all__ = [
    "JOB_STREAM",
    "PORTFOLIO_STREAM",
    "InMemoryAuditLog",
    "InMemoryJobRepository",
    "InMemoryPortfolioRepository",
]

PORTFOLIO_STREAM = "portfolios"


def _now() -> datetime:
    return datetime.now(UTC)


class InMemoryAuditLog:
    """Hash-chained streams kept in memory."""

    def __init__(self, clock: Callable[[], datetime] = _now) -> None:
        self._clock = clock
        self.streams: dict[str, list[LogEntry]] = {}

    async def append(
        self,
        stream: str,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        owner_id: str | None = None,
    ) -> LogEntry:
        entries = self.streams.setdefault(stream, [])
        entry = LogEntry.chained(
            entries[-1] if entries else None,
            stream=stream,
            recorded_at=self._clock(),
            owner_id=owner_id,
            kind=kind,
            payload=payload,
        )
        entries.append(entry)
        return entry

    async def read(self, stream: str, *, after: int = 0, limit: int = 1_000) -> list[LogEntry]:
        entries = [e for e in self.streams.get(stream, []) if e.sequence > after]
        return entries[:limit]

    async def verify(self, stream: str) -> ChainReport:
        return verify_chain(stream, self.streams.get(stream, []))


class InMemoryPortfolioRepository:
    """Saved portfolios kept in memory, with the audit trail of every change."""

    def __init__(
        self, audit: InMemoryAuditLog | None = None, clock: Callable[[], datetime] = _now
    ) -> None:
        self._clock = clock
        self.audit = audit or InMemoryAuditLog(clock)
        self._records: dict[UUID, Stored[PortfolioSpec]] = {}

    def _owned(self, owner: str, portfolio_id: UUID) -> Stored[PortfolioSpec]:
        record = self._records.get(portfolio_id)
        if record is None or record.owner_id != owner:
            raise RecordNotFoundError(f"No portfolio {portfolio_id}")
        return record

    def _check_name(self, owner: str, name: str, *, ignore: UUID | None = None) -> None:
        for record in self._records.values():
            if record.owner_id == owner and record.value.name == name and record.id != ignore:
                raise DuplicateNameError(f"A portfolio named {name!r} already exists")

    async def _log(self, kind: str, record: Stored[PortfolioSpec]) -> None:
        payload: dict[str, JsonValue] = {
            "id": str(record.id),
            "name": record.value.name,
            "version": record.version,
        }
        await self.audit.append(
            PORTFOLIO_STREAM, f"portfolio.{kind}", payload, owner_id=record.owner_id
        )

    async def add(self, owner: str, spec: PortfolioSpec) -> Stored[PortfolioSpec]:
        self._check_name(owner, spec.name)
        now = self._clock()
        record = Stored(uuid4(), owner, 1, now, now, spec)
        self._records[record.id] = record
        await self._log("created", record)
        return record

    async def get(self, owner: str, portfolio_id: UUID) -> Stored[PortfolioSpec]:
        return self._owned(owner, portfolio_id)

    async def list(
        self, owner: str, *, limit: int = 50, cursor: str | None = None
    ) -> Page[Stored[PortfolioSpec]]:
        records = sorted(
            (r for r in self._records.values() if r.owner_id == owner),
            key=lambda r: (r.updated_at, r.id),
            reverse=True,
        )
        if cursor is not None:
            position = decode_cursor(cursor)
            records = [r for r in records if (r.updated_at, r.id) < position]
        page = records[:limit]
        more = len(records) > limit
        last = page[-1] if page else None
        next_cursor = encode_cursor(last.updated_at, last.id) if more and last else None
        return Page(tuple(page), next_cursor)

    async def replace(
        self, owner: str, portfolio_id: UUID, spec: PortfolioSpec, *, expected_version: int
    ) -> Stored[PortfolioSpec]:
        current = self._owned(owner, portfolio_id)
        if current.version != expected_version:
            raise VersionConflictError(current.version)
        self._check_name(owner, spec.name, ignore=portfolio_id)
        record = Stored(
            current.id, owner, current.version + 1, current.created_at, self._clock(), spec
        )
        self._records[record.id] = record
        await self._log("replaced", record)
        return record

    async def remove(self, owner: str, portfolio_id: UUID, *, expected_version: int) -> None:
        current = self._owned(owner, portfolio_id)
        if current.version != expected_version:
            raise VersionConflictError(current.version)
        del self._records[portfolio_id]
        await self._log("removed", current)


class InMemoryJobRepository:
    """Jobs kept in memory; :attr:`queue` is what the workers would take, in order."""

    def __init__(
        self, audit: InMemoryAuditLog | None = None, clock: Callable[[], datetime] = _now
    ) -> None:
        self._clock = clock
        self.audit = audit or InMemoryAuditLog(clock)
        self._jobs: dict[UUID, Job] = {}
        self.queue: list[tuple[str, UUID]] = []

    def _owned(self, owner: str, job_id: UUID) -> Job:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner:
            raise RecordNotFoundError(f"No job {job_id}")
        return job

    def _running(self, owner: str, job_id: UUID) -> Job:
        job = self._owned(owner, job_id)
        if job.status is not JobStatus.RUNNING:
            raise JobStateError(f"Job {job_id} is {job.status}, not running", job.status)
        return job

    async def _finish(self, job: Job) -> Job:
        job = replace(job, stage=None)  # a finished job is doing nothing
        self._jobs[job.id] = job
        await self.audit.append(
            JOB_STREAM, f"job.{job.status}", job_outcome(job), owner_id=job.owner_id
        )
        return job

    async def submit(self, owner: str, kind: str, parameters: Mapping[str, JsonValue]) -> Job:
        check_submission(kind, parameters)
        job = Job(uuid4(), owner, kind, JobStatus.QUEUED, dict(parameters), self._clock())
        self._jobs[job.id] = job
        self.queue.append((owner, job.id))
        await self.audit.append(
            JOB_STREAM, "job.submitted", {"id": str(job.id), "kind": kind}, owner_id=owner
        )
        return job

    async def get(self, owner: str, job_id: UUID) -> Job:
        return self._owned(owner, job_id)

    async def list(self, owner: str, *, limit: int = 50, cursor: str | None = None) -> Page[Job]:
        jobs = sorted(
            (job for job in self._jobs.values() if job.owner_id == owner),
            key=lambda job: (job.created_at, job.id),
            reverse=True,
        )
        if cursor is not None:
            position = decode_cursor(cursor)
            jobs = [job for job in jobs if (job.created_at, job.id) < position]
        page = jobs[:limit]
        last = page[-1] if page else None
        more = len(jobs) > limit
        return Page(tuple(page), encode_cursor(last.created_at, last.id) if more and last else None)

    async def cancel(self, owner: str, job_id: UUID) -> Job:
        job = self._owned(owner, job_id)
        if job.status.finished:
            raise JobStateError(f"Job {job_id} has already finished ({job.status})", job.status)
        if job.status is JobStatus.RUNNING:
            job = replace(job, cancel_requested=True)
            self._jobs[job_id] = job
            return job
        return await self._finish(
            replace(job, status=JobStatus.CANCELLED, finished_at=self._clock())
        )

    async def remove(self, owner: str, job_id: UUID) -> None:
        job = self._owned(owner, job_id)
        if not job.status.finished:
            raise JobStateError(f"Job {job_id} is {job.status}: cancel it first", job.status)
        del self._jobs[job_id]
        await self.audit.append(JOB_STREAM, "job.removed", {"id": str(job_id)}, owner_id=owner)

    async def start(self, owner: str, job_id: UUID) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner or job.status.finished:
            return None
        job = replace(
            job, status=JobStatus.RUNNING, started_at=self._clock(), attempts=job.attempts + 1
        )
        self._jobs[job_id] = job
        return job

    async def report(
        self, owner: str, job_id: UUID, *, progress: float | None, stage: str | None
    ) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner or job.status is not JobStatus.RUNNING:
            return False
        job = replace(job, progress=progress, stage=stage)
        self._jobs[job_id] = job
        return job.cancel_requested

    async def succeed(self, owner: str, job_id: UUID, result: JsonValue) -> Job:
        job = self._running(owner, job_id)
        canonical_json({"result": result})  # plain JSON, or ValueError
        return await self._finish(
            replace(
                job,
                status=JobStatus.SUCCEEDED,
                result=result,
                progress=1.0,
                finished_at=self._clock(),
            )
        )

    async def fail(self, owner: str, job_id: UUID, error: JobError) -> Job:
        job = self._running(owner, job_id)
        return await self._finish(
            replace(job, status=JobStatus.FAILED, error=error, finished_at=self._clock())
        )

    async def stopped(self, owner: str, job_id: UUID) -> Job:
        job = self._running(owner, job_id)
        return await self._finish(
            replace(job, status=JobStatus.CANCELLED, finished_at=self._clock())
        )
