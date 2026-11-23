"""One contract for every repository: the in-memory reference and the PostgreSQL one.

Each test runs against both. What a use case learns with the in-memory repository therefore
holds on the real database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from investinglab.domain.errors import DomainError
from investinglab.domain.heartbeat import SourceHeartbeat, SourceStatus
from investinglab.domain.portfolio import RebalancePolicy
from investinglab.domain.time import Frequency
from investinglab.ports import (
    JOB_STREAM,
    AuditLog,
    DuplicateNameError,
    HeartbeatStore,
    JobError,
    JobRepository,
    JobStateError,
    JobStatus,
    JsonValue,
    PortfolioRepository,
    PortfolioSpec,
    RecordNotFoundError,
    VersionConflictError,
    job_outcome,
)
from investinglab_api.persistence import (
    SqlAuditLog,
    SqlHeartbeatStore,
    SqlJobRepository,
    SqlPortfolioRepository,
    queue_app,
)
from support.repositories import (
    PORTFOLIO_STREAM,
    InMemoryAuditLog,
    InMemoryHeartbeatStore,
    InMemoryJobRepository,
    InMemoryPortfolioRepository,
)

type Repositories = tuple[PortfolioRepository, AuditLog]
type JobStores = tuple[JobRepository, AuditLog]


class Clock:
    """A clock that never repeats an instant: listings have a definite order."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(milliseconds=1)
        return self.now


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repositories(request: pytest.FixtureRequest) -> Repositories:
    clock = Clock()
    if request.param == "memory":
        audit = InMemoryAuditLog(clock)
        return InMemoryPortfolioRepository(audit, clock), audit
    database = request.getfixturevalue("database")
    return SqlPortfolioRepository(database, clock), SqlAuditLog(database, clock)


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def job_stores(request: pytest.FixtureRequest) -> JobStores:
    clock = Clock()
    if request.param == "memory":
        audit = InMemoryAuditLog(clock)
        return InMemoryJobRepository(audit, clock), audit
    database = request.getfixturevalue("database")
    postgres = request.getfixturevalue("postgres")
    return SqlJobRepository(database, queue_app(postgres["app"]), clock), SqlAuditLog(
        database, clock
    )


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def heartbeats(request: pytest.FixtureRequest) -> HeartbeatStore:
    if request.param == "memory":
        return InMemoryHeartbeatStore()
    return SqlHeartbeatStore(request.getfixturevalue("database"))


@pytest.fixture
def owner() -> str:
    """An owner nobody else uses: the tests share one database."""
    return f"owner-{uuid4().hex[:12]}"


def spec(name: str = "Core", **changes: object) -> PortfolioSpec:
    fields: dict[str, object] = {
        "name": name,
        "weights": (("AAA.MC", 0.6), ("BBB.MC", 0.4)),
        **changes,
    }
    return PortfolioSpec(**fields)  # type: ignore[arg-type]


async def test_a_saved_portfolio_reads_back_exactly(repositories: Repositories, owner: str) -> None:
    portfolios, _ = repositories
    full = spec(
        "Global · ñ",
        weights=(("BBB.MC", -0.25), ("AAA.MC", 1.25)),
        base_currency="EUR",
        rebalance=RebalancePolicy.threshold(0.05),
        allow_short=True,
        start=date(2020, 1, 2),
        end=date(2025, 6, 30),
        frequency=Frequency.WEEK_1,
    )

    saved = await portfolios.add(owner, full)
    read = await portfolios.get(owner, saved.id)

    assert read == saved
    assert read.value == full
    assert (read.version, read.owner_id) == (1, owner)
    assert read.created_at == read.updated_at
    assert read.created_at.tzinfo is not None


async def test_every_policy_survives_the_round_trip(repositories: Repositories, owner: str) -> None:
    portfolios, _ = repositories
    policies = [
        RebalancePolicy.buy_and_hold(),
        RebalancePolicy.periodic(Frequency.QUARTER_1),
        RebalancePolicy.threshold(0.1),
    ]

    for number, policy in enumerate(policies):
        saved = await portfolios.add(owner, spec(f"P{number}", rebalance=policy))
        assert (await portfolios.get(owner, saved.id)).value.rebalance == policy


