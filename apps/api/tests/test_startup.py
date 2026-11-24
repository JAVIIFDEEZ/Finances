"""How the API and the worker start: the event loop they run on and what they say if they cannot.

psycopg's asynchronous mode refuses Windows' default ``ProactorEventLoop``; on Windows both
processes run on a ``SelectorEventLoop``. The Windows job of the CI runs this file there.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import psycopg
import pytest
import uvicorn

from investinglab_api import __main__ as entry
from investinglab_api import loops
from investinglab_api.settings import get_api_settings


@pytest.mark.parametrize(
    ("platform", "factory", "uvicorn_loop"),
    [
        ("win32", loops.selector_loop, loops.UVICORN_SELECTOR),
        ("linux", None, "auto"),
        ("darwin", None, "auto"),
    ],
)
def test_only_windows_gets_a_selector_loop(
    platform: str, factory: object, uvicorn_loop: str
) -> None:
    assert loops.loop_factory(platform) is factory
    assert loops.uvicorn_loop(platform) == uvicorn_loop


def test_the_selector_loop_is_one_uvicorn_can_load() -> None:
    config = uvicorn.Config("investinglab_api.app:create_app", loop=loops.UVICORN_SELECTOR)

    factory = config.get_loop_factory()

    assert factory is loops.selector_loop
    loop = factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_psycopg_reaches_the_network_on_this_platforms_loop() -> None:
    """On Windows' default loop psycopg refuses to start (``InterfaceError``); here it tries."""

    async def connect() -> None:
        await psycopg.AsyncConnection.connect(
            "postgresql://nobody@127.0.0.1:1/none", connect_timeout=2
        )

    with pytest.raises(psycopg.OperationalError) as refused:
        asyncio.run(connect(), loop_factory=loops.loop_factory())

    assert not isinstance(refused.value, psycopg.InterfaceError)


def test_the_worker_runs_on_the_selector_loop_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used: dict[str, Any] = {}

    def run(main: Any, **options: Any) -> None:
        used.update(options)
        main.close()  # never awaited: it only had to be built

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(asyncio, "run", run)

    assert entry.main(["worker"]) == 0
    assert used == {"loop_factory": loops.selector_loop}


def test_the_api_runs_on_the_selector_loop_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    used: dict[str, Any] = {}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(uvicorn, "run", lambda *_, **options: used.update(options))
    get_api_settings.cache_clear()

    assert entry.main([]) == 0
    assert used["loop"] == loops.UVICORN_SELECTOR
