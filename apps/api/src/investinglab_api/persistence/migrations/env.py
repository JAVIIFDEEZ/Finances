"""Alembic environment: migrations run with the URL the caller configured."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from investinglab_api.persistence.models import Base

target_metadata = Base.metadata


def run() -> None:
    """Run the migrations in one transaction."""
    url = context.config.attributes.get("url")
    if url is None:
        msg = "No database URL: run the migrations through `investinglab-api db`"
        raise RuntimeError(msg)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run()