async def test_one_owner_never_sees_anothers_portfolios(
    repositories: Repositories, owner: str
) -> None:
    portfolios, _ = repositories
    other = f"{owner}-other"
    mine = await portfolios.add(owner, spec("Mine"))
    theirs = await portfolios.add(other, spec("Theirs"))

    assert [r.id for r in (await portfolios.list(owner)).items] == [mine.id]
    assert [r.id for r in (await portfolios.list(other)).items] == [theirs.id]
    for attempt in (
        lambda: portfolios.get(owner, theirs.id),
        lambda: portfolios.replace(owner, theirs.id, spec("Stolen"), expected_version=1),
        lambda: portfolios.remove(owner, theirs.id, expected_version=1),
    ):
        with pytest.raises(RecordNotFoundError):  # not found, never "forbidden"
            await attempt()
    assert (await portfolios.get(other, theirs.id)).value.name == "Theirs"


async def test_names_are_unique_per_owner_not_globally(
    repositories: Repositories, owner: str
) -> None:
    portfolios, _ = repositories
    first = await portfolios.add(owner, spec("Core"))
    second = await portfolios.add(owner, spec("Satellite"))
    await portfolios.add(f"{owner}-other", spec("Core"))  # another owner may reuse the name

    with pytest.raises(DuplicateNameError, match="Core"):
        await portfolios.add(owner, spec("Core"))
    with pytest.raises(DuplicateNameError, match="Core"):
        await portfolios.replace(owner, second.id, spec("Core"), expected_version=1)

    kept = await portfolios.replace(owner, first.id, spec("Core"), expected_version=1)
    assert kept.version == 2  # keeping its own name is no conflict
    assert (await portfolios.get(owner, second.id)).version == 1  # the refused change left it


async def test_a_replacement_needs_the_version_it_read(
    repositories: Repositories, owner: str
) -> None:
    portfolios, _ = repositories
    saved = await portfolios.add(owner, spec("Core"))

    changed = await portfolios.replace(
        owner, saved.id, spec("Core v2", allow_short=True), expected_version=1
    )

    assert (changed.version, changed.value.name, changed.value.allow_short) == (2, "Core v2", True)
    assert changed.created_at == saved.created_at
    assert changed.updated_at > saved.updated_at
    with pytest.raises(VersionConflictError) as conflict:  # a second writer with a stale copy
        await portfolios.replace(owner, saved.id, spec("Lost update"), expected_version=1)
    assert conflict.value.current_version == 2
    assert (await portfolios.get(owner, saved.id)).value.name == "Core v2"


async def test_a_removal_needs_the_version_it_read(repositories: Repositories, owner: str) -> None:
    portfolios, _ = repositories
    saved = await portfolios.add(owner, spec("Core"))
    await portfolios.replace(owner, saved.id, spec("Core"), expected_version=1)

    with pytest.raises(VersionConflictError) as conflict:
        await portfolios.remove(owner, saved.id, expected_version=1)
    assert conflict.value.current_version == 2
    await portfolios.remove(owner, saved.id, expected_version=2)

    with pytest.raises(RecordNotFoundError):
        await portfolios.get(owner, saved.id)
    with pytest.raises(RecordNotFoundError):
        await portfolios.remove(owner, saved.id, expected_version=2)
    assert (await portfolios.list(owner)).items == ()


async def test_missing_portfolios_are_not_found(repositories: Repositories, owner: str) -> None:
    portfolios, _ = repositories

    with pytest.raises(RecordNotFoundError):
        await portfolios.get(owner, uuid4())
    with pytest.raises(RecordNotFoundError):
        await portfolios.replace(owner, uuid4(), spec(), expected_version=1)


