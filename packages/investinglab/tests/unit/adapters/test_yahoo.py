"""Yahoo Finance adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded payload (a missing close, a ragged column,
an unknown venue...) to prove each rule; the altered values are never used as market data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.yahoo import USER_AGENT, YahooFinanceProvider
from investinglab.adapters.providers.yahoo.provider import EARLIEST, _windows
from investinglab.domain import AssetClass, Frequency, PriceAdjustment
from investinglab.ports import (
    BarsRequest,
    Dataset,
    MarketDataProvider,
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

    from investinglab.domain import PriceSeries


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _result(payload: Any) -> Any:
    return payload["chart"]["result"][0]


async def _fetch(
    cassette: Cassette,
    router: respx.MockRouter,
    request: BarsRequest | None = None,
    *,
    payload: Any = None,
    clock: datetime | None = None,
) -> PriceSeries:
    exact = request is None and payload is None and clock is None
    cassette.play(router, exact=exact, payload=payload)
    moment = clock or cassette.recorded_at
    async with YahooFinanceProvider(clock=lambda: moment) as yahoo:
        return await yahoo.fetch_bars(request or cassette.bars_request)


# ── Daily bars ───────────────────────────────────────────────────────


async def test_daily_bars_carry_madrid_sessions_and_adjusted_closes(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")

    series = await _fetch(cassette, router)

    recorded = _result(cassette.payload())
    assert series.symbol == "SAN.MC"
    assert series.frequency is Frequency.DAY_1
    assert len(series) == len(recorded["timestamp"]) == 22
    assert series.bars.index[0] == pd.Timestamp("2024-05-02")
    assert pd.DatetimeIndex(series.bars.index).tz is None
    assert series.bars["close"].tolist() == recorded["indicators"]["quote"][0]["close"]
    assert series.bars["adj_close"].tolist() == recorded["indicators"]["adjclose"][0]["adjclose"]
    assert (series.bars["adj_close"] < series.bars["close"]).all()  # dividends paid since
    assert series.adjustment is PriceAdjustment.SPLITS
    instrument = series.instrument
    assert (instrument.name, instrument.asset_class) == ("Banco Santander, S.A.", AssetClass.EQUITY)
    assert instrument.currency.code == "EUR"
    assert instrument.exchange is not None
    assert instrument.exchange.code == "XMAD"
    assert series.source.provider == "yahoo"
    assert series.source.dataset == "v8/finance/chart"
    assert series.source.retrieved_at == cassette.recorded_at


async def test_requests_identify_investinglab_and_encode_the_symbol(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/gspc_1d")
    (route,) = cassette.play(router)

    async with YahooFinanceProvider(clock=cassette.clock) as yahoo:
        await yahoo.fetch_bars(cassette.bars_request)

    request = route.calls.last.request
    assert request.url.raw_path.startswith(b"/v8/finance/chart/%5EGSPC?")
    assert request.headers["User-Agent"] == USER_AGENT
    assert "InvestingLab/" in USER_AGENT


async def test_prices_in_pence_are_scaled_to_pounds(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/vod_l_1d")

    series = await _fetch(cassette, router)

    recorded = _result(cassette.payload())
    pence = dict(
        zip(
            (datetime.fromtimestamp(stamp, UTC).date() for stamp in recorded["timestamp"]),
            recorded["indicators"]["quote"][0]["close"],
            strict=True,
        )
    )
    assert series.currency.code == "GBP"
    sessions = pd.DatetimeIndex(series.bars.index)
    for session, close in zip(sessions, series.bars["close"], strict=True):
        assert close == pytest.approx(pence[session.date()] / 100)
    assert series.instrument.exchange is not None
    assert series.instrument.exchange.code == "XLON"


async def test_currency_pairs_use_their_session_date_and_have_no_volume(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/eurusd_1d")

    series = await _fetch(cassette, router)

    london_midnight = datetime(2026, 9, 30, 23, tzinfo=UTC)
    assert int(london_midnight.timestamp()) in _result(cassette.payload())["timestamp"]
    assert series.bars.index[0] == pd.Timestamp("2026-10-01")  # that bar's London date
    assert "volume" not in series.bars.columns  # Yahoo reports 0 for every pair
    assert series.instrument.asset_class is AssetClass.FX
    assert series.instrument.exchange is not None
    assert series.instrument.exchange.code == "FX"


async def test_sydney_sessions_keep_their_local_date(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/bhp_ax_1d")

    series = await _fetch(cassette, router)

    # After the switch to daylight time, 10:00 in Sydney is 23:00 UTC of the previous day.
    assert pd.DatetimeIndex(series.bars.index).strftime("%m-%d").tolist() == [
        "10-01",
        "10-02",
        "10-05",
        "10-06",
        "10-07",
        "10-08",
        "10-09",
    ]
    assert series.currency.code == "AUD"


async def test_prices_are_split_adjusted(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/nvda_1d_split")

    series = await _fetch(cassette, router)

    closes = series.bars["close"]
    # The 10:1 split of 2024-06-10 does not show as a -90 % return.
    assert closes.pct_change().abs().max() < 0.1
    assert series.instrument.exchange is not None
    assert series.instrument.exchange.code == "XNAS"


async def test_monthly_bars_are_aggregated_from_daily_sessions(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/gspc_1d")
    cassette.play(router)
    monthly = BarsRequest(
        "^GSPC", frequency=Frequency.MONTH_1, start=date(2026, 1, 1), end=date(2026, 4, 30)
    )

    async with YahooFinanceProvider(clock=cassette.clock) as yahoo:
        daily = await yahoo.fetch_bars(cassette.bars_request)
        series = await yahoo.fetch_bars(monthly)

    assert series.frequency is Frequency.MONTH_1
    assert len(series) == 4
    daily_closes = daily.bars["close"]
    for label, close in zip(series.bars.index, series.bars["close"], strict=True):
        assert daily_closes[label] == close  # labelled by the last session
    assert series.instrument.asset_class is AssetClass.INDEX


async def test_a_coarse_series_with_too_few_periods_is_a_data_error(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/gspc_1d")
    yearly = BarsRequest(
        "^GSPC", frequency=Frequency.YEAR_1, start=date(2026, 1, 1), end=date(2026, 4, 30)
    )

    with pytest.raises(ProviderDataError, match=r"\^GSPC"):
        await _fetch(cassette, router, yearly)


# ── Finished bars only ───────────────────────────────────────────────


async def test_the_session_in_progress_is_left_out(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/btc_usd_1d_live")
    open_day = cassette.recorded_at.date()

    during = await _fetch(cassette, router)
    after = await _fetch(cassette, router, clock=cassette.recorded_at + timedelta(hours=6))

    assert during.end == pd.Timestamp(open_day - timedelta(days=1))
    assert after.end == pd.Timestamp(open_day)
    assert during.instrument.asset_class is AssetClass.CRYPTO


async def test_intraday_bars_drop_the_snapshot_and_the_bar_in_progress(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/san_mc_1h_live")
    closing_snapshot = pd.Timestamp("2026-11-09 16:30", tz="UTC")
    assert int(closing_snapshot.timestamp()) in _result(cassette.payload())["timestamp"]

    after_close = await _fetch(cassette, router)
    midday = await _fetch(cassette, router, clock=datetime(2026, 11, 9, 12, 30, tzinfo=UTC))

    assert str(pd.DatetimeIndex(after_close.bars.index).tz) == "UTC"
    assert closing_snapshot not in after_close.bars.index
    assert after_close.end == pd.Timestamp("2026-11-09 16:00", tz="UTC")
    assert after_close.bars.index.to_series().diff().min() == pd.Timedelta(hours=1)
    assert midday.end == pd.Timestamp("2026-11-09 11:00", tz="UTC")  # 12:00 is not closed
    assert "adj_close" not in after_close.bars.columns


async def test_intraday_requests_without_a_start_reach_back_to_the_lookback(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/san_mc_1h_live")
    everything = BarsRequest("SAN.MC", frequency=Frequency.HOUR_1)

    series = await _fetch(cassette, router, everything)

    assert len(series) == 27  # every closed bar on the grid, the snapshot left out


async def test_intraday_ranges_use_the_market_session_dates(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/san_mc_1h_live")
    one_day = BarsRequest(
        "SAN.MC", frequency=Frequency.HOUR_1, start=date(2026, 11, 6), end=date(2026, 11, 6)
    )

    series = await _fetch(cassette, router, one_day)

    assert series.start == pd.Timestamp("2026-11-06 08:00", tz="UTC")
    assert series.end == pd.Timestamp("2026-11-06 16:00", tz="UTC")


# ── Data that is never invented ──────────────────────────────────────


async def test_a_bar_without_a_close_is_an_absent_observation(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    payload = cassette.payload()
    _result(payload)["indicators"]["quote"][0]["close"][3] = None

    series = await _fetch(cassette, router, payload=payload)

    assert len(series) == 21
    assert pd.Timestamp("2024-05-07") not in series.bars.index
    assert {"open", "high", "low"} <= set(series.bars.columns)


async def test_incomplete_open_high_low_columns_are_left_out(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    payload = cassette.payload()
    _result(payload)["indicators"]["quote"][0]["open"][5] = None

    series = await _fetch(cassette, router, payload=payload)

    assert len(series) == 22  # every close is kept...
    assert list(series.bars.columns) == ["close", "adj_close", "volume"]  # ...nothing patched


async def test_bars_that_break_the_domain_rules_are_a_data_error(
    router: respx.MockRouter,
) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    payload = cassette.payload()
    _result(payload)["indicators"]["quote"][0]["volume"][0] = -1

    with pytest.raises(ProviderDataError, match="'volume' must be finite and non-negative"):
        await _fetch(cassette, router, payload=payload)


async def test_too_few_finished_bars_is_a_data_error(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    two_sessions = BarsRequest("SAN.MC", start=date(2024, 5, 30), end=date(2024, 5, 31))

    with pytest.raises(ProviderDataError, match="only 2 finished 1d bars"):
        await _fetch(cassette, router, two_sessions)


# ── Errors ───────────────────────────────────────────────────────────


async def test_an_unknown_symbol_is_not_found(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/not_found")

    with pytest.raises(SymbolNotFoundError, match="HTTP 404"):
        await _fetch(cassette, router)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ({"code": "Not Found", "description": "No data found"}, SymbolNotFoundError),
        ({"code": "Bad Request", "description": None}, ProviderDataError),
    ],
)
async def test_an_error_document_is_translated(
    router: respx.MockRouter, error: dict[str, Any], expected: type[Exception]
) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")

    with pytest.raises(expected, match=error["code"]):
        await _fetch(cassette, router, payload={"chart": {"result": None, "error": error}})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"chart": {"result": [], "error": None}}, "no chart"),
        ({"unexpected": True}, "unexpected chart payload"),
    ],
)
async def test_empty_or_malformed_payloads_are_rejected(
    router: respx.MockRouter, payload: Any, message: str
) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")

    with pytest.raises((SymbolNotFoundError, ProviderDataError), match=message):
        await _fetch(cassette, router, payload=payload)


async def test_columns_must_match_the_timestamps(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    payload = cassette.payload()
    _result(payload)["indicators"]["quote"][0]["close"].pop()

    with pytest.raises(ProviderDataError, match=r"columns \['close'\] do not match"):
        await _fetch(cassette, router, payload=payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("instrumentType", "OPTION", "'OPTION' is not supported"),
        ("currency", None, "does not say the quote currency"),
        ("currency", "EURO", "EURO"),
    ],
)
async def test_unsupported_metadata_is_rejected(
    router: respx.MockRouter, field: str, value: str | None, message: str
) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    payload = cassette.payload()
    _result(payload)["meta"][field] = value

    with pytest.raises(ProviderDataError, match=message):
        await _fetch(cassette, router, payload=payload)


async def test_an_unknown_venue_is_left_unknown(router: respx.MockRouter) -> None:
    cassette = load_cassette("yahoo/san_mc_1d")
    payload = cassette.payload()
    _result(payload)["meta"]["exchangeName"] = "XYZ"

    series = await _fetch(cassette, router, payload=payload)

    assert series.instrument.exchange is None
    assert series.bars.index[0] == pd.Timestamp("2024-05-02")  # dates still from Madrid


async def test_a_range_beyond_the_intraday_lookback_is_refused_without_a_request(
    router: respx.MockRouter,
) -> None:
    now = datetime(2026, 11, 9, 18, tzinfo=UTC)
    old = BarsRequest(
        "SAN.MC", frequency=Frequency.MINUTE_1, start=date(2026, 9, 1), end=date(2026, 9, 5)
    )

    async with YahooFinanceProvider(clock=lambda: now) as yahoo:
        with pytest.raises(UnsupportedRequestError, match="keeps 1m bars for 30 days"):
            await yahoo.fetch_bars(old)

    assert not router.calls


# ── Request windows and capabilities ─────────────────────────────────


def test_request_windows_pad_the_sessions_and_split_minute_ranges() -> None:
    now = datetime(2026, 11, 9, 18, tzinfo=UTC)
    day = 86_400

    (everything,) = _windows(BarsRequest("SAN.MC"), Frequency.DAY_1, now)
    (padded,) = _windows(
        BarsRequest("SAN.MC", start=date(2024, 5, 2), end=date(2024, 5, 31)), Frequency.DAY_1, now
    )
    minutes = _windows(
        BarsRequest("SAN.MC", frequency=Frequency.MINUTE_1, start=date(2026, 10, 28)),
        Frequency.MINUTE_1,
        now,
    )

    assert everything == (int(EARLIEST.timestamp()), int(now.timestamp()))
    assert padded == (
        int(datetime(2024, 5, 1, tzinfo=UTC).timestamp()),
        int(datetime(2024, 6, 2, tzinfo=UTC).timestamp()),
    )
    assert len(minutes) == 2
    assert all(last - first <= 7 * day for first, last in minutes)
    assert minutes[0][1] == minutes[1][0]
    assert minutes[-1][1] == int(now.timestamp())


def test_request_windows_respect_the_lookback() -> None:
    now = datetime(2026, 11, 9, 18, tzinfo=UTC)

    windows = _windows(
        BarsRequest("SAN.MC", frequency=Frequency.MINUTE_5, start=date(2026, 9, 11)),
        Frequency.MINUTE_5,
        now,
    )

    assert windows[0][0] == int((now - timedelta(days=60) + timedelta(hours=1)).timestamp())


def test_capabilities_describe_yahoo() -> None:
    today = date(2026, 11, 9)
    yahoo = YahooFinanceProvider()
    capabilities = yahoo.capabilities

    assert isinstance(yahoo, MarketDataProvider)
    assert yahoo.name == "yahoo"
    assert capabilities.datasets == frozenset({Dataset.BARS})
    assert capabilities.frequencies == frozenset(Frequency)
    assert not capabilities.requires_api_key
    assert capabilities.max_history[Frequency.MINUTE_1] == timedelta(days=29)
    assert Frequency.DAY_1 not in capabilities.max_history
    assert capabilities.can_serve_bars(BarsRequest("BTC-USD"), today)
    assert not capabilities.can_serve_bars(
        BarsRequest("SAN.MC", frequency=Frequency.MINUTE_1), today
    )
    assert not capabilities.can_serve_bars(BarsRequest("US10Y", asset_class=AssetClass.BOND), today)
