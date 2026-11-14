"""Record real provider responses as test cassettes (``just record-fixtures``).

Each cassette stores the exact requests an adapter sends for one request of the platform
(a :class:`~investinglab.ports.BarsRequest`, an
:class:`~investinglab.ports.EconomicRequest` or a :class:`~investinglab.ports.RatesRequest`)
and the responses the provider gave, so the tests replay *real* payloads with ``respx`` and
never touch the network. A cassette may record with smaller pages than the provider's
default, to exercise its pagination on a short excerpt; it says so (``page_size``).

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
from typing import TYPE_CHECKING, Any

import httpx

from investinglab.adapters.http import HttpClient, RetryPolicy
from investinglab.adapters.providers import (
    alternative_me,
    binance,
    coinbase,
    ecb,
    kraken,
    okx,
    yahoo,
)
from investinglab.config import LogLevel, configure_logging
from investinglab.domain.rate_series import RateKind
from investinglab.domain.time import Frequency
from investinglab.ports import BarsRequest, EconomicRequest, ProviderError, RatesRequest

if TYPE_CHECKING:
    from collections.abc import Callable

type Request = BarsRequest | EconomicRequest | RatesRequest
type Provider = (
    yahoo.YahooFinanceProvider
    | ecb.EcbProvider
    | binance.BinanceProvider
    | okx.OkxProvider
    | alternative_me.AlternativeMeProvider
    | kraken.KrakenProvider
    | coinbase.CoinbaseProvider
)

CASSETTES = Path(__file__).resolve().parents[1] / "packages/investinglab/tests/fixtures/cassettes"


def _transient(status: int) -> bool:
    """Statuses the HTTP client retries: the cassette keeps the final answer only."""
    return status in {408, 429} or status >= 500  # noqa: PLR2004


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
        if not _transient(response.status_code):  # the client retries those
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
    """One cassette: a name (``<provider>/<case>``), the request it answers and why it exists.

    ``page_size`` records with pages smaller than the provider's default (pagination tests).
    """

    name: str
    request: Request
    purpose: str
    page_size: int | None = None

    @property
    def provider(self) -> str:
        """Provider slug, the first part of the name."""
        return self.name.split("/", 1)[0]


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
        Recording(
            "ecb/eurusd_1d",
            BarsRequest("EURUSD=X", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Euro reference rate of the US dollar (also read inverted as USDEUR=X).",
        ),
        Recording(
            "ecb/gbpusd_1d",
            BarsRequest("GBPUSD=X", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Pair without the euro: ratio of two reference rates of the same day.",
        ),
        Recording(
            "ecb/eurusd_1d_millennium",
            BarsRequest("EURUSD=X", start=date(1999, 12, 27), end=date(2000, 1, 7)),
            "A TARGET holiday published as an empty value (31 December 1999).",
        ),
        Recording(
            "ecb/eurusd_weekend",
            BarsRequest("EURUSD=X", start=date(2026, 10, 3), end=date(2026, 10, 4)),
            "A range without fixings: the portal answers an empty body.",
        ),
        Recording(
            "ecb/estr_easter",
            EconomicRequest(ecb.ESTR, start=date(2026, 3, 30), end=date(2026, 4, 10)),
            "€STR around Easter 2026: published on the next TARGET business day.",
        ),
        Recording(
            "ecb/deposit_facility_cut",
            EconomicRequest(ecb.DEPOSIT_FACILITY, start=date(2025, 6, 6), end=date(2025, 6, 14)),
            "Deposit facility rate across the cut of 2025-06-11 (2.25 % to 2.00 %).",
        ),
        Recording(
            "binance/btc_usdt_1d",
            BarsRequest("BTC/USDT", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Spot pair quoted in USDT: UTC dates, OHLCV and the flow of each bar.",
        ),
        Recording(
            "binance/btc_usdt_1d_2025",
            BarsRequest("BTC/USDT", start=date(2025, 1, 1), end=date(2026, 1, 31)),
            "Thirteen months of daily bars: the input of the indicator parity tests.",
        ),
        Recording(
            "binance/btc_usdt_1d_paged",
            BarsRequest("BTC/USDT", start=date(2026, 10, 1), end=date(2026, 10, 10)),
            "Pagination: ten daily bars asked for in pages of four.",
            page_size=4,
        ),
        Recording(
            "binance/eth_btc_1h_live",
            BarsRequest("ETH/BTC", frequency=Frequency.HOUR_1, start=today - timedelta(days=1)),
            "Hourly bars of a pair quoted in bitcoin: the bar in progress is left out.",
        ),
        Recording(
            "binance/not_found",
            BarsRequest("NOPE/USDT", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Unknown pair: HTTP 400 with Binance's error code -1121.",
        ),
        Recording(
            "okx/btc_usdt_swap_funding",
            RatesRequest(
                "BTC/USDT:USDT", RateKind.FUNDING, start=date(2026, 10, 1), end=date(2026, 10, 10)
            ),
            "Linear perpetual swap: funding settled every 8 hours, sign as OKX reports it.",
        ),
        Recording(
            "okx/btc_usdt_swap_paged",
            RatesRequest(
                "BTC/USDT:USDT", RateKind.FUNDING, start=date(2026, 10, 1), end=date(2026, 10, 5)
            ),
            "Pagination: fifteen payments asked for in pages of six, newest first.",
            page_size=6,
        ),
        Recording(
            "kraken/btc_usd_1d",
            BarsRequest("BTC/USD", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Pair in US dollars, which Binance does not list: daily bars with trades and VWAP.",
        ),
        Recording(
            "kraken/eth_eur_4h_live",
            BarsRequest("ETH/EUR", frequency=Frequency.HOUR_4, start=today - timedelta(days=2)),
            "Native 4-hour bars of a pair in euros: the bar in progress is left out.",
        ),
        Recording(
            "kraken/not_found",
            BarsRequest("NOPE/USD", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Unknown pair: HTTP 200 with Kraken's error EQuery:Unknown asset pair.",
        ),
        Recording(
            "coinbase/btc_usd_1d",
            BarsRequest("BTC/USD", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Pair in US dollars: daily candles, newest first, low before high.",
        ),
        Recording(
            "coinbase/btc_usd_1d_paged",
            BarsRequest("BTC/USD", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Pagination: twenty daily candles asked for in windows of seven.",
            page_size=7,
        ),
        Recording(
            "coinbase/eth_eur_4h_live",
            BarsRequest("ETH/EUR", frequency=Frequency.HOUR_4, start=today - timedelta(days=1)),
            "4-hour bars built from hourly candles: only bins whose hours have all closed.",
        ),
        Recording(
            "coinbase/not_found",
            BarsRequest("NOPE/USD", start=date(2026, 10, 1), end=date(2026, 10, 20)),
            "Unknown pair: HTTP 404.",
        ),
        Recording(
            "alternative_me/fng_october",
            EconomicRequest(
                alternative_me.FEAR_GREED, start=date(2026, 10, 1), end=date(2026, 10, 20)
            ),
            "Crypto Fear & Greed Index: one reading a day, asked for since the first day.",
        ),
        Recording(
            "okx/not_found",
            RatesRequest(
                "NOPE/USDT:USDT", RateKind.FUNDING, start=date(2026, 10, 1), end=date(2026, 10, 2)
            ),
            "Unknown swap: HTTP 200 with OKX's error code 51001.",
        ),
    ]


def _provider(
    recording: Recording, transport: RecordingTransport, recorded_at: datetime
) -> Provider:
    retry = RetryPolicy(max_attempts=4, initial_backoff=2.0)

    def clock() -> datetime:
        return recorded_at

    factories: dict[str, Callable[[], Provider]] = {
        yahoo.NAME: lambda: yahoo.YahooFinanceProvider(
            client=HttpClient(
                yahoo.NAME,
                base_url=yahoo.BASE_URL,
                retry=retry,
                headers={"User-Agent": yahoo.USER_AGENT},
                transport=transport,
            ),
            clock=clock,
        ),
        ecb.NAME: lambda: ecb.EcbProvider(
            client=HttpClient(
                ecb.NAME, base_url=ecb.BASE_URL, timeout=90.0, retry=retry, transport=transport
            ),
            clock=clock,
        ),
        binance.NAME: lambda: binance.BinanceProvider(
            client=binance.http_client(retry=retry, transport=transport),
            clock=clock,
            page_size=recording.page_size or binance.PAGE_SIZE,
        ),
        kraken.NAME: lambda: kraken.KrakenProvider(
            client=kraken.http_client(retry=retry, transport=transport), clock=clock
        ),
        coinbase.NAME: lambda: coinbase.CoinbaseProvider(
            client=coinbase.http_client(retry=retry, transport=transport),
            clock=clock,
            page_size=recording.page_size or coinbase.PAGE_SIZE,
        ),
        okx.NAME: lambda: okx.OkxProvider(
            client=okx.http_client(retry=retry, transport=transport),
            clock=clock,
            page_size=recording.page_size or okx.PAGE_SIZE,
        ),
        alternative_me.NAME: lambda: alternative_me.AlternativeMeProvider(
            client=alternative_me.http_client(retry=retry, transport=transport), clock=clock
        ),
    }
    return factories[recording.provider]()


def _describe(request: Request) -> dict[str, str | None]:
    bounds = {
        "start": request.start.isoformat() if request.start else None,
        "end": request.end.isoformat() if request.end else None,
    }
    if isinstance(request, BarsRequest):
        return {"symbol": request.symbol, "frequency": request.frequency.value, **bounds}
    if isinstance(request, RatesRequest):
        return {
            "symbol": request.symbol,
            "kind": request.kind.value,
            "venue": request.venue,
            **bounds,
        }
    return {"series_id": request.series_id, "mode": request.mode.value, **bounds}


async def _outcome(provider: Provider, request: Request) -> str:
    """What the adapter made of the recorded responses, for the person recording."""
    if isinstance(request, BarsRequest) and isinstance(
        provider,
        yahoo.YahooFinanceProvider
        | ecb.EcbProvider
        | binance.BinanceProvider
        | kraken.KrakenProvider
        | coinbase.CoinbaseProvider,
    ):
        return f"{len(await provider.fetch_bars(request))} bars"
    if isinstance(request, RatesRequest) and isinstance(provider, okx.OkxProvider):
        return f"{len(await provider.fetch_rates(request))} payments"
    if isinstance(request, EconomicRequest) and isinstance(
        provider, ecb.EcbProvider | alternative_me.AlternativeMeProvider
    ):
        series = await provider.fetch_economic_series(request)
        return f"{len(series.observations)} observations"
    raise TypeError(f"{provider.name} does not serve {type(request).__name__}")


async def _record(recording: Recording, recorded_at: datetime) -> dict[str, Any]:
    transport = RecordingTransport()
    async with _provider(recording, transport, recorded_at) as provider:
        try:
            outcome = await _outcome(provider, recording.request)
        except ProviderError as error:
            outcome = f"{type(error).__name__}: {error}"
    cassette: dict[str, Any] = {
        "provider": recording.provider,
        "purpose": recording.purpose,
        "recorded_at": recorded_at.isoformat(timespec="seconds"),
        "request": _describe(recording.request),
    }
    if recording.page_size:
        cassette["page_size"] = recording.page_size
    return {**cassette, "outcome": outcome, "exchanges": transport.exchanges}


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
