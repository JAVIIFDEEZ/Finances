"""What the database itself guarantees, checked on a real PostgreSQL.

The application connects with a role that is neither superuser nor owner of the tables, as
it should in production; ``owner`` is the role that ran the migrations.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from investinglab.ports import PortfolioSpec, RepositoryUnavailableError, verify_chain
from investinglab_api.persistence import (
    Database,
    DatabaseStatus,
    SqlAuditLog,
    SqlPortfolioRepository,
)
from investinglab_api.persistence.ddl import OWNER_SETTING
from investinglab_api.persistence.migrate import (
    alembic_config,
    current_revision,
    head_revision,
    upgrade,
)
from investinglab_api.persistence.models import GLOBAL_TABLES, Base, Owned
from investinglab_api.persistence.portfolios import name_taken

pytestmark = pytest.mark.integration

INSUFFICIENT_PRIVILEGE = "42501"
SPEC = PortfolioSpec(name="Core", weights=(("AAA.MC", 1.0),))


def psycopg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def sqlstate(error: pytest.ExceptionInfo[DBAPIError]) -> str | None:
    return getattr(error.value.orig, "sqlstate", None)


# ── Schema ─────────────────────────────────────────────────────────────────


def test_the_models_match_the_migrated_schema(postgres: dict[str, str]) -> None:
    """Like ``makemigrations --check``: a model change without its migration fails here."""
    engine = create_engine(postgres["owner"])
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
    assert current_revision(postgres["owner"]) == head_revision()


def test_every_table_has_an_owner_or_is_declared_global() -> None:
    owned = {
        table.name
        for table in Base.metadata.tables.values()
        if any(
            mapper.local_table is table and issubclass(mapper.class_, Owned)
            for mapper in Base.registry.mappers
        )
    }
    tables = set(Base.metadata.tables)

    assert owned | GLOBAL_TABLES == tables
    assert not owned & GLOBAL_TABLES
    for name in owned:
        assert not Base.metadata.tables[name].c.owner_id.nullable


def test_every_owned_table_has_forced_row_level_security(postgres: dict[str, str]) -> None:
    owned = sorted(set(Base.metadata.tables) - GLOBAL_TABLES)
    with psycopg.connect(psycopg_url(postgres["owner"])) as connection:
        flags = {
            name: (enabled, forced)
            for name, enabled, forced in connection.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(%s)",
                (owned,),
            )
        }
        policies = {
            name: (using, check)
            for name, using, check in connection.execute(
                "SELECT tablename, qual, with_check FROM pg_policies WHERE tablename = ANY(%s)",
                (owned,),
            )
        }

    assert flags == dict.fromkeys(owned, (True, True))
    for name in owned:
        using, check = policies[name]
        assert OWNER_SETTING in using
        assert OWNER_SETTING in check


def test_migrations_go_down_and_up_again(postgres: dict[str, str]) -> None:
    server = make_url(postgres["owner"])
    name = f"investinglab_migrations_{uuid4().hex[:8]}"
    admin = psycopg_url(postgres["owner"])
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    url = server.set(database=name).render_as_string(hide_password=False)
    try:
        assert current_revision(url) is None
        upgrade(url)
        assert current_revision(url) == head_revision()
        command.downgrade(alembic_config(url), "base")
        assert current_revision(url) is None
        upgrade(url)
        assert current_revision(url) == head_revision()
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


# ── Owner isolation, enforced by the database ──────────────────────────────


async def test_the_database_hides_other_owners_even_from_an_unfiltered_query(
    database: Database,
) -> None:
    portfolios = SqlPortfolioRepository(database)
    ana, bea = f"ana-{uuid4().hex[:8]}", f"bea-{uuid4().hex[:8]}"
    await portfolios.add(ana, SPEC)
    await portfolios.add(bea, SPEC)
    everything = text("SELECT owner_id FROM portfolios")  # a query that forgot its filter

    async with database.transaction(ana) as session:
        seen_by_ana = set((await session.scalars(everything)).all())
    async with database.transaction() as session:
        seen_by_nobody = (await session.scalars(everything)).all()

    assert seen_by_ana == {ana}
    assert seen_by_nobody == []


async def test_the_database_refuses_rows_for_another_owner(database: Database) -> None:
    ana, bea = f"ana-{uuid4().hex[:8]}", f"bea-{uuid4().hex[:8]}"
    insert = text(
        "INSERT INTO portfolios (id, owner_id, name, definition, version, created_at, updated_at) "
        "VALUES (:id, :owner, 'Forged', '{}', 1, now(), now())"
    )

    with pytest.raises(DBAPIError) as as_other:
        async with database.transaction(ana) as session:
            await session.execute(insert, {"id": uuid4(), "owner": bea})
    with pytest.raises(DBAPIError) as as_nobody:
        async with database.transaction() as session:
            await session.execute(insert, {"id": uuid4(), "owner": bea})

    assert sqlstate(as_other) == INSUFFICIENT_PRIVILEGE
    assert sqlstate(as_nobody) == INSUFFICIENT_PRIVILEGE


async def test_the_owner_setting_ends_with_its_transaction(database: Database) -> None:
    owner = f"ana-{uuid4().hex[:8]}"
    setting = text(f"SELECT current_setting('{OWNER_SETTING}', true)")

    async with database.transaction(owner) as session:
        inside = await session.scalar(setting)
    async with database.transaction() as session:  # the same pooled connection
        after = await session.scalar(setting)

    assert inside == owner
    assert not after


# ── Append-only log ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET payload = '{}' WHERE stream = :stream",
        "DELETE FROM audit_log WHERE stream = :stream",
        "TRUNCATE audit_log",
    ],
    ids=["update", "delete", "truncate"],
)
@pytest.mark.parametrize("role", ["app", "owner"])
async def test_nobody_can_change_the_audit_log(
    postgres: dict[str, str], statement: str, role: str
) -> None:
    """Not the application, and not even the role that owns the table."""
    stream = f"immutable-{uuid4().hex[:8]}"
    database = Database(postgres[role])
    try:
        log = SqlAuditLog(database)
        entry = await log.append(stream, "test", {"n": 1})

        with pytest.raises(DBAPIError) as refused:
            async with database.transaction() as session:
                await session.execute(text(statement), {"stream": stream})

        assert sqlstate(refused) == INSUFFICIENT_PRIVILEGE
        assert await log.read(stream) == [entry]
    finally:
        await database.dispose()


async def test_the_log_chains_entries_and_reads_them_back(database: Database) -> None:
    log = SqlAuditLog(database)
    stream = f"chain-{uuid4().hex[:8]}"

    first = await log.append(stream, "a", {"amount": 1.5, "tags": ["x", "ñ"], "none": None})
    second = await log.append(stream, "b", {"n": 2}, owner_id="ana")

    assert await log.read(stream) == [first, second]
    assert second.previous_hash == first.hash
    assert first.details == {"amount": 1.5, "tags": ["x", "ñ"], "none": None}
    assert [e.sequence for e in await log.read(stream, after=1)] == [2]
    report = await log.verify(stream)
    assert (report.intact, report.entries, report.head) == (True, 2, second.hash)
    assert (await log.verify(f"empty-{uuid4().hex[:8]}")).entries == 0


async def test_concurrent_writers_never_fork_the_chain(database: Database) -> None:
    log = SqlAuditLog(database)
    stream = f"race-{uuid4().hex[:8]}"

    await asyncio.gather(*(log.append(stream, "tick", {"n": n}) for n in range(25)))

    entries = await log.read(stream)
    assert [e.sequence for e in entries] == list(range(1, 26))
    assert sorted(e.details["n"] for e in entries) == list(range(25))  # type: ignore[type-var]
    assert (await log.verify(stream)).intact


async def test_a_rewrite_behind_the_triggers_is_still_detected(postgres: dict[str, str]) -> None:
    """Whoever controls the database can disable the triggers; the chain then tells."""
    database = Database(postgres["app"])
    stream = f"tampered-{uuid4().hex[:8]}"
    try:
        log = SqlAuditLog(database)
        for number in range(3):
            await log.append(stream, "test", {"n": number})
        with psycopg.connect(psycopg_url(postgres["owner"]), autocommit=True) as superuser:
            superuser.execute("ALTER TABLE audit_log DISABLE TRIGGER USER")
            try:
                superuser.execute(
                    "UPDATE audit_log SET payload = %s WHERE stream = %s AND sequence = 2",
                    ('{"n":99}', stream),
                )
            finally:
                superuser.execute("ALTER TABLE audit_log ENABLE TRIGGER USER")

        report = await log.verify(stream)

        assert (report.intact, report.broken_at, report.entries) == (False, 2, 1)
        assert "content" in (report.reason or "")
    finally:
        await database.dispose()


async def test_a_refused_change_writes_nothing_to_the_log(database: Database) -> None:
    portfolios = SqlPortfolioRepository(database)
    log = SqlAuditLog(database)
    owner = f"ana-{uuid4().hex[:8]}"
    saved = await portfolios.add(owner, SPEC)
    before = [e for e in await log.read("portfolios", limit=100_000) if e.owner_id == owner]

    with pytest.raises(Exception, match="version"):
        await portfolios.replace(owner, saved.id, replace(SPEC, name="Late"), expected_version=7)

    after = [e for e in await log.read("portfolios", limit=100_000) if e.owner_id == owner]
    assert after == before
    assert verify_chain("portfolios", await log.read("portfolios", limit=100_000)).intact


# ── Health ─────────────────────────────────────────────────────────────────


async def test_the_status_tells_ready_from_unmigrated_from_unreachable(
    postgres: dict[str, str], database: Database
) -> None:
    server = make_url(postgres["owner"])
    unmigrated = Database(server.set(database="postgres").render_as_string(hide_password=False))
    unreachable = Database(server.set(port=1).render_as_string(hide_password=False))
    try:
        assert await database.status() is DatabaseStatus.OK
        assert await unmigrated.status() is DatabaseStatus.MIGRATIONS_PENDING
        assert await unreachable.status() is DatabaseStatus.UNAVAILABLE
        with pytest.raises(RepositoryUnavailableError):
            await SqlPortfolioRepository(unreachable).list("anyone")
    finally:
        await unmigrated.dispose()
        await unreachable.dispose()


def test_only_the_name_constraint_means_a_duplicate_name() -> None:
    """Any other integrity error is a bug to see, not a name conflict to explain."""
    other = IntegrityError("INSERT", {}, Exception("ck_portfolios_version_positive"))

    assert name_taken("Core", other) is other
