"""Relational persistence (PostgreSQL): the API's implementation of the core's repositories.

Nothing outside this package and the application factory knows SQLAlchemy: routers and use
cases only see the ports of :mod:`investinglab.ports` (ADR-0029).

The exports are loaded when first used (PEP 562): migrating the database
(``investinglab-api db upgrade``, run by ``just dev`` before the servers) only needs Alembic,
SQLAlchemy and the models, not the core with pandas and SciPy that the repositories bring.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from investinglab_api.persistence.audit import SqlAuditLog
    from investinglab_api.persistence.database import Database, DatabaseStatus
    from investinglab_api.persistence.heartbeats import SqlHeartbeatStore
    from investinglab_api.persistence.jobs import SqlJobRepository
    from investinglab_api.persistence.portfolios import SqlPortfolioRepository
    from investinglab_api.persistence.queue import queue_app

__all__ = [
    "Database",
    "DatabaseStatus",
    "SqlAuditLog",
    "SqlHeartbeatStore",
    "SqlJobRepository",
    "SqlPortfolioRepository",
    "queue_app",
]

_EXPORTS: Final = {
    "Database": "investinglab_api.persistence.database",
    "DatabaseStatus": "investinglab_api.persistence.database",
    "SqlAuditLog": "investinglab_api.persistence.audit",
    "SqlHeartbeatStore": "investinglab_api.persistence.heartbeats",
    "SqlJobRepository": "investinglab_api.persistence.jobs",
    "SqlPortfolioRepository": "investinglab_api.persistence.portfolios",
    "queue_app": "investinglab_api.persistence.queue",
}


def __getattr__(name: str) -> object:
    """Import an export the first time it is asked for."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value  # later lookups skip this function
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
