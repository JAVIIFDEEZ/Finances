from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from investinglab.domain import AssetClass, DomainError, Frequency, RateKind
from investinglab.ports import (
    BarsRequest,
    Dataset,
    EconomicRequest,
    ProviderCapabilities,
    RatesRequest,
)
from investinglab.services import ProviderRegistry
from support.fakes import (
    BARS_CAPABILITIES,
    FLOW_CAPABILITIES,
    RATES_CAPABILITIES,
    FakeBarsProvider,
    FakeEconomicProvider,
    FakeFlowProvider,
    FakeRatesProvider,
)

TODAY = date(2026, 10, 31)


def _registry(*names: str) -> ProviderRegistry:
    registry = ProviderRegistry()
    for name in names:
        registry.register(FakeBarsProvider(name))
    return registry


def test_registration_order_is_the_default_preference() -> None:
    registry = _registry("yahoo", "tiingo", "alphavantage")

    candidates = registry.bars_candidates(BarsRequest("SPY"), TODAY)

    assert [p.name for p in candidates] == ["yahoo", "tiingo", "alphavantage"]
    assert registry.names == ("yahoo", "tiingo", "alphavantage")
    assert "yahoo" in registry
    assert "missing" not in registry


def test_most_specific_preference_wins_and_others_remain_as_fallback() -> None:
    registry = _registry("yahoo", "tiingo", "alpaca")
    registry.prefer(["alpaca", "yahoo"], frequency=Frequency.MINUTE_1)
    registry.prefer(["tiingo"], asset_class=AssetClass.EQUITY)
    registry.prefer(
        ["yahoo", "alpaca"], asset_class=AssetClass.EQUITY, frequency=Frequency.MINUTE_1
    )

    def order(request: BarsRequest) -> list[str]:
        return [p.name for p in registry.bars_candidates(request, TODAY)]

    assert order(BarsRequest("SPY", Frequency.MINUTE_1)) == ["alpaca", "yahoo", "tiingo"]
    assert order(BarsRequest("SPY", asset_class=AssetClass.EQUITY)) == ["tiingo", "yahoo", "alpaca"]
    assert order(BarsRequest("SPY", Frequency.MINUTE_1, asset_class=AssetClass.EQUITY)) == [
        "yahoo",
        "alpaca",
        "tiingo",
    ]


def test_candidates_are_filtered_by_capabilities() -> None:
    registry = ProviderRegistry()
    registry.register(
        FakeBarsProvider(
            "daily_only",
            capabilities=ProviderCapabilities(
                datasets=frozenset({Dataset.BARS}),
                asset_classes=frozenset({AssetClass.EQUITY}),
                frequencies=frozenset({Frequency.DAY_1}),
            ),
        )
    )
    registry.register(FakeBarsProvider("everything"))

    candidates = registry.bars_candidates(BarsRequest("BTC-USD", Frequency.HOUR_1), TODAY)

    assert [p.name for p in candidates] == ["everything"]


def test_economic_providers() -> None:
    registry = ProviderRegistry()
    registry.register(FakeEconomicProvider("fred"))

    assert [p.name for p in registry.economic_candidates(EconomicRequest("UNRATE"))] == ["fred"]
    assert registry.bars_candidates(BarsRequest("SPY"), TODAY) == []


def test_providers_are_skipped_for_identifiers_they_do_not_serve() -> None:
    registry = ProviderRegistry()
    closed = ProviderCapabilities(datasets=frozenset({Dataset.ECONOMIC}), identifiers=r"EST\..+")
    registry.register(FakeEconomicProvider("ecb", capabilities=closed))
    registry.register(FakeEconomicProvider("fred"))

    estr = registry.economic_candidates(EconomicRequest("EST.B.EU000A2X2A25.WT"))
    unrate = registry.economic_candidates(EconomicRequest("UNRATE"))

    assert [p.name for p in estr] == ["ecb", "fred"]
    assert [p.name for p in unrate] == ["fred"]


def test_duplicated_names_are_rejected() -> None:
    registry = _registry("yahoo")

    with pytest.raises(DomainError, match="already registered"):
        registry.register(FakeBarsProvider("yahoo"))


def test_preferences_must_name_registered_providers() -> None:
    with pytest.raises(DomainError, match="Unknown"):
        _registry("yahoo").prefer(["tiingo"])


@dataclass
class _NoMethods:
    name: str
    capabilities: ProviderCapabilities


