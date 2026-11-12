"""The audit log's hash chain: what it accepts and what it detects."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from investinglab.ports import (
    GENESIS_HASH,
    AuditLog,
    JsonValue,
    LogEntry,
    canonical_json,
    entry_hash,
    verify_chain,
)
from support.repositories import InMemoryAuditLog

MOMENT = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)


def chain(*payloads: dict[str, JsonValue], stream: str = "s") -> list[LogEntry]:
    entries: list[LogEntry] = []
    for offset, payload in enumerate(payloads):
        entries.append(
            LogEntry.chained(
                entries[-1] if entries else None,
                stream=stream,
                recorded_at=MOMENT + timedelta(seconds=offset),
                owner_id="ana",
                kind="test",
                payload=payload,
            )
        )
    return entries


def test_canonical_json_does_not_depend_on_key_order_or_spacing() -> None:
    assert (
        canonical_json({"b": [1, 2.5, None], "a": {"ñ": True}})
        == '{"a":{"ñ":true},"b":[1,2.5,null]}'
    )
    assert canonical_json({"x": 1, "y": 2}) == canonical_json({"y": 2, "x": 1})


@pytest.mark.parametrize(
    "payload",
    [{"x": float("nan")}, {"x": float("inf")}, {"x": {1: "a"}}, {"x": object()}, {"x": [b"raw"]}],
    ids=["nan", "infinity", "non-text-key", "object", "bytes"],
)
def test_payloads_that_are_not_plain_finite_json_are_refused(payload: dict[str, JsonValue]) -> None:
    with pytest.raises(ValueError, match="Audit payload"):
        canonical_json(payload)


def test_the_first_entry_chains_to_the_genesis_hash() -> None:
    (first,) = chain({"n": 1})

    assert (first.sequence, first.previous_hash) == (1, GENESIS_HASH)
    assert first.hash == first.expected_hash()
    assert first.details == {"n": 1}


def digest(
    *,
    stream: str = "s",
    kind: str = "k",
    owner_id: str | None = None,
    recorded_at: datetime = MOMENT,
) -> str:
    return entry_hash(
        previous_hash=GENESIS_HASH,
        stream=stream,
        sequence=1,
        recorded_at=recorded_at,
        owner_id=owner_id,
        kind=kind,
        payload="{}",
    )


def test_the_hash_is_the_same_instant_in_any_timezone() -> None:
    madrid = MOMENT.astimezone(timezone(timedelta(hours=1)))

    assert digest(recorded_at=madrid) == digest(recorded_at=MOMENT)
    assert digest(recorded_at=MOMENT + timedelta(microseconds=1)) != digest()


def test_fields_cannot_be_shifted_into_each_other() -> None:
    assert digest(stream="ab", kind="c") != digest(stream="a", kind="bc")
    assert digest(owner_id=None) != digest(owner_id="")


def test_entries_need_a_stream_a_kind_and_an_aware_instant() -> None:
    with pytest.raises(ValueError, match="stream and a kind"):
        LogEntry.chained(None, stream="", recorded_at=MOMENT, owner_id=None, kind="k", payload={})
    with pytest.raises(ValueError, match="timezone-aware"):
        LogEntry.chained(
            None,
            stream="s",
            recorded_at=MOMENT.replace(tzinfo=None),
            owner_id=None,
            kind="k",
            payload={},
        )


def test_an_intact_chain_verifies_and_reports_its_head() -> None:
    entries = chain({"n": 1}, {"n": 2}, {"n": 3})

    report = verify_chain("s", entries)

    assert report.intact
    assert (report.entries, report.head) == (3, entries[-1].hash)
    assert verify_chain("s", []).head == GENESIS_HASH


@pytest.mark.parametrize(
    ("tamper", "broken_at", "reason"),
    [
        (lambda e: [e[0], replace(e[1], payload='{"n":99}'), e[2]], 2, "content"),
        (lambda e: [e[0], replace(e[1], kind="other"), e[2]], 2, "content"),
        (lambda e: [e[0], replace(e[1], owner_id="eve"), e[2]], 2, "content"),
        (lambda e: [e[0], e[2]], 2, "sequence 3 where 2"),
        (lambda e: [e[1], e[0], e[2]], 1, "sequence 2 where 1"),
        (lambda e: [e[0], replace(e[1], stream="other"), e[2]], 2, "stream 'other'"),
        (lambda e: e[:1] + chain({"n": 1}, {"n": 7})[1:], 2, None),
    ],
    ids=["payload", "kind", "owner", "removed", "reordered", "foreign", "rebuilt-from-2"],
)
def test_tampering_is_located(tamper: object, broken_at: int, reason: str | None) -> None:
    entries = chain({"n": 1}, {"n": 2}, {"n": 3})
    tampered = tamper(entries)  # type: ignore[operator]

    report = verify_chain("s", tampered)

    if reason is None:  # a consistently rebuilt tail fits: only the head kept elsewhere tells
        assert report.intact
        assert report.head != entries[-1].hash
    else:
        assert (report.intact, report.broken_at) == (False, broken_at)
        assert reason in (report.reason or "")
        assert report.entries == broken_at - 1


@given(
    payloads=st.lists(
        st.dictionaries(st.text(max_size=5), st.integers() | st.text(max_size=8), max_size=3),
        min_size=2,
        max_size=6,
    ),
    data=st.data(),
)
def test_changing_any_entry_breaks_the_chain_at_that_entry(
    payloads: list[dict[str, JsonValue]], data: st.DataObject
) -> None:
    entries = chain(*payloads)
    position = data.draw(st.integers(min_value=0, max_value=len(entries) - 1))
    entries[position] = replace(entries[position], payload='{"tampered":true}')

    report = verify_chain("s", entries)

    assert report.broken_at == position + 1


async def test_the_in_memory_log_keeps_one_chain_per_stream() -> None:
    log = InMemoryAuditLog(clock=lambda: MOMENT)
    assert isinstance(log, AuditLog)

    await log.append("a", "x", {"n": 1}, owner_id="ana")
    await log.append("b", "x", {"n": 1})
    second = await log.append("a", "y", {"n": 2})

    assert second.sequence == 2
    assert [e.kind for e in await log.read("a")] == ["x", "y"]
    assert [e.sequence for e in await log.read("a", after=1)] == [2]
    assert len(await log.read("a", limit=1)) == 1
    assert (await log.verify("a")).entries == 2
    assert (await log.verify("missing")).intact
