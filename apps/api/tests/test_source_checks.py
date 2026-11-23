"""The worker's check of the data sources (ADR-0047): what it keeps and what it logs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from investinglab.ports import Canary, Dataset, RateLimitedError
from investinglab.toolkit import AsyncToolkit
from investinglab_api import worker
from investinglab_api.jobs import sources
from investinglab_api.jobs.sources import SOURCES_CRON, check_and_record
from investinglab_api.persistence import queue_app
from investinglab_api.settings import ApiSettings
from support.factories import make_series
from support.fakes import BARS_CAPABILITIES, FakeBarsProvider
from support.repositories import InMemoryHeartbeatStore, InMemoryJobRepository

if TYPE_CHECKING:
    from investinglab.config import Settings

CANARY = replace(BARS_CAPABILITIES, canary=Canary(Dataset.BARS, "SPY"))


class _Log:
    """Records what is logged, by level."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append(("warning", event, fields))


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> _Log:
    recorder = _Log()
    monkeypatch.setattr(sources, "log", recorder)
    return recorder


@pytest.fixture
def checked(core_settings: Settings) -> AsyncToolkit:
    """A toolkit over one source that answers, one that fails and one without a canary."""
    series = {"SPY": make_series(symbol="SPY")}
    up = FakeBarsProvider("up", series, capabilities=CANARY)
    down = FakeBarsProvider(
        "down", errors={"SPY": RateLimitedError("down", "HTTP 429")}, capabilities=CANARY
    )
    files = FakeBarsProvider("files", series)
    return AsyncToolkit.from_settings(core_settings, providers=[up, down, files], cache=False)


async def test_each_check_is_kept_and_logged(checked: AsyncToolkit, log: _Log) -> None:
    store = InMemoryHeartbeatStore()

    await check_and_record(checked, store)
    statuses = await check_and_record(checked, store)

    assert [(s.provider, s.heartbeat.ok, s.failures) for s in statuses] == [
        ("up", True, 0),
        ("down", False, 2),
    ]
    assert await store.statuses() == tuple(sorted(statuses, key=lambda s: s.provider))
    levels = [(level, event, fields.get("provider")) for level, event, fields in log.events]
    assert (
        levels
        == [
            ("info", "source_ok", "up"),
            ("warning", "source_failing", "down"),
        ]
        * 2
    )
    failing = log.events[-1][2]
    assert failing["failures"] == 2
    assert str(failing["error"]).startswith("RateLimitedError")
    assert log.events[0][2]["latest"] == "2024-01-08T00:00:00+00:00"


async def test_the_worker_checks_the_sources_given_where_to_keep_them(
    checked: AsyncToolkit, log: _Log
) -> None:
    store = InMemoryHeartbeatStore()
    url = "postgresql+psycopg://nobody@localhost:1/none"  # never opened
    jobs, settings = InMemoryJobRepository(), ApiSettings()
    plain = worker.register(queue_app(url), jobs, toolkit=checked, settings=settings)
    app = worker.register(
        queue_app(url), jobs, toolkit=checked, settings=settings, heartbeats=store
    )

    assert worker.CHECK_SOURCES not in plain.tasks
    periodic = {task.task.name: task.cron for task in app.periodic_registry.periodic_tasks.values()}
    assert periodic == {worker.RETRY_STALLED: "* * * * *", worker.CHECK_SOURCES: SOURCES_CRON}
    assert app.tasks[worker.CHECK_SOURCES].queue == worker.MAINTENANCE
    await app.tasks[worker.CHECK_SOURCES].func(timestamp=0)
    assert [status.provider for status in await store.statuses()] == ["down", "up"]
    assert len(log.events) == 2