@pytest.mark.parametrize(
    "capabilities",
    [
        BARS_CAPABILITIES,
        ProviderCapabilities(datasets=frozenset({Dataset.ECONOMIC})),
        FLOW_CAPABILITIES,
        RATES_CAPABILITIES,
    ],
    ids=["bars", "economic", "flow", "holding_rates"],
)
def test_declared_datasets_must_be_implemented(capabilities: ProviderCapabilities) -> None:
    with pytest.raises(DomainError, match="declares"):
        ProviderRegistry().register(_NoMethods("broken", capabilities))  # type: ignore[arg-type]


@dataclass
class _BarsAndFlow:
    """A venue serving both datasets, like Binance."""

    name: str
    capabilities: ProviderCapabilities

    async def fetch_bars(self, request: BarsRequest) -> None:
        raise NotImplementedError

    async def fetch_flow(self, request: BarsRequest) -> None:
        raise NotImplementedError


def test_flow_providers_follow_the_preferences_of_the_bars() -> None:
    both = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS, Dataset.FLOW}),
        asset_classes=frozenset(AssetClass),
        frequencies=frozenset(Frequency),
    )
    registry = _registry("yahoo")
    registry.register(FakeFlowProvider("tape"))
    registry.register(_BarsAndFlow("venue", both))  # type: ignore[arg-type]
    registry.prefer(["venue", "yahoo"], asset_class=AssetClass.CRYPTO)
    registry.prefer(["tape"], frequency=Frequency.MINUTE_1)

    crypto = BarsRequest("BTC/USDT", asset_class=AssetClass.CRYPTO)
    minute = BarsRequest("SPY", Frequency.MINUTE_1)

    assert [p.name for p in registry.flow_candidates(crypto, TODAY)] == ["venue", "tape"]
    assert [p.name for p in registry.bars_candidates(crypto, TODAY)] == ["venue", "yahoo"]
    assert [p.name for p in registry.flow_candidates(minute, TODAY)] == ["tape", "venue"]
    assert [p.name for p in registry.bars_candidates(minute, TODAY)] == ["yahoo", "venue"]
    assert registry.names == ("yahoo", "tape", "venue")
    assert registry.capabilities()["venue"] is both


def test_flow_candidates_are_filtered_by_capabilities() -> None:
    registry = ProviderRegistry()
    registry.register(
        FakeFlowProvider(
            "pairs",
            capabilities=ProviderCapabilities(
                datasets=frozenset({Dataset.FLOW}),
                asset_classes=frozenset({AssetClass.CRYPTO}),
                frequencies=frozenset({Frequency.DAY_1}),
                identifiers=r"[A-Z]+/[A-Z]+",
            ),
        )
    )

    assert registry.flow_candidates(BarsRequest("BTC/USDT"), TODAY)
    assert not registry.flow_candidates(BarsRequest("SPY"), TODAY)
    assert not registry.flow_candidates(BarsRequest("BTC/USDT", Frequency.HOUR_1), TODAY)
    assert not registry.bars_candidates(BarsRequest("BTC/USDT"), TODAY)


def test_rates_go_to_the_providers_of_that_kind_and_venue() -> None:
    funding_only = ProviderCapabilities(
        datasets=frozenset({Dataset.HOLDING_RATES}),
        rate_kinds=frozenset({RateKind.FUNDING}),
        identifiers=r".+:.+",
    )
    registry = ProviderRegistry()
    registry.register(FakeRatesProvider("okx", capabilities=funding_only))
    registry.register(FakeRatesProvider("broker"))

    funding = RatesRequest("BTC/USDT:USDT", RateKind.FUNDING)
    borrow = RatesRequest("SAN.MC", RateKind.BORROW)

    assert [p.name for p in registry.rates_candidates(funding)] == ["okx", "broker"]
    assert [p.name for p in registry.rates_candidates(borrow)] == ["broker"]
    on_okx = RatesRequest("BTC/USDT:USDT", RateKind.FUNDING, venue="okx")
    assert [p.name for p in registry.rates_candidates(on_okx)] == ["okx"]
    assert not registry.rates_candidates(RatesRequest("SAN.MC", RateKind.FUNDING, venue="okx"))
    assert registry.names == ("okx", "broker")


def test_preferences_may_name_flow_only_providers() -> None:
    registry = ProviderRegistry()
    registry.register(FakeFlowProvider("tape"))

    registry.prefer(["tape"])

    assert not registry.bars_candidates(BarsRequest("SPY"), TODAY)
    with pytest.raises(DomainError, match="Unknown"):
        registry.prefer(["nobody"])
