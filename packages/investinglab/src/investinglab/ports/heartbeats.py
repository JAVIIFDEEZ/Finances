"""Where the heartbeats of the data sources are kept (ADR-0047).

They describe the platform, not any owner's data, so the store is global: no method takes
an owner. A relational implementation lives in the API (``source_heartbeats``) and an
in-memory one in the tests; both pass the same contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from investinglab.domain.heartbeat import SourceHeartbeat, SourceStatus

__all__ = ["HeartbeatStore"]


@runtime_checkable
class HeartbeatStore(Protocol):
    """The status of every data source checked so far."""

    async def record(self, heartbeat: SourceHeartbeat) -> SourceStatus:
        """Keep a check and return the source's status after it (failures in a row...)."""
        ...

    async def statuses(self) -> tuple[SourceStatus, ...]:
        """The status of every source checked, by name."""
        ...
