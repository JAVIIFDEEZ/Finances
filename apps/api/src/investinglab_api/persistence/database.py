"""The connection to PostgreSQL: engine, owner-scoped transactions and health."""

from __future__ import annotations

from contextlib import asynccontextmanager
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from investinglab.config import get_logger
from investinglab.ports import RepositoryUnavailableError
from investinglab_api.persistence.ddl import OWNER_SETTING
from investinglab_api.persistence.migrate import head_revision

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["Database", "DatabaseStatus"]

log = get_logger(__name__)


class DatabaseStatus(StrEnum):
    """What the readiness probe reports about the database."""

    NOT_CONFIGURED = "not_configured"
    OK = "ok"
    MIGRATIONS_PENDING = "migrations_pending"
    UNAVAILABLE = "unavailable"


class Database:
    """A pool of connections and the only way to open a transaction.

    Args:
        url: SQLAlchemy URL of the database, with the ``postgresql+psycopg`` driver.
        pool_size: Connections kept open.
    """

    def __init__(self, url: str, *, pool_size: int = 5) -> None:
        self._engine = create_async_engine(url, pool_size=pool_size, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self, owner: str | None = None) -> AsyncIterator[AsyncSession]:
        """A transaction that commits on exit and rolls back on error.

        With an ``owner``, the database only shows and accepts that owner's rows for the
        whole transaction (row-level security): the central filter no query can forget.

        Raises:
            RepositoryUnavailableError: The database cannot be reached.
        """
        try:
            async with self._sessions() as session, session.begin():
                if owner is not None:
                    local = True  # the setting ends with the transaction
                    await session.execute(select(func.set_config(OWNER_SETTING, owner, local)))
                yield session
        except (OperationalError, InterfaceError) as error:
            log.warning("database_unavailable", error=type(error.orig).__name__)
            raise RepositoryUnavailableError("The database is not available") from error

    async def status(self) -> DatabaseStatus:
        """Whether the database answers and its schema is the one this code expects."""
        try:
            async with self._engine.connect() as connection:
                current = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        except DBAPIError as error:
            if isinstance(error, (OperationalError, InterfaceError)):
                return DatabaseStatus.UNAVAILABLE
            return DatabaseStatus.MIGRATIONS_PENDING  # no alembic_version table yet
        return (
            DatabaseStatus.OK if current == head_revision() else DatabaseStatus.MIGRATIONS_PENDING
        )

    async def dispose(self) -> None:
        """Close every connection."""
        await self._engine.dispose()
