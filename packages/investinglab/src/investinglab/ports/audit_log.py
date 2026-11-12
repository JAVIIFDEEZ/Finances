"""Append-only audit log: entries that can be added and read, never changed.

Experiments, order execution and security events need a record nobody can rewrite, not even
by mistake. A store that implements :class:`AuditLog` refuses updates and deletions, and
every entry carries the hash of the previous one of its stream, so a modified, removed or
reordered entry breaks the chain and :func:`verify_chain` says where.

The chain is tamper-*evident*, not tamper-proof: whoever controls the database can rebuild
it from the tampered entry onwards, or cut its tail. Keeping the last hash of a stream
somewhere else (a report, another system) detects both.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "GENESIS_HASH",
    "AuditLog",
    "ChainReport",
    "JsonValue",
    "LogEntry",
    "canonical_json",
    "entry_hash",
    "verify_chain",
]

type JsonValue = bool | int | float | str | Sequence["JsonValue"] | Mapping[str, "JsonValue"] | None
"""What a payload may hold: plain JSON, with finite numbers."""

GENESIS_HASH: Final = "0" * 64
"""Previous hash of the first entry of every stream."""


def canonical_json(payload: Mapping[str, JsonValue]) -> str:
    """The one text form of a payload: sorted keys, no spaces, UTF-8, finite numbers.

    The stored text is what gets hashed, so verifying never depends on how a database
    would re-serialise the value.

    Raises:
        ValueError: The payload holds NaN, infinity or something that is not JSON.
    """
    _check(payload)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _check(value: object) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = "Audit payloads take finite numbers only"
            raise ValueError(msg)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                msg = f"Audit payload keys must be text, got {type(key).__name__}"
                raise ValueError(msg)  # noqa: TRY004 - one error type for an invalid payload
            _check(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check(item)
        return
    msg = f"Audit payloads take plain JSON values, got {type(value).__name__}"
    raise ValueError(msg)


def _instant(moment: datetime) -> str:
    if moment.tzinfo is None:
        msg = "Audit entries need a timezone-aware instant"
        raise ValueError(msg)
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def entry_hash(
    *,
    previous_hash: str,
    stream: str,
    sequence: int,
    recorded_at: datetime,
    owner_id: str | None,
    kind: str,
    payload: str,
) -> str:
    """SHA-256 of an entry chained to the previous one of its stream (hex).

    Every field takes part, length-prefixed, so no two different entries share an input.

    Args:
        previous_hash: Hash of the previous entry (:data:`GENESIS_HASH` for the first).
        stream: Name of the chain.
        sequence: Position in the stream, from 1.
        recorded_at: Instant of the entry (timezone-aware; hashed in UTC to the microsecond).
        owner_id: Owner the entry is about, if any.
        kind: What happened.
        payload: Canonical JSON of the details (see :func:`canonical_json`).
    """
    parts = (
        previous_hash,
        stream,
        str(sequence),
        _instant(recorded_at),
        "" if owner_id is None else f"owner:{owner_id}",
        kind,
        payload,
    )
    digest = hashlib.sha256()
    for part in parts:
        raw = part.encode("utf-8")
        digest.update(f"{len(raw)}:".encode("ascii"))
        digest.update(raw)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One entry of a stream.

    Attributes:
        stream: Name of the chain the entry belongs to.
        sequence: Position in the stream, from 1 and without gaps.
        recorded_at: Instant the entry was written (timezone-aware).
        owner_id: Owner the entry is about, if any.
        kind: What happened (``portfolio.created``…).
        payload: Canonical JSON of the details.
        previous_hash: Hash of the previous entry of the stream.
        hash: Hash of this entry (see :func:`entry_hash`).
    """

    stream: str
    sequence: int
    recorded_at: datetime
    owner_id: str | None
    kind: str
    payload: str
    previous_hash: str
    hash: str

    @classmethod
    def chained(
        cls,
        previous: LogEntry | None,
        *,
        stream: str,
        recorded_at: datetime,
        owner_id: str | None,
        kind: str,
        payload: Mapping[str, JsonValue],
    ) -> LogEntry:
        """The entry that follows ``previous`` in ``stream`` (``None``: the first one)."""
        if not stream or not kind:
            msg = "Audit entries need a stream and a kind"
            raise ValueError(msg)
        sequence = 1 if previous is None else previous.sequence + 1
        previous_hash = GENESIS_HASH if previous is None else previous.hash
        text = canonical_json(payload)
        digest = entry_hash(
            previous_hash=previous_hash,
            stream=stream,
            sequence=sequence,
            recorded_at=recorded_at,
            owner_id=owner_id,
            kind=kind,
            payload=text,
        )
        return cls(stream, sequence, recorded_at, owner_id, kind, text, previous_hash, digest)

    @property
    def details(self) -> dict[str, JsonValue]:
        """The payload, parsed."""
        parsed: dict[str, JsonValue] = json.loads(self.payload)
        return parsed

    def expected_hash(self) -> str:
        """The hash the entry should carry, recomputed from its fields."""
        return entry_hash(
            previous_hash=self.previous_hash,
            stream=self.stream,
            sequence=self.sequence,
            recorded_at=self.recorded_at,
            owner_id=self.owner_id,
            kind=self.kind,
            payload=self.payload,
        )


@dataclass(frozen=True, slots=True)
class ChainReport:
    """Result of verifying a stream.

    Attributes:
        stream: The stream verified.
        entries: Entries checked.
        head: Hash of the last valid entry (:data:`GENESIS_HASH` for an empty stream): keep
            it elsewhere to detect a truncated or rebuilt chain.
        broken_at: Sequence of the first entry that does not fit the chain, if any.
        reason: Why it does not fit.
    """

    stream: str
    entries: int
    head: str
    broken_at: int | None = None
    reason: str | None = None

    @property
    def intact(self) -> bool:
        """Whether every entry fits the chain."""
        return self.broken_at is None


def verify_chain(stream: str, entries: Iterable[LogEntry]) -> ChainReport:
    """Check that ``entries`` (in order) form the unbroken chain of ``stream``.

    Detects a changed entry (its hash no longer matches), a missing or reordered one (the
    sequence or the previous hash does not follow) and an entry from another stream.
    """
    head = GENESIS_HASH
    count = 0
    for expected, entry in enumerate(entries, start=1):
        reason = None
        if entry.stream != stream:
            reason = f"entry of stream {entry.stream!r}"
        elif entry.sequence != expected:
            reason = f"sequence {entry.sequence} where {expected} was expected"
        elif entry.previous_hash != head:
            reason = "previous hash does not match the entry before"
        elif entry.hash != entry.expected_hash():
            reason = "content does not match its hash"
        if reason is not None:
            return ChainReport(stream, count, head, broken_at=expected, reason=reason)
        head = entry.hash
        count += 1
    return ChainReport(stream, count, head)


@runtime_checkable
class AuditLog(Protocol):
    """A store of append-only, hash-chained streams."""

    async def append(
        self,
        stream: str,
        kind: str,
        payload: Mapping[str, JsonValue],
        *,
        owner_id: str | None = None,
    ) -> LogEntry:
        """Add an entry at the end of ``stream`` and return it."""
        ...

    async def read(self, stream: str, *, after: int = 0, limit: int = 1_000) -> list[LogEntry]:
        """Entries of ``stream`` with a sequence above ``after``, in order."""
        ...

    async def verify(self, stream: str) -> ChainReport:
        """Check the whole chain of ``stream``."""
        ...
