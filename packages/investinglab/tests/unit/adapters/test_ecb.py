"""ECB adapter, replayed from real recorded responses (``support.cassettes``).

The robustness tests alter a *copy* of a recorded CSV to prove each rule; the altered values
are never used as market data.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pytest
import respx

from investinglab.adapters.providers.ecb import (
    CATALOGUE,
    DEPOSIT_FACILITY,
    ESTR,
    EcbProvider,
    Publication,
)
from investinglab.adapters.providers.ecb.calendar import next_target_days
from investinglab.domain import AssetClass, EconomicSeries, Frequency, PriceAdjustment
from investinglab.ports import (
    BarsRequest,
    Dataset,
    EconomicDataProvider,
    EconomicRequest,
    MarketDataProvider,
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from support.cassettes import Cassette, load_cassette

if TYPE_CHECKING:
    from collections.abc import Iterator

    from investinglab.domain import PriceSeries

NOW = datetime(2026, 11, 9, 19, tzinfo=UTC)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _recorded(cassette: Cassette, index: int = 0) -> dict[str, float]:
    """The values of a recorded CSV body, by observation date."""
    rows = csv.DictReader(io.StringIO(cassette.text(index)))
    return {row["TIME_PERIOD"]: float(row["OBS_VALUE"]) for row in rows if row["OBS_VALUE"]}


async def _bars(
    cassette: Cassette,
    router: respx.MockRouter,
    request: BarsRequest | None = None,
    *,
    text: str | None = None,
) -> PriceSeries:
    cassette.play(router, text=text)
    async with EcbProvider(clock=cassette.clock) as ecb:
        return await ecb.fetch_bars(request or cassette.bars_request)


async def _economic(cassette: Cassette, router: respx.MockRouter) -> EconomicSeries:
    cassette.play(router)
    async with EcbProvider(clock=cassette.clock) as ecb:
        return await ecb.fetch_economic_series(cassette.economic_request)


# ── Reference rates as bars ──────────────────────────────────────────


async def test_euro_pairs_are_the_reference_rates(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_1d")

    series = await _bars(cassette, router)

    recorded = _recorded(cassette)
    assert list(series.bars.columns) == ["close"]
    assert series.bars["close"].tolist() == list(recorded.values())
    assert series.bars.index[0] == pd.Timestamp("2026-10-01")
    instrument = series.instrument
    assert (instrument.asset_class, instrument.currency.code) == (AssetClass.FX, "USD")
    assert instrument.exchange is not None
    assert instrument.exchange.code == "FX"
    assert instrument.name == "EUR/USD ECB reference rate"
    assert series.adjustment is PriceAdjustment.RAW
    assert (series.source.provider, series.source.dataset) == ("ecb", "EXR")
    assert series.source.retrieved_at == cassette.recorded_at


async def test_pairs_quoted_in_euros_are_the_inverse(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_1d")
    inverse = BarsRequest("USDEUR=X", start=date(2026, 10, 1), end=date(2026, 10, 20))

    series = await _bars(cassette, router, inverse)

    recorded = _recorded(cassette)
    assert series.currency.code == "EUR"
    assert series.bars["close"].tolist() == pytest.approx([1 / v for v in recorded.values()])


async def test_pairs_without_the_euro_are_same_day_ratios(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/gbpusd_1d")

    series = await _bars(cassette, router)

    by_url = {
        exchange.url.rsplit("/", 1)[1]: index for index, exchange in enumerate(cassette.exchanges)
    }
    dollars = _recorded(cassette, by_url["D.USD.EUR.SP00.A"])
    pounds = _recorded(cassette, by_url["D.GBP.EUR.SP00.A"])
    expected = [dollars[day] / pounds[day] for day in sorted(dollars)]
    assert series.bars["close"].tolist() == pytest.approx(expected)
    assert series.currency.code == "USD"
    assert series.instrument.name == "GBP/USD ECB reference rates (cross via EUR)"


async def test_holidays_are_absent_not_filled(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_1d_millennium")
    assert ",,H," in cassette.text()  # 31 December 1999 is published without a value

    series = await _bars(cassette, router)

    assert len(series) == 9
    assert pd.Timestamp("1999-12-31") not in series.bars.index


async def test_a_range_without_fixings_is_a_data_error(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_weekend")

    with pytest.raises(ProviderDataError, match="no published values"):
        await _bars(cassette, router)


async def test_a_range_of_holidays_only_is_a_data_error(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_1d_millennium")
    header, *rows = cassette.text().splitlines()
    holidays = [row for row in rows if ",,H," in row]

    with pytest.raises(ProviderDataError, match="no published values"):
        await _bars(cassette, router, text="\n".join([header, *holidays]))


async def test_coarser_bars_are_aggregated_from_the_fixings(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_1d")
    weekly = BarsRequest(
        "EURUSD=X", frequency=Frequency.WEEK_1, start=date(2026, 10, 1), end=date(2026, 10, 20)
    )

    series = await _bars(cassette, router, weekly)

    recorded = _recorded(cassette)
    assert series.frequency is Frequency.WEEK_1
    assert series.bars.index[0] == pd.Timestamp("2026-10-02")  # the week's last fixing
    assert series.bars["close"].iloc[0] == recorded["2026-10-02"]


# ── Economic series ──────────────────────────────────────────────────


async def test_estr_is_known_from_the_next_target_day(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/estr_easter")

    series = await _economic(cassette, router)

    published = series.observations.set_index("observation_date")["published_at"]
    assert published[pd.Timestamp("2026-03-30")] == pd.Timestamp("2026-03-31")
    # Thursday before Easter: Good Friday and Easter Monday are TARGET holidays.
    assert published[pd.Timestamp("2026-04-02")] == pd.Timestamp("2026-04-07")
    assert published[pd.Timestamp("2026-04-10")] == pd.Timestamp("2026-04-13")  # weekend
    assert series.first_release().tolist() == list(_recorded(cassette).values())
    assert (series.series_id, series.frequency) == (ESTR, Frequency.DAY_1)
    assert "Percent" in series.units
    assert (series.source.provider, series.source.dataset) == ("ecb", "EST")


async def test_policy_rates_are_known_on_their_date(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/deposit_facility_cut")

    series = await _economic(cassette, router)

    observations = series.observations
    assert (observations["published_at"] == observations["observation_date"]).all()
    rates = series.first_release()
    assert rates[pd.Timestamp("2025-06-10")] == 2.25
    assert rates[pd.Timestamp("2025-06-11")] == 2.0
    assert series.title == "ECB deposit facility rate"
    assert CATALOGUE[DEPOSIT_FACILITY].publication is Publication.SAME_DAY


# ── Refusals and malformed documents ─────────────────────────────────


@pytest.mark.parametrize("symbol", ["SAN.MC", "EUREUR=X", "EURARS=X", "EURUSD"])
async def test_other_symbols_are_refused_without_a_request(
    router: respx.MockRouter, symbol: str
) -> None:
    async with EcbProvider(clock=lambda: NOW) as ecb:
        with pytest.raises(SymbolNotFoundError, match="ECB reference currencies"):
            await ecb.fetch_bars(BarsRequest(symbol))
        assert not ecb.capabilities.serves(symbol)

    assert not router.calls


async def test_series_outside_the_catalogue_are_refused(router: respx.MockRouter) -> None:
    async with EcbProvider(clock=lambda: NOW) as ecb:
        with pytest.raises(SymbolNotFoundError, match="is not served"):
            await ecb.fetch_economic_series(EconomicRequest("DGS3MO"))

    assert not router.calls


async def test_intraday_bars_are_not_served(router: respx.MockRouter) -> None:
    async with EcbProvider(clock=lambda: NOW) as ecb:
        with pytest.raises(UnsupportedRequestError, match="reference rates are daily"):
            await ecb.fetch_bars(BarsRequest("EURUSD=X", frequency=Frequency.HOUR_1))

    assert not router.calls


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("OBS_VALUE", "VALUE", r"CSV without columns \['OBS_VALUE'\]"),
        ("EXR.D.USD.EUR.SP00.A", "EXR.D.JPY.EUR.SP00.A", "unexpected series"),
        ("2026-10-01", "2026-10", "not daily dates"),
        ("2026-10-02", "2026-10-01", "repeated observation dates"),
        ("1.1298", "-1.1298", "non-positive prices"),
    ],
)
async def test_malformed_documents_are_data_errors(
    router: respx.MockRouter, old: str, new: str, message: str
) -> None:
    cassette = load_cassette("ecb/eurusd_1d")

    with pytest.raises(ProviderDataError, match=message):
        await _bars(cassette, router, text=cassette.text().replace(old, new))


async def test_unreadable_documents_are_data_errors(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/eurusd_1d")

    with pytest.raises(ProviderDataError, match="unreadable CSV"):
        await _bars(cassette, router, text='KEY,TIME_PERIOD\n"unterminated')


async def test_economic_values_must_be_finite(router: respx.MockRouter) -> None:
    cassette = load_cassette("ecb/estr_easter")
    cassette.play(router, text=cassette.text().replace("1.931", "inf", 1))

    async with EcbProvider(clock=cassette.clock) as ecb:
        with pytest.raises(ProviderDataError, match="non-finite"):
            await ecb.fetch_economic_series(cassette.economic_request)


# ── Capabilities and calendar ────────────────────────────────────────


def test_capabilities_describe_the_ecb() -> None:
    ecb = EcbProvider()
    capabilities = ecb.capabilities

    assert isinstance(ecb, MarketDataProvider)
    assert isinstance(ecb, EconomicDataProvider)
    assert ecb.name == "ecb"
    assert capabilities.datasets == frozenset({Dataset.BARS, Dataset.ECONOMIC})
    assert capabilities.asset_classes == frozenset({AssetClass.FX})
    assert Frequency.HOUR_1 not in capabilities.frequencies
    assert not capabilities.requires_api_key
    for identifier in ("EURUSD=X", "USDEUR=X", "GBPJPY=X", ESTR, DEPOSIT_FACILITY):
        assert capabilities.serves(identifier)
    for identifier in ("SAN.MC", "BTC-USD", "DGS3MO", "EURVES=X"):
        assert not capabilities.serves(identifier)


@pytest.mark.parametrize(
    ("day", "published"),
    [
        ("2026-04-02", "2026-04-07"),  # Good Friday and Easter Monday
        ("2025-12-24", "2025-12-29"),  # Christmas, 26 December and a weekend
        ("2025-12-31", "2026-01-02"),  # New Year's Day
        ("2026-04-30", "2026-05-04"),  # Labour Day and a weekend
        ("2026-11-06", "2026-11-09"),  # an ordinary Friday
    ],
)
def test_next_target_days_skip_weekends_and_holidays(day: str, published: str) -> None:
    result = next_target_days(pd.DatetimeIndex([day]))

    assert result[0] == pd.Timestamp(published)


def test_next_target_days_of_nothing() -> None:
    assert next_target_days(pd.DatetimeIndex([])).empty
