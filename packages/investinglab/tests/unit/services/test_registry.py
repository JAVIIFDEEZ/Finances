from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from investinglab.domain import AssetClass, DomainError, Frequency
from investinglab.ports import BarsRequest, Dataset, EconomicRequest, ProviderCapabilities
from investinglab.services import ProviderRegistry
from support.fakes import BARS_CAPABILITIES, FakeBarsProvider, FakeEconomicProvider

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
    [BARS_CAPABILITIES, ProviderCapabilities(datasets=frozenset({Dataset.ECONOMIC}))],
)
def test_declared_datasets_must_be_implemented(capabilities: ProviderCapabilities) -> None:
    with pytest.raises(DomainError, match="declares"):
        ProviderRegistry().register(_NoMethods("broken", capabilities))  # type: ignore[arg-type]
