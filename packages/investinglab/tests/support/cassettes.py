"""Replay of recorded provider responses ("cassettes") with respx.

A cassette lives in ``tests/fixtures/cassettes/<provider>/<name>.json`` and is written by
``just record-fixtures`` (``scripts/record_fixtures.py``). It holds the REAL requests an
adapter sent for one platform request and the REAL responses the provider gave: short
excerpts kept to test the parsing rules, never synthetic prices.

Replaying matches every recorded exchange by URL and *exact* query parameters, so a change
in what the adapter sends fails the test instead of passing silently. Tests that move the
clock or the requested range use ``exact=False`` (URL only).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from investinglab.domain.time import Frequency
from investinglab.ports import BarsRequest

if TYPE_CHECKING:
    import respx

__all__ = ["CASSETTES", "Cassette", "Exchange", "load_cassette"]

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"


@dataclass(frozen=True, slots=True)
class Exchange:
    """One recorded HTTP request and its response."""

    url: str
    params: dict[str, str]
    status: int
    payload: Any = None
    text: str | None = None
    content_type: str = "application/json"

    def response(self, payload: Any = None) -> httpx.Response:
        """The recorded response, or one with the same status and another JSON body."""
        if payload is not None:
            return httpx.Response(self.status, json=payload)
        if self.text is not None:
            return httpx.Response(
                self.status, text=self.text, headers={"content-type": self.content_type}
            )
        return httpx.Response(self.status, json=self.payload)


@dataclass(frozen=True, slots=True)
class Cassette:
    """Recorded exchanges for one platform request."""

    name: str
    recorded_at: datetime
    request: BarsRequest
    exchanges: tuple[Exchange, ...]

    def clock(self) -> datetime:
        """The recording time: the adapter must judge which bars were finished then."""
        return self.recorded_at

    def payload(self, index: int = 0) -> Any:
        """A deep copy of a recorded JSON body, to alter in robustness tests."""
        return copy.deepcopy(self.exchanges[index].payload)

    def play(
        self, router: respx.MockRouter, *, exact: bool = True, payload: Any = None
    ) -> list[respx.Route]:
        """Register every exchange on ``router`` (optionally answering with ``payload``)."""
        routes = []
        for exchange in self.exchanges:
            route = (
                router.get(exchange.url, params__eq=exchange.params)
                if exact
                else router.get(exchange.url)
            )
            routes.append(route.mock(return_value=exchange.response(payload)))
        return routes


def _day(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


def load_cassette(name: str) -> Cassette:
    """Load ``fixtures/cassettes/<name>.json`` (``name`` like ``"yahoo/san_mc_1d"``)."""
    raw = json.loads((CASSETTES / f"{name}.json").read_text(encoding="utf-8"))
    request = raw["request"]
    return Cassette(
        name=name,
        recorded_at=datetime.fromisoformat(raw["recorded_at"]),
        request=BarsRequest(
            request["symbol"],
            frequency=Frequency(request["frequency"]),
            start=_day(request["start"]),
            end=_day(request["end"]),
        ),
        exchanges=tuple(
            Exchange(
                url=exchange["url"],
                params=exchange["params"],
                status=exchange["status"],
                payload=exchange.get("json"),
                text=exchange.get("text"),
                content_type=exchange.get("content_type", "application/json"),
            )
            for exchange in raw["exchanges"]
        ),
    )
