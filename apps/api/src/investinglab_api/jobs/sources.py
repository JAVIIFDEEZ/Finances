"""Check every data source and keep its status (ADR-0047).

The worker runs it every :data:`SOURCES_CRON` and once when it starts; the API only reads
what it kept. A source that fails is logged as a warning with its failures in a row, so the
logs tell when a source went quiet even without looking at the screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from investinglab.config import get_logger

if TYPE_CHECKING:
    from investinglab.domain.heartbeat import SourceStatus
    from investinglab.ports import HeartbeatStore
    from investinglab.toolkit import AsyncToolkit

__all__ = ["SOURCES_CRON", "check_and_record"]

log = get_logger(__name__)

SOURCES_CRON: Final = "*/15 * * * *"
"""Every quarter of an hour: about forty calls an hour across every source, within any quota."""


async def check_and_record(
    toolkit: AsyncToolkit, store: HeartbeatStore
) -> tuple[SourceStatus, ...]:
    """Ask every source its canary and keep the status of each."""
    statuses = []
    for heartbeat in await toolkit.check_sources():
        status = await store.record(heartbeat)
        statuses.append(status)
        if heartbeat.ok:
            log.info(
                "source_ok",
                provider=heartbeat.provider,
                latency=round(heartbeat.latency, 3),
                latest=heartbeat.latest.isoformat() if heartbeat.latest else None,
            )
        else:
            log.warning(
                "source_failing",
                provider=heartbeat.provider,
                failures=status.failures,
                error=heartbeat.error,
            )
    return tuple(statuses)
