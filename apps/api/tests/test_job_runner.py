"""How a worker runs a job: outcome, progress, cancellation and failures (in-memory store)."""

from __future__ import annotations

import asyncio
import math
import time
from typing import TYPE_CHECKING

import pytest

from investinglab.domain.errors import DomainError
from investinglab.ports import JobStatus
from investinglab.services import DataUnavailableError
from investinglab_api.jobs import MAX_ATTEMPTS, JobContext, job_error, run_job
from investinglab_api.settings import ApiSettings
from support.repositories import InMemoryJobRepository

if TYPE_CHECKING:
    from collections.abc import Mapping

    from investinglab.ports import Job, JsonValue
    from investinglab.toolkit import AsyncToolkit
    from investinglab_api.jobs import Handler

OWNER = "owner-runner"
FAST = 0.01
"""Flush interval of these tests: progress and cancellation are noticed at once."""


async def _run(
    jobs: InMemoryJobRepository,
    toolkit: AsyncToolkit,
    handlers: Mapping[str, Handler],
    job: Job,
) -> Job | None:
    return await run_job(
        jobs,
        handlers,
        toolkit=toolkit,
        settings=ApiSettings(),
        owner=OWNER,
        job_id=job.id,
        flush_seconds=FAST,
    )


async def _answer(context: JobContext) -> JsonValue:
    context.progress.update(0.5, "halfway")
    await asyncio.sleep(3 * FAST)  # long enough for a report to be written
    return {"answer": 42, "echo": context.parameters["question"]}


async def test_a_job_runs_to_its_result_and_reports_its_progress(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "answer", {"question": "life"})
    reported: list[tuple[float | None, str | None]] = []
    report = jobs.report

    async def spy(owner: str, job_id: object, **progress: object) -> bool:
        reported.append((progress["progress"], progress["stage"]))  # type: ignore[arg-type]
        return await report(owner, job_id, **progress)  # type: ignore[arg-type]

    jobs.report = spy  # type: ignore[method-assign]
    done = await _run(jobs, toolkit, {"answer": _answer}, submitted)

    assert done is not None
    assert done.status is JobStatus.SUCCEEDED
    assert done.result == {"answer": 42, "echo": "life"}
    assert (done.progress, done.attempts) == (1.0, 1)
    assert (0.5, "halfway") in reported


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (DomainError("not enough history"), "invalid-request"),
        (DataUnavailableError("NOPE", ()), "data-not-found"),
        (TimeoutError("slow"), "timeout"),
        (RuntimeError("bug"), "internal-error"),
    ],
    ids=["domain", "no-data", "timeout", "bug"],
)
async def test_a_failure_is_recorded_with_the_api_vocabulary(
    toolkit: AsyncToolkit, error: Exception, code: str
) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "boom", {})

    async def boom(_: JobContext) -> JsonValue:
        raise error

    done = await _run(jobs, toolkit, {"boom": boom}, submitted)

    assert done is not None
    assert done.status is JobStatus.FAILED
    assert done.error is not None
    assert done.error.code == code
    assert "bug" not in done.error.detail  # internal details stay in the logs


async def test_a_result_that_is_not_json_fails_the_job(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "nan", {})

    async def nan(_: JobContext) -> JsonValue:
        return {"value": math.nan}

    done = await _run(jobs, toolkit, {"nan": nan}, submitted)

    assert done is not None
    assert (done.status, done.error.code if done.error else None) == (
        JobStatus.FAILED,
        "internal-error",
    )


async def test_cancelling_stops_a_job_working_in_a_thread(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "slow", {})
    started = asyncio.Event()

    async def slow(context: JobContext) -> JsonValue:
        def chunks() -> int:
            for done in range(1, 10_000):
                context.progress.update(done / 10_000, "working")  # raises once cancelled
                time.sleep(FAST / 10)
            return done

        started.set()
        return await asyncio.to_thread(chunks)

    running = asyncio.create_task(_run(jobs, toolkit, {"slow": slow}, submitted))
    await started.wait()
    await asyncio.sleep(2 * FAST)
    asked = await jobs.cancel(OWNER, submitted.id)
    done = await asyncio.wait_for(running, timeout=5)

    assert (asked.status, asked.cancel_requested) == (JobStatus.RUNNING, True)
    assert done is not None
    assert done.status is JobStatus.CANCELLED
    assert done.result is None


