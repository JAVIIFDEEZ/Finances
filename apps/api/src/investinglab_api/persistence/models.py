"""Tables, as SQLAlchemy models.

Every table of user data inherits :class:`Owned`; the few that do not are listed in
:data:`GLOBAL_TABLES`, and a test fails when a table is in neither group.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Index, MetaData, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["GLOBAL_TABLES", "AuditRow", "Base", "Owned", "PortfolioRow"]

GLOBAL_TABLES: Final = frozenset({"audit_log"})
"""Tables without an owner column: they hold no data a user edits."""

TIMESTAMPTZ: Final = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    """Base of every model, with stable names for constraints and indexes."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Owned:
    """Mixin of every table of user data: each row belongs to one owner."""

    owner_id: Mapped[str] = mapped_column(Text, nullable=False)


class PortfolioRow(Owned, Base):
    """A saved portfolio (see :class:`investinglab.ports.PortfolioSpec`)."""

    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("owner_id", "name"),
        CheckConstraint("owner_id <> ''", name="owner_not_empty"),
        CheckConstraint("name <> ''", name="name_not_empty"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_portfolios_owner_updated", "owner_id", "updated_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)


class AuditRow(Base):
    """An entry of the append-only audit log (see :class:`investinglab.ports.LogEntry`)."""

    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint("sequence >= 1", name="sequence_positive"),)

    stream: Mapped[str] = mapped_column(Text, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
