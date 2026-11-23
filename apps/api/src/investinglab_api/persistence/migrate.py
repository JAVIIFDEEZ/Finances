"""Schema migrations (Alembic), run on purpose: ``investinglab-api db upgrade``.

The migrations ship inside the package, so the command works wherever the API is installed.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from investinglab_api.persistence.models import is_queue_object

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from sqlalchemy.engine import Engine

__all__ = [
    "CONNECT_TIMEOUT",
    "alembic_config",
    "compared",
    "current_revision",
    "engine",
    "head_revision",
    "revision",
    "upgrade",
]

MIGRATIONS = Path(__file__).parent / "migrations"

CONNECT_TIMEOUT: Final = 10
"""Seconds to wait for the database to answer before giving up with an error."""


def engine(url: str) -> Engine:
    """An engine for a one-off migration command, that gives up if nobody answers."""
    return create_engine(url, connect_args={"connect_timeout": CONNECT_TIMEOUT})


def compared(name: str | None, _type: str, _parents: MutableMapping[Any, str | None]) -> bool:
    """Whether a schema comparison looks at an object: not the queue's, Procrastinate owns them."""
    return not is_queue_object(name)


def alembic_config(url: str | None = None) -> Config:
    """Alembic's configuration, built in code (there is no ``alembic.ini``)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["url"] = url
    return config


@cache
def head_revision() -> str:
    """The revision the code expects the database to be at."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:  # pragma: no cover - there is always an initial migration
        msg = "No migrations found"
        raise RuntimeError(msg)
    return head


def upgrade(url: str, revision: str = "head") -> None:
    """Bring the database to ``revision`` (the latest by default)."""
    command.upgrade(alembic_config(url), revision)


def revision(url: str, message: str) -> None:
    """Write a new migration with what the models have and the database lacks.

    A draft to review: Alembic does not see row-level security, triggers or grants, which
    every new table needs (see :mod:`investinglab_api.persistence.ddl`).
    """
    command.revision(alembic_config(url), message=message, autogenerate=True)


def current_revision(url: str) -> str | None:
    """The revision the database is at (``None`` before the first migration)."""
    connected = engine(url)
    try:
        with connected.connect() as connection:
            try:
                value = connection.scalar(text("SELECT version_num FROM alembic_version"))
            except ProgrammingError:
                return None
            return None if value is None else str(value)
    finally:
        connected.dispose()