async def test_a_report_after_the_cancellation_stops_the_job(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "late", {})

    async def late(context: JobContext) -> JsonValue:
        context.progress.cancelled.set()  # the runner learnt it between two reports
        context.progress.update(0.9)
        return "never"

    done = await _run(jobs, toolkit, {"late": late}, submitted)

    assert done is not None
    assert done.status is JobStatus.CANCELLED


async def test_cancelling_stops_a_job_waiting_on_the_network(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "waiting", {})

    async def waiting(_: JobContext) -> JsonValue:
        await asyncio.sleep(60)
        return "never"

    running = asyncio.create_task(_run(jobs, toolkit, {"waiting": waiting}, submitted))
    await asyncio.sleep(2 * FAST)
    await jobs.cancel(OWNER, submitted.id)
    done = await asyncio.wait_for(running, timeout=5)

    assert done is not None
    assert done.status is JobStatus.CANCELLED


async def test_a_stopping_worker_records_the_job_as_interrupted(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "waiting", {})

    async def waiting(_: JobContext) -> JsonValue:
        await asyncio.sleep(60)
        return "never"

    running = asyncio.create_task(_run(jobs, toolkit, {"waiting": waiting}, submitted))
    await asyncio.sleep(2 * FAST)
    running.cancel()  # what the worker does to its jobs when it shuts down
    with pytest.raises(asyncio.CancelledError):
        await running

    stored = await jobs.get(OWNER, submitted.id)
    assert stored.status is JobStatus.FAILED
    assert stored.error is not None
    assert stored.error.code == "job-interrupted"


async def test_a_kind_no_worker_knows_fails(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "mystery", {})

    done = await _run(jobs, toolkit, {}, submitted)

    assert done is not None
    assert done.error is not None
    assert (done.status, done.error.code) == (JobStatus.FAILED, "invalid-request")
    assert "mystery" in done.error.detail


async def test_a_job_whose_worker_keeps_dying_ends_interrupted(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "answer", {"question": "again"})
    for _ in range(MAX_ATTEMPTS):  # started, then its worker vanished each time
        await jobs.start(OWNER, submitted.id)

    done = await _run(jobs, toolkit, {"answer": _answer}, submitted)

    assert done is not None
    assert done.error is not None
    assert (done.status, done.error.code, done.attempts) == (
        JobStatus.FAILED,
        "job-interrupted",
        MAX_ATTEMPTS + 1,
    )


async def test_a_job_lost_once_runs_again(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "answer", {"question": "again"})
    await jobs.start(OWNER, submitted.id)  # its first worker died while running it

    done = await _run(jobs, toolkit, {"answer": _answer}, submitted)

    assert done is not None
    assert (done.status, done.attempts) == (JobStatus.SUCCEEDED, 2)


async def test_a_finished_or_cancelled_job_is_skipped(toolkit: AsyncToolkit) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "answer", {"question": "skip"})
    await jobs.cancel(OWNER, submitted.id)  # cancelled while queued

    assert await _run(jobs, toolkit, {"answer": _answer}, submitted) is None
    assert (await jobs.get(OWNER, submitted.id)).status is JobStatus.CANCELLED


async def test_a_job_cancelled_before_its_worker_reported_stops_at_once(
    toolkit: AsyncToolkit,
) -> None:
    jobs = InMemoryJobRepository()
    submitted = await jobs.submit(OWNER, "answer", {"question": "late"})
    await jobs.start(OWNER, submitted.id)
    await jobs.cancel(OWNER, submitted.id)  # asked while a lost worker held it

    done = await _run(jobs, toolkit, {"answer": _answer}, submitted)

    assert done is not None
    assert done.status is JobStatus.CANCELLED


def test_errors_keep_the_meaning_of_the_api_problems() -> None:
    assert job_error(DomainError("bad")).title == "Invalid request"
    assert job_error(TimeoutError()).detail == "The job took too long: no detail"
