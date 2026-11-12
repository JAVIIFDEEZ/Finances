"""One contract for every repository: the in-memory reference and the PostgreSQL one.

Each test runs against both. What a use case learns with the in-memory repository therefore
holds on the real database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from investinglab.domain.errors import DomainError
from investinglab.domain.portfolio import RebalancePolicy
from investinglab.domain.time import Frequency
from investinglab.ports import (
    AuditLog,
    DuplicateNameError,
    PortfolioRepository,
    PortfolioSpec,
    RecordNotFoundError,
    VersionConflictError,
)
from investinglab_api.persistence import SqlAuditLog, SqlPortfolioRepository
from support.repositories import PORTFOLIO_STREAM, InMemoryAuditLog, InMemoryPortfolioRepository

type Repositories = tuple[PortfolioRepository, AuditLog]


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
