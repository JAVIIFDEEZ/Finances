"""Whether each data source answers, and how fresh its data is (ADR-0047).

A *heartbeat* is one check of one source: its canary request was answered or not, how long
it took, and the instant of the latest observation the answer held. The *status* of a source
is its latest heartbeat plus what the checks before it say: since when it fails, and when it
last answered.

The age of the latest observation is information, not a verdict: a stock market is closed at
the weekend and a monthly series is a month old by design. What it tells is whether a source
that should be current has stopped moving.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from investinglab.domain.errors import DomainError

__all__ = ["SourceHeartbeat", "SourceStatus"]


def _aware(moment: datetime | None, what: str) -> None:
    if moment is not None and moment.tzinfo is None:
        raise DomainError(f"The {what} of a heartbeat needs a timezone")


@dataclass(frozen=True, slots=True)
class SourceHeartbeat:
    """One check of one data source.

    Attributes:
        provider: Name of the source.
        checked_at: When it was asked.
        ok: Whether it answered its canary with data.
        latency: Seconds until it answered (or failed).
        latest: Instant of the latest observation in the answer (the start of the last
            daily bar, the last funding settled...); ``None`` when it failed.
        error: What went wrong, when it failed (the kind of error and its message).
    """

    provider: str
    checked_at: datetime
    ok: bool
    latency: float
    latest: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise DomainError("A heartbeat names its source")
        _aware(self.checked_at, "instant")
        _aware(self.latest, "latest observation")
        if not (math.isfinite(self.latency) and self.latency >= 0):
            raise DomainError(f"A latency is zero or more seconds, got {self.latency}")
        if self.ok != (self.error is None):
            raise DomainError("A heartbeat has an error exactly when the source failed")
        if not self.ok and self.latest is not None:
            raise DomainError("A failed check has no latest observation")

    def age(self, now: datetime) -> timedelta | None:
        """How old the latest observation was at ``now``; ``None`` when there was none."""
        return None if self.latest is None else max(timedelta(0), now - self.latest)


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """The latest heartbeat of a source and what the checks before it tell.

    Attributes:
        heartbeat: The latest check.
        last_ok_at: When the source last answered (``None`` if it never has).
        failures: Checks failed in a row up to the latest (0 when it answered).
    """

    heartbeat: SourceHeartbeat
    last_ok_at: datetime | None
    failures: int

    def __post_init__(self) -> None:
        _aware(self.last_ok_at, "last answer")
        if self.failures < 0:
            raise DomainError("Failures in a row cannot be negative")
        if self.heartbeat.ok and (
            self.failures != 0 or self.last_ok_at != self.heartbeat.checked_at
        ):
            raise DomainError("A source that answered has no failures and answered then")

    @property
    def provider(self) -> str:
        """Name of the source."""
        return self.heartbeat.provider

    def after(self, heartbeat: SourceHeartbeat) -> SourceStatus:
        """The status once ``heartbeat`` is known: the history carries on.

        Raises:
            DomainError: If the heartbeat is of another source.
        """
        if heartbeat.provider != self.provider:
            raise DomainError(f"A heartbeat of {heartbeat.provider} is not {self.provider}'s")
        return (
            SourceStatus.first(heartbeat)
            if heartbeat.ok
            else SourceStatus(heartbeat, self.last_ok_at, self.failures + 1)
        )

    @staticmethod
    def first(heartbeat: SourceHeartbeat) -> SourceStatus:
        """The status of a source whose only known check is ``heartbeat``."""
        if heartbeat.ok:
            return SourceStatus(heartbeat, heartbeat.checked_at, 0)
        return SourceStatus(heartbeat, None, 1)