async def test_listings_page_from_the_most_recently_updated(
    repositories: Repositories, owner: str
) -> None:
    portfolios, _ = repositories
    saved = [await portfolios.add(owner, spec(f"P{number}")) for number in range(5)]
    await portfolios.replace(owner, saved[1].id, spec("P1 touched"), expected_version=1)
    expected = ["P1 touched", "P4", "P3", "P2", "P0"]

    first = await portfolios.list(owner, limit=2)
    second = await portfolios.list(owner, limit=2, cursor=first.next_cursor)
    third = await portfolios.list(owner, limit=2, cursor=second.next_cursor)

    names = [r.value.name for page in (first, second, third) for r in page.items]
    assert names == expected
    assert first.next_cursor is not None
    assert second.next_cursor is not None
    assert third.next_cursor is None
    assert [r.value.name for r in (await portfolios.list(owner)).items] == expected
    with pytest.raises(DomainError, match="cursor"):
        await portfolios.list(owner, cursor="not-a-cursor")


async def test_every_change_leaves_an_entry_in_the_audit_log(
    repositories: Repositories, owner: str
) -> None:
    portfolios, audit = repositories
    start = len(await audit.read(PORTFOLIO_STREAM, limit=100_000))
    saved = await portfolios.add(owner, spec("Core"))
    await portfolios.replace(owner, saved.id, spec("Core v2"), expected_version=1)
    await portfolios.remove(owner, saved.id, expected_version=2)
    await portfolios.add(owner, spec("Dup"))
    with pytest.raises(DuplicateNameError):  # a refused change leaves no entry
        await portfolios.add(owner, spec("Dup"))

    entries = [
        e
        for e in await audit.read(PORTFOLIO_STREAM, after=start, limit=100_000)
        if e.owner_id == owner
    ]

    assert [(e.kind, e.details["name"], e.details["version"]) for e in entries] == [
        ("portfolio.created", "Core", 1),
        ("portfolio.replaced", "Core v2", 2),
        ("portfolio.removed", "Core v2", 2),
        ("portfolio.created", "Dup", 1),
    ]
    assert all(e.details["id"] == str(saved.id) for e in entries[:3])
    assert (await audit.verify(PORTFOLIO_STREAM)).intact


# ── Background jobs ────────────────────────────────────────────────────────

PARAMETERS: dict[str, JsonValue] = {
    "portfolio": {"holdings": [{"symbol": "AAA.MC", "weight": 1.0}]},
    "n_paths": 500,
}


