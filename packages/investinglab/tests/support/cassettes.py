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

from investinglab.domain.rate_series import RateKind
from investinglab.domain.time import Frequency
from investinglab.ports import BarsRequest, EconomicRequest, RatesRequest, VintageMode

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

    def response(self, payload: Any = None, text: str | None = None) -> httpx.Response:
        """The recorded response, or one with the same status and another body."""
        if payload is not None:
            return httpx.Response(self.status, json=payload)
        body = text if text is not None else self.text
        if body is not None:
            return httpx.Response(
                self.status, text=body, headers={"content-type": self.content_type}
            )
        return httpx.Response(self.status, json=self.payload)


@dataclass(frozen=True, slots=True)
class Cassette:
    """Recorded exchanges for one platform request."""

    name: str
    recorded_at: datetime
    request: BarsRequest | EconomicRequest | RatesRequest
    exchanges: tuple[Exchange, ...]
    page_size: int | None = None
    """Page size the cassette was recorded with, when smaller than the provider's default."""

    @property
    def bars_request(self) -> BarsRequest:
        """The recorded request, which must be one for price bars."""
        assert isinstance(self.request, BarsRequest), f"{self.name} records an economic request"
        return self.request

    @property
    def economic_request(self) -> EconomicRequest:
        """The recorded request, which must be one for an economic series."""
        assert isinstance(self.request, EconomicRequest), f"{self.name} records no economic series"
        return self.request

    @property
    def rates_request(self) -> RatesRequest:
        """The recorded request, which must be one for holding rates."""
        assert isinstance(self.request, RatesRequest), f"{self.name} records no holding rates"
        return self.request

    def clock(self) -> datetime:
        """The recording time: the adapter must judge which bars were finished then."""
        return self.recorded_at

    def payload(self, index: int = 0) -> Any:
        """A deep copy of a recorded JSON body, to alter in robustness tests."""
        return copy.deepcopy(self.exchanges[index].payload)

    def text(self, index: int = 0) -> str:
        """A recorded text body (CSV, XML...), to alter in robustness tests."""
        body = self.exchanges[index].text
        assert body is not None, f"{self.name} exchange {index} has no text body"
        return body

    def play(
        self,
        router: respx.MockRouter,
        *,
        exact: bool = True,
        payload: Any = None,
        text: str | None = None,
    ) -> list[respx.Route]:
        """Register every exchange on ``router``, optionally answering another body."""
        routes = []
        for exchange in self.exchanges:
            route = (
                router.get(exchange.url, params__eq=exchange.params)
                if exact
                else router.get(exchange.url)
            )
            routes.append(route.mock(return_value=exchange.response(payload, text)))
        return routes


def _day(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


def _request(raw: dict[str, Any]) -> BarsRequest | EconomicRequest | RatesRequest:
    start, end = _day(raw["start"]), _day(raw["end"])
    if "series_id" in raw:
        return EconomicRequest(
            raw["series_id"], start=start, end=end, mode=VintageMode(raw["mode"])
        )
    if "kind" in raw:
        return RatesRequest(
            raw["symbol"], RateKind(raw["kind"]), venue=raw["venue"], start=start, end=end
        )
    return BarsRequest(raw["symbol"], frequency=Frequency(raw["frequency"]), start=start, end=end)


def load_cassette(name: str) -> Cassette:
    """Load ``fixtures/cassettes/<name>.json`` (``name`` like ``"yahoo/san_mc_1d"``)."""
    raw = json.loads((CASSETTES / f"{name}.json").read_text(encoding="utf-8"))
    return Cassette(
        name=name,
        recorded_at=datetime.fromisoformat(raw["recorded_at"]),
        request=_request(raw["request"]),
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
        page_size=raw.get("page_size"),
    )
