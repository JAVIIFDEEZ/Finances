"""Record real provider responses as test cassettes (``just record-fixtures``).

Each cassette stores the exact requests an adapter sends for one request of the platform
(a :class:`~investinglab.ports.BarsRequest`) and the responses the provider gave, so the
tests replay *real* payloads with ``respx`` and never touch the network.

The ranges are short excerpts, just long enough to exercise every parsing rule (session
dates, minor currency units, splits, unfinished bars...): they are test fixtures, not a
dataset. Re-record when a provider changes its format and review the diff before
committing. Cassettes whose range is relative to the recording day (the intraday ones, the
unfinished crypto session) are only valid with the clock frozen at ``recorded_at``, which
the test helpers do.

Usage::

    uv run python scripts/record_fixtures.py            # every cassette
    uv run python scripts/record_fixtures.py yahoo/btc  # only names containing the text
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from investinglab.adapters.http import HttpClient, RetryPolicy
from investinglab.adapters.providers.yahoo import BASE_URL, NAME, USER_AGENT, YahooFinanceProvider
from investinglab.config import LogLevel, configure_logging
from investinglab.domain.time import Frequency
from investinglab.ports import BarsRequest, ProviderError

CASSETTES = Path(__file__).resolve().parents[1] / "packages/investinglab/tests/fixtures/cassettes"


class RecordingTransport(httpx.AsyncBaseTransport):
    """Transport that forwards every request and keeps a copy of the final exchanges.

    It forwards through a plain ``httpx.AsyncClient``, which honours the environment's proxy
    and certificate settings (a bare transport would ignore them).
    """

    def __init__(self) -> None:
        self._inner = httpx.AsyncClient(follow_redirects=False)
        self.exchanges: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send ``request`` for real and keep a copy of the exchange."""
        response = await self._inner.send(request)
        body = response.content
        if response.status_code != httpx.codes.TOO_MANY_REQUESTS:  # retried by the client
            content_type = response.headers.get("content-type", "")
            exchange: dict[str, Any] = {
                "method": request.method,
                "url": str(request.url.copy_with(query=None)),
                "params": dict(request.url.params),
                "status": response.status_code,
                "content_type": content_type.split(";")[0],
            }
            if "json" in content_type:
                exchange["json"] = json.loads(body)
            else:
                exchange["text"] = body.decode(response.encoding or "utf-8")
            self.exchanges.append(exchange)
        # The body is already decompressed: drop the headers that describe the wire format.
        headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
        }
        return httpx.Response(response.status_code, headers=headers, content=body, request=request)

    async def aclose(self) -> None:
        """Close the forwarding client."""
        await self._inner.aclose()


@dataclass(frozen=True)
class Recording:
    """One cassette: a name, the request it answers and why it exists."""

    name: str
    request: BarsRequest
    purpose: str


def _recordings(today: date) -> list[Recording]:
    return [
        Recording(
            "yahoo/san_mc_1d",
            BarsRequest("SAN.MC", start=date(2024, 5, 2), end=date(2024, 5, 31)),
            "Madrid equity in EUR: session dates, split-adjusted OHLC and adjusted close.",
        ),
        Recording(
            "yahoo/vod_l_1d",
            BarsRequest("VOD.L", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "London equity quoted in pence (GBp): prices scaled to GBP.",
        ),
        Recording(
            "yahoo/eurusd_1d",
            BarsRequest("EURUSD=X", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Currency pair: London-midnight bars, volume reported as 0.",
        ),
        Recording(
            "yahoo/bhp_ax_1d",
            BarsRequest("BHP.AX", start=date(2026, 10, 1), end=date(2026, 10, 9)),
            "Sydney equity: sessions open on the previous UTC day.",
        ),
        Recording(
            "yahoo/nvda_1d_split",
            BarsRequest("NVDA", start=date(2024, 6, 3), end=date(2024, 6, 14)),
            "Nasdaq equity across its 10:1 split of 2024-06-10.",
        ),
        Recording(
            "yahoo/gspc_1d",
            BarsRequest("^GSPC", start=date(2026, 1, 1), end=date(2026, 4, 30)),
            "Index with a caret symbol; aggregated to monthly bars in the tests.",
        ),
        Recording(
            "yahoo/btc_usd_1d_live",
            BarsRequest("BTC-USD", start=today - timedelta(days=6)),
            "24/7 crypto-asset: today's session is still open at recording time.",
        ),
        Recording(
            "yahoo/san_mc_1h_live",
            BarsRequest("SAN.MC", frequency=Frequency.HOUR_1, start=today - timedelta(days=3)),
            "Hourly bars, with the off-grid snapshot bar Yahoo appends.",
        ),
        Recording(
            "yahoo/not_found",
            BarsRequest("NOPE.XX", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Unknown symbol (HTTP 404 with an error document).",
        ),
    ]


async def _record(recording: Recording, recorded_at: datetime) -> dict[str, Any]:
    transport = RecordingTransport()
    client = HttpClient(
        NAME,
        base_url=BASE_URL,
        retry=RetryPolicy(max_attempts=4, initial_backoff=2.0),
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    )
    async with YahooFinanceProvider(client=client, clock=lambda: recorded_at) as provider:
        try:
            series = await provider.fetch_bars(recording.request)
            outcome = f"{len(series)} bars"
        except ProviderError as error:
            outcome = f"{type(error).__name__}: {error}"
    request = recording.request
    return {
        "provider": NAME,
        "purpose": recording.purpose,
        "recorded_at": recorded_at.isoformat(timespec="seconds"),
        "request": {
            "symbol": request.symbol,
            "frequency": request.frequency.value,
            "start": request.start.isoformat() if request.start else None,
            "end": request.end.isoformat() if request.end else None,
        },
        "outcome": outcome,
        "exchanges": transport.exchanges,
    }


async def main(selection: str | None) -> int:
    """Record the selected cassettes and return the process exit code."""
    configure_logging(LogLevel.WARNING)
    recorded_at = datetime.now(UTC).replace(microsecond=0)
    chosen = [r for r in _recordings(recorded_at.date()) if not selection or selection in r.name]
    if not chosen:
        print(f"No cassette matches {selection!r}", file=sys.stderr)  # noqa: T201
        return 1
    for recording in chosen:
        cassette = await _record(recording, recorded_at)
        path = CASSETTES / f"{recording.name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cassette, indent=1, ensure_ascii=False) + "\n", "utf-8")
        print(f"{recording.name}: {cassette['outcome']}")  # noqa: T201
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("only", nargs="?", help="record only the cassettes whose name has it")
    sys.exit(asyncio.run(main(parser.parse_args().only)))
