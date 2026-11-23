"""Check every data source and keep its status (ADR-0047).

The worker runs it every :data:`SOURCES_CRON` and once when it starts; the API only reads
what it kept. A source that fails is logged as a warning with its failures in a row, so the
logs tell when a source went quiet even without looking at the screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from investinglab.config import get_logger
from investinglab_api import telemetry

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
    """Ask every source its canary and keep the status of each.

    When the worker traces, the whole check is one span with an event per source; a source
    that fails is an event that says so, not a failure of the check (ADR-0048).
    """
    statuses = []
    with telemetry.span("check sources") as span:
        for heartbeat in await toolkit.check_sources():
            status = await store.record(heartbeat)
            statuses.append(status)
            span.event(
                "source.checked",
                provider=heartbeat.provider,
                ok=heartbeat.ok,
                latency_seconds=heartbeat.latency,
                failures=status.failures,
            )
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
        span.set(
            **{
                "investinglab.sources.checked": len(statuses),
                "investinglab.sources.failing": sum(not s.heartbeat.ok for s in statuses),
            }
        )
    return tuple(statuses)
