from __future__ import annotations

from datetime import date, timedelta

import pytest

from investinglab.domain import AssetClass, DomainError, Frequency
from investinglab.ports import (
    BarsRequest,
    Dataset,
    EconomicRequest,
    ProviderCapabilities,
    RateLimit,
    RateLimitedError,
    VintageMode,
)

TODAY = date(2026, 10, 31)


def test_bars_request_validation() -> None:
    with pytest.raises(DomainError, match="symbol"):
        BarsRequest(" ")
    with pytest.raises(DomainError, match="after"):
        BarsRequest("SPY", start=date(2024, 2, 1), end=date(2024, 1, 1))


@pytest.mark.parametrize(
    ("cached", "requested", "expected"),
    [
        (BarsRequest("SPY"), BarsRequest("SPY", start=date(2020, 1, 1)), True),
        (BarsRequest("SPY", start=date(2020, 1, 1)), BarsRequest("SPY"), False),
        (
            BarsRequest("SPY", start=date(2020, 1, 1)),
            BarsRequest("SPY", start=date(2021, 1, 1)),
            True,
        ),
        (BarsRequest("SPY", end=date(2024, 1, 1)), BarsRequest("SPY", end=date(2025, 1, 1)), False),
        (BarsRequest("SPY", end=date(2024, 1, 1)), BarsRequest("SPY"), False),
        (BarsRequest("SPY"), BarsRequest("QQQ"), False),
        (BarsRequest("SPY"), BarsRequest("SPY", Frequency.WEEK_1), False),
    ],
)
def test_bars_coverage(cached: BarsRequest, requested: BarsRequest, expected: bool) -> None:
    assert cached.covers(requested) is expected


@pytest.mark.parametrize(
    ("cached", "requested", "expected"),
    [
        (EconomicRequest("X", mode=VintageMode.ALL_VINTAGES), EconomicRequest("X"), True),
        (EconomicRequest("X"), EconomicRequest("X", mode=VintageMode.LATEST), False),
        (EconomicRequest("X"), EconomicRequest("X", start=date(2020, 1, 1)), True),
        (EconomicRequest("X", start=date(2020, 1, 1)), EconomicRequest("X"), False),
        (EconomicRequest("X", end=date(2020, 1, 1)), EconomicRequest("X"), False),
        (EconomicRequest("X"), EconomicRequest("Y"), False),
    ],
)
def test_economic_coverage(
    cached: EconomicRequest, requested: EconomicRequest, expected: bool
) -> None:
    assert cached.covers(requested) is expected


def test_economic_request_validation() -> None:
    with pytest.raises(DomainError):
        EconomicRequest("")
    with pytest.raises(DomainError):
        EconomicRequest("X", start=date(2024, 2, 1), end=date(2024, 1, 1))


def test_rate_limit_validation() -> None:
    assert RateLimit(5, 60).max_calls == 5
    with pytest.raises(DomainError):
        RateLimit(0, 60)
    with pytest.raises(DomainError):
        RateLimit(5, 0)


def test_capabilities_filter_requests() -> None:
    capabilities = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS}),
        asset_classes=frozenset({AssetClass.EQUITY, AssetClass.INDEX}),
        frequencies=frozenset({Frequency.DAY_1, Frequency.MINUTE_1}),
        max_history={Frequency.MINUTE_1: timedelta(days=7)},
    )

    assert capabilities.can_serve_bars(BarsRequest("SPY"), TODAY)
    assert capabilities.can_serve_bars(BarsRequest("SPY", asset_class=AssetClass.EQUITY), TODAY)
    assert not capabilities.can_serve_bars(BarsRequest("BTC", asset_class=AssetClass.CRYPTO), TODAY)
    assert not capabilities.can_serve_bars(BarsRequest("SPY", Frequency.WEEK_1), TODAY)
    recent = BarsRequest("SPY", Frequency.MINUTE_1, start=TODAY - timedelta(days=3))
    old = BarsRequest("SPY", Frequency.MINUTE_1, start=TODAY - timedelta(days=30))
    assert capabilities.can_serve_bars(recent, TODAY)
    assert not capabilities.can_serve_bars(old, TODAY)
    assert not capabilities.can_serve_bars(BarsRequest("SPY", Frequency.MINUTE_1), TODAY)
    economic_only = ProviderCapabilities(datasets=frozenset({Dataset.ECONOMIC}))
    assert not economic_only.can_serve_bars(BarsRequest("SPY"), TODAY)


def test_provider_errors_carry_context() -> None:
    error = RateLimitedError("yahoo", "HTTP 429", retry_after=3.0)

    assert error.provider == "yahoo"
    assert error.retryable
    assert error.retry_after == 3.0
    assert str(error) == "[yahoo] HTTP 429"
