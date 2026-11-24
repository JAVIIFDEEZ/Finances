"""The event loop the API and the worker run on: a selector loop on Windows.

psycopg's asynchronous connections (SQLAlchemy's and those of Procrastinate's queue) cannot run
on the ``ProactorEventLoop`` that Python uses by default on Windows: psycopg refuses it, so
every database call fails there. On Windows, then, the API and the worker run on a
``SelectorEventLoop``; elsewhere nothing changes (uvicorn keeps uvloop where it is installed).

uvicorn happened to pick a selector loop only when it reloads (its server then runs in a
subprocess), so ``just dev`` worked while the worker and ``just preview`` did not.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["UVICORN_SELECTOR", "loop_factory", "needs_selector", "selector_loop", "uvicorn_loop"]

UVICORN_SELECTOR: Final = "investinglab_api.loops:selector_loop"
"""uvicorn's ``loop`` option for :func:`selector_loop`."""


def needs_selector(platform: str | None = None) -> bool:
    """Whether ``platform`` (this one by default) needs a selector loop for psycopg."""
    return (platform or sys.platform) == "win32"


def selector_loop() -> asyncio.AbstractEventLoop:
    """A new selector event loop: what psycopg's asynchronous mode needs on Windows."""
    return asyncio.SelectorEventLoop()


def loop_factory(platform: str | None = None) -> Callable[[], asyncio.AbstractEventLoop] | None:
    """``asyncio.run``'s ``loop_factory``: a selector loop on Windows, the default elsewhere."""
    return selector_loop if needs_selector(platform) else None


def uvicorn_loop(platform: str | None = None) -> str:
    """Uvicorn's ``loop``: the selector loop on Windows, uvicorn's own choice elsewhere."""
    return UVICORN_SELECTOR if needs_selector(platform) else "auto"