async def test_a_submitted_job_reads_back_queued(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores

    job = await jobs.submit(owner, "simulation", PARAMETERS)
    read = await jobs.get(owner, job.id)

    assert read == job
    assert (read.status, read.kind, read.owner_id, read.attempts) == (
        JobStatus.QUEUED,
        "simulation",
        owner,
        0,
    )
    assert read.parameters == PARAMETERS
    assert (read.started_at, read.finished_at, read.progress, read.result) == (
        None,
        None,
        None,
        None,
    )
    assert read.created_at.tzinfo is not None


@pytest.mark.parametrize(
    ("kind", "parameters", "problem"),
    [
        ("", {}, "kind"),
        ("x" * 41, {}, "kind"),
        ("simulation", {"value": float("nan")}, "plain JSON"),
    ],
    ids=["empty-kind", "long-kind", "nan"],
)
async def test_a_submission_is_validated(
    job_stores: JobStores, owner: str, kind: str, parameters: dict[str, object], problem: str
) -> None:
    jobs, _ = job_stores

    with pytest.raises(DomainError, match=problem):
        await jobs.submit(owner, kind, parameters)  # type: ignore[arg-type]
    assert (await jobs.list(owner)).items == ()


async def test_a_job_runs_from_queued_to_succeeded(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)

    started = await jobs.start(owner, job.id)
    asked = await jobs.report(owner, job.id, progress=0.25, stage="simulating")
    running = await jobs.get(owner, job.id)
    done = await jobs.succeed(owner, job.id, {"paths": [1.0, 2.5], "label": "ñ"})

    assert started is not None
    assert (started.status, started.attempts) == (JobStatus.RUNNING, 1)
    assert started.started_at is not None
    assert asked is False
    assert (running.progress, running.stage) == (0.25, "simulating")
    assert (done.status, done.progress, done.stage) == (JobStatus.SUCCEEDED, 1.0, None)
    assert done.result == {"paths": [1.0, 2.5], "label": "ñ"}
    assert done.finished_at is not None
    assert await jobs.get(owner, job.id) == done


async def test_a_failed_job_keeps_its_error(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)
    await jobs.start(owner, job.id)
    error = JobError("data-not-found", "Data not found", "Nobody has NOPE.MC")

    failed = await jobs.fail(owner, job.id, error)

    assert (failed.status, failed.error, failed.result) == (JobStatus.FAILED, error, None)
    assert (await jobs.get(owner, job.id)).error == error


async def test_cancelling_a_queued_job_finishes_it(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)

    cancelled = await jobs.cancel(owner, job.id)

    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.finished_at is not None
    assert await jobs.start(owner, job.id) is None  # the worker that takes it skips it
    with pytest.raises(JobStateError) as refused:
        await jobs.cancel(owner, job.id)
    assert refused.value.status is JobStatus.CANCELLED


async def test_cancelling_a_running_job_asks_it_to_stop(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)
    await jobs.start(owner, job.id)

    asked = await jobs.cancel(owner, job.id)
    told = await jobs.report(owner, job.id, progress=0.5, stage=None)
    stopped = await jobs.stopped(owner, job.id)

    assert (asked.status, asked.cancel_requested) == (JobStatus.RUNNING, True)
    assert told is True
    assert (stopped.status, stopped.result, stopped.error, stopped.stage) == (
        JobStatus.CANCELLED,
        None,
        None,
        None,
    )


async def test_only_a_running_job_can_finish(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)

    with pytest.raises(JobStateError) as queued:
        await jobs.succeed(owner, job.id, {"early": True})
    await jobs.start(owner, job.id)
    await jobs.succeed(owner, job.id, {"done": True})
    with pytest.raises(JobStateError) as twice:
        await jobs.fail(owner, job.id, JobError("internal-error", "Internal error", "late"))

    assert queued.value.status is JobStatus.QUEUED
    assert twice.value.status is JobStatus.SUCCEEDED
    assert await jobs.report(owner, job.id, progress=0.1, stage=None) is False
    assert await jobs.start(owner, job.id) is None  # a finished job never runs again


async def test_a_lost_worker_lets_the_job_start_again(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)

    await jobs.start(owner, job.id)
    again = await jobs.start(owner, job.id)

    assert again is not None
    assert (again.status, again.attempts) == (JobStatus.RUNNING, 2)


async def test_only_a_finished_job_can_be_removed(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)

    with pytest.raises(JobStateError):
        await jobs.remove(owner, job.id)
    await jobs.cancel(owner, job.id)
    await jobs.remove(owner, job.id)

    with pytest.raises(RecordNotFoundError):
        await jobs.get(owner, job.id)


async def test_another_owners_job_does_not_exist(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    job = await jobs.submit(owner, "simulation", PARAMETERS)
    stranger = f"{owner}-other"

    for attempt in (
        jobs.get(stranger, job.id),
        jobs.cancel(stranger, job.id),
        jobs.remove(stranger, job.id),
        jobs.succeed(stranger, job.id, {"stolen": True}),
    ):
        with pytest.raises(RecordNotFoundError):
            await attempt
    assert await jobs.start(stranger, job.id) is None
    assert (await jobs.list(stranger)).items == ()
    assert (await jobs.get(owner, job.id)).status is JobStatus.QUEUED


async def test_jobs_are_listed_from_the_newest(job_stores: JobStores, owner: str) -> None:
    jobs, _ = job_stores
    submitted = [await jobs.submit(owner, "simulation", PARAMETERS) for _ in range(5)]

    first = await jobs.list(owner, limit=2)
    second = await jobs.list(owner, limit=2, cursor=first.next_cursor)
    third = await jobs.list(owner, limit=2, cursor=second.next_cursor)

    listed = [job.id for page in (first, second, third) for job in page.items]
    assert listed == [job.id for job in reversed(submitted)]
    assert third.next_cursor is None
    with pytest.raises(DomainError, match="cursor"):
        await jobs.list(owner, cursor="not-a-cursor")


async def test_every_outcome_leaves_an_entry_in_the_audit_log(
    job_stores: JobStores, owner: str
) -> None:
    jobs, audit = job_stores
    start = len(await audit.read(JOB_STREAM, limit=100_000))
    done = await jobs.submit(owner, "simulation", PARAMETERS)
    await jobs.start(owner, done.id)
    succeeded = await jobs.succeed(owner, done.id, {"value": 1.5})
    dropped = await jobs.submit(owner, "simulation", PARAMETERS)
    await jobs.cancel(owner, dropped.id)
    await jobs.remove(owner, dropped.id)

    entries = [
        e for e in await audit.read(JOB_STREAM, after=start, limit=100_000) if e.owner_id == owner
    ]

    assert [e.kind for e in entries] == [
        "job.submitted",
        "job.succeeded",
        "job.submitted",
        "job.cancelled",
        "job.removed",
    ]
    assert entries[1].details == job_outcome(succeeded)  # the result's digest, not the result
    assert "result_sha256" in entries[1].details
    assert (await audit.verify(JOB_STREAM)).intact


# ── Source heartbeats (ADR-0047) ─────────────────────────────────────


@pytest.fixture
def source() -> str:
    """A source nobody else checks: the table is global and the tests share one database."""
    return f"source-{uuid4().hex[:12]}"


def _check(
    source: str, at: datetime, *, ok: bool = True, latency: float = 0.4321
) -> SourceHeartbeat:
    if ok:
        latest = datetime(2026, 11, 20, tzinfo=UTC)
        return SourceHeartbeat(source, at, ok=True, latency=latency, latest=latest)
    error = "TimeoutError: " + "x" * 290  # about as long as one is kept
    return SourceHeartbeat(source, at, ok=False, latency=latency, error=error)


async def _status_of(store: HeartbeatStore, source: str) -> list[SourceStatus]:
    return [status for status in await store.statuses() if status.provider == source]


async def test_a_heartbeat_reads_back_exactly(heartbeats: HeartbeatStore, source: str) -> None:
    checked = datetime(2026, 11, 23, 9, 15, 30, 123456, tzinfo=UTC)

    recorded = await heartbeats.record(_check(source, checked))

    assert recorded == SourceStatus(_check(source, checked), checked, 0)
    assert await _status_of(heartbeats, source) == [recorded]


async def test_failures_add_up_until_the_source_answers(
    heartbeats: HeartbeatStore, source: str
) -> None:
    start = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
    at = [start + timedelta(minutes=15 * step) for step in range(4)]

    await heartbeats.record(_check(source, at[0]))
    await heartbeats.record(_check(source, at[1], ok=False))
    failing = await heartbeats.record(_check(source, at[2], ok=False, latency=30.0))

    assert (failing.last_ok_at, failing.failures) == (at[0], 2)
    assert failing.heartbeat == _check(source, at[2], ok=False, latency=30.0)
    assert await _status_of(heartbeats, source) == [failing]
    back = await heartbeats.record(_check(source, at[3]))
    assert (back.last_ok_at, back.failures, back.heartbeat.error) == (at[3], 0, None)


async def test_a_source_that_never_answered(heartbeats: HeartbeatStore, source: str) -> None:
    status = await heartbeats.record(_check(source, datetime.now(UTC), ok=False))

    assert (status.last_ok_at, status.failures, status.heartbeat.latest) == (None, 1, None)


async def test_sources_are_listed_by_name(heartbeats: HeartbeatStore, source: str) -> None:
    now = datetime.now(UTC)
    for name in (f"{source}-b", f"{source}-a", f"{source}-c"):
        await heartbeats.record(_check(name, now))

    names = [status.provider for status in await heartbeats.statuses()]

    mine = [name for name in names if name.startswith(source)]
    assert mine == [f"{source}-a", f"{source}-b", f"{source}-c"]
    assert names == sorted(names)
