from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from investinglab.domain import EUR, EXCHANGES, GBP, USD, AssetClass, CurrencyPair
from investinglab.services import (
    CurrencyService,
    DataUnavailableError,
    MarketDataService,
    ProviderRegistry,
    yahoo_style_fx_symbol,
)
from support.factories import make_fx_series, make_series
from support.fakes import FakeBarsProvider

NOW = datetime(2026, 10, 31, tzinfo=UTC)
DAYS = pd.bdate_range("2024-01-01", periods=8)


def _service(provider: FakeBarsProvider) -> CurrencyService:
    registry = ProviderRegistry()
    registry.register(provider)
    return CurrencyService(MarketDataService(registry, clock=lambda: NOW))


def test_yahoo_style_symbols() -> None:
    assert yahoo_style_fx_symbol(CurrencyPair(USD, EUR)) == "USDEUR=X"


async def test_get_rates_requests_the_fx_pair() -> None:
    fx = make_fx_series([0.9] * 8, pair="USDEUR", index=DAYS)
    provider = FakeBarsProvider("fx", {"USDEUR=X": fx})

    rates = await _service(provider).get_rates(CurrencyPair(USD, EUR), start=date(2024, 1, 1))

    assert rates.pair == CurrencyPair(USD, EUR)
    request = provider.calls[0]
    assert request.asset_class is AssetClass.FX
    assert request.start == date(2024, 1, 1)


async def test_convert_all_fetches_each_pair_once() -> None:
    fx = make_fx_series([0.5] * 8, pair="USDEUR", index=DAYS)
    provider = FakeBarsProvider("fx", {"USDEUR=X": fx})
    spy = make_series(
        [100.0] * 5 + [110.0] * 3,
        symbol="SPY",
        currency=USD,
        index=DAYS,
        exchange=EXCHANGES["XNYS"],
    )
    qqq = make_series(
        [50.0] * 8, symbol="QQQ", currency=USD, index=DAYS, exchange=EXCHANGES["XNYS"]
    )
    san = make_series([4.0] * 8, symbol="SAN.MC", index=DAYS)

    converted = await _service(provider).convert_all([spy, qqq, san], EUR)

    assert [s.currency for s in converted] == [EUR, EUR, EUR]
    assert converted[0].prices.iloc[0] == pytest.approx(50.0)
    assert converted[2] is san
    assert len(provider.calls) == 1


async def test_convert_single_series_and_passthrough() -> None:
    fx = make_fx_series([1.25] * 8, pair="GBPEUR", index=DAYS)
    service = _service(FakeBarsProvider("fx", {"GBPEUR=X": fx}))
    vod = make_series(
        [2.0] * 8, symbol="VOD.L", currency=GBP, index=DAYS, exchange=EXCHANGES["XLON"]
    )

    converted = await service.convert(vod, EUR)

    assert converted.prices.tolist() == pytest.approx([2.5] * 8)
    assert await service.convert(converted, EUR) is converted


async def test_missing_fx_data_propagates() -> None:
    service = _service(FakeBarsProvider("fx"))
    spy = make_series(symbol="SPY", currency=USD, exchange=EXCHANGES["XNYS"])

    with pytest.raises(DataUnavailableError):
        await service.convert(spy, EUR)
