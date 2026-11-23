from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from investinglab.domain import DomainError, SourceHeartbeat, SourceStatus

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
LATEST = datetime(2026, 11, 22, tzinfo=UTC)


def _ok(at: datetime = NOW, provider: str = "yahoo") -> SourceHeartbeat:
    return SourceHeartbeat(provider, at, ok=True, latency=0.4, latest=LATEST)


def _failed(at: datetime = NOW, provider: str = "yahoo") -> SourceHeartbeat:
    return SourceHeartbeat(provider, at, ok=False, latency=30.0, error="TimeoutError")


def test_a_heartbeat_says_how_old_its_latest_observation_is() -> None:
    heartbeat = _ok()

    assert heartbeat.age(NOW) == timedelta(hours=36)
    assert heartbeat.age(LATEST - timedelta(hours=1)) == timedelta(0)  # never negative
    assert _failed().age(NOW) is None


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"provider": " "}, "names its source"),
        ({"checked_at": datetime(2026, 11, 23)}, "instant of a heartbeat needs a timezone"),  # noqa: DTZ001
        ({"latest": datetime(2026, 11, 22)}, "latest observation of a heartbeat"),  # noqa: DTZ001
        ({"latency": -0.1}, "zero or more seconds"),
        ({"latency": float("nan")}, "zero or more seconds"),
        ({"error": "boom"}, "error exactly when"),
        ({"ok": False}, "error exactly when"),
        ({"ok": False, "error": "boom"}, "no latest observation"),
    ],
)
def test_a_heartbeat_is_validated(fields: dict[str, object], message: str) -> None:
    arguments: dict[str, object] = {
        "provider": "yahoo",
        "checked_at": NOW,
        "ok": True,
        "latency": 0.4,
        "latest": LATEST,
        "error": None,
    } | fields

    with pytest.raises(DomainError, match=message):
        SourceHeartbeat(**arguments)  # type: ignore[arg-type]


def test_the_first_check_starts_the_history() -> None:
    answered = SourceStatus.first(_ok())
    failed = SourceStatus.first(_failed())

    assert (answered.provider, answered.last_ok_at, answered.failures) == ("yahoo", NOW, 0)
    assert (failed.last_ok_at, failed.failures) == (None, 1)


def test_failures_add_up_until_the_source_answers_again() -> None:
    later = [NOW + timedelta(minutes=15 * step) for step in range(1, 4)]
    status = SourceStatus.first(_ok())

    status = status.after(_failed(later[0])).after(_failed(later[1]))

    assert (status.heartbeat.checked_at, status.last_ok_at, status.failures) == (later[1], NOW, 2)
    status = status.after(_ok(later[2]))
    assert (status.last_ok_at, status.failures) == (later[2], 0)


def test_a_status_only_follows_its_own_source() -> None:
    with pytest.raises(DomainError, match="not yahoo's"):
        SourceStatus.first(_ok()).after(_ok(provider="ecb"))


@pytest.mark.parametrize(
    ("heartbeat", "last_ok_at", "failures", "message"),
    [
        (_failed(), datetime(2026, 11, 1), 1, "last answer of a heartbeat"),  # noqa: DTZ001
        (_failed(), None, -1, "cannot be negative"),
        (_ok(), NOW, 1, "has no failures"),
        (_ok(), NOW - timedelta(minutes=15), 0, "answered then"),
    ],
)
def test_a_status_is_validated(
    heartbeat: SourceHeartbeat, last_ok_at: datetime | None, failures: int, message: str
) -> None:
    with pytest.raises(DomainError, match=message):
        SourceStatus(heartbeat, last_ok_at, failures)
