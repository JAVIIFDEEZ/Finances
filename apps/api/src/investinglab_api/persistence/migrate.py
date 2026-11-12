"""Schema migrations (Alembic), run on purpose: ``investinglab-api db upgrade``.

The migrations ship inside the package, so the command works wherever the API is installed.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

__all__ = ["alembic_config", "current_revision", "head_revision", "revision", "upgrade"]

MIGRATIONS = Path(__file__).parent / "migrations"


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
    engine: Engine = create_engine(url)
    try:
        with engine.connect() as connection:
            try:
                value = connection.scalar(text("SELECT version_num FROM alembic_version"))
            except ProgrammingError:
                return None
            return None if value is None else str(value)
    finally:
        engine.dispose()
