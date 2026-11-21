from __future__ import annotations

from datetime import date, timedelta

import pytest

from investinglab.domain import AssetClass, DomainError, Frequency, RateKind
from investinglab.ports import (
    BarsRequest,
    BookDepthRequest,
    Dataset,
    EconomicRequest,
    PositioningRequest,
    ProviderCapabilities,
    RateLimit,
    RateLimitedError,
    RatesRequest,
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


def test_rates_request_validation() -> None:
    request = RatesRequest("BTC/USDT:USDT", RateKind.FUNDING)

    assert (request.venue, request.start, request.end) == (None, None, None)
    with pytest.raises(DomainError, match="needs a symbol"):
        RatesRequest(" ", RateKind.BORROW)
    with pytest.raises(DomainError, match="is after end"):
        RatesRequest("X", RateKind.FUNDING, start=date(2024, 2, 1), end=date(2024, 1, 1))


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
    assert economic_only.can_serve_economic(EconomicRequest("UNRATE"))
    assert not capabilities.can_serve_economic(EconomicRequest("UNRATE"))


def test_capabilities_route_by_the_identifiers_served() -> None:
    pairs = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS, Dataset.ECONOMIC}),
        frequencies=frozenset({Frequency.DAY_1}),
        identifiers=r"[A-Z]{6}=X|EST\..+",
    )

    assert pairs.serves("EURUSD=X")
    assert not pairs.serves("SAN.MC")
    assert not pairs.serves("XEURUSD=X")  # the whole identifier must match
    assert pairs.can_serve_bars(BarsRequest("EURUSD=X"), TODAY)
    assert not pairs.can_serve_bars(BarsRequest("SAN.MC"), TODAY)
    assert pairs.can_serve_economic(EconomicRequest("EST.B.EU000A2X2A25.WT"))
    assert not pairs.can_serve_economic(EconomicRequest("DGS3MO"))
    with pytest.raises(DomainError, match="Invalid identifiers pattern"):
        ProviderCapabilities(datasets=frozenset({Dataset.BARS}), identifiers="(")


def test_a_dataset_can_have_identifiers_of_its_own() -> None:
    venue = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS, Dataset.HOLDING_RATES}),
        frequencies=frozenset({Frequency.DAY_1}),
        identifiers=r"[A-Z]+/[A-Z]+",
        identifiers_by_dataset={Dataset.HOLDING_RATES: r"[A-Z]+/[A-Z]+:[A-Z]+"},
        rate_kinds=frozenset({RateKind.FUNDING}),
    )

    assert venue.can_serve_bars(BarsRequest("BTC/USDT"), TODAY)
    assert not venue.can_serve_bars(BarsRequest("BTC/USDT:USDT"), TODAY)  # a swap has no bars here
    assert venue.can_serve_rates(RatesRequest("BTC/USDT:USDT", RateKind.FUNDING))
    assert not venue.can_serve_rates(RatesRequest("BTC/USDT", RateKind.FUNDING))
    assert venue.serves("BTC/USDT")
    assert not venue.serves("BTC/USDT", Dataset.HOLDING_RATES)
    with pytest.raises(DomainError, match="Invalid identifiers pattern"):
        ProviderCapabilities(
            datasets=frozenset({Dataset.HOLDING_RATES}),
            identifiers_by_dataset={Dataset.HOLDING_RATES: "["},
        )


def test_provider_errors_carry_context() -> None:
    error = RateLimitedError("yahoo", "HTTP 429", retry_after=3.0)

    assert error.provider == "yahoo"
    assert error.retryable
    assert error.retry_after == 3.0
    assert str(error) == "[yahoo] HTTP 429"


def test_positioning_is_routed_by_its_own_identifiers_and_frequencies() -> None:
    venue = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS, Dataset.POSITIONING}),
        frequencies=frozenset(Frequency),
        identifiers=r"[A-Z]+/[A-Z]+",
        identifiers_by_dataset={Dataset.POSITIONING: r"[A-Z]+/[A-Z]+:[A-Z]+"},
        frequencies_by_dataset={Dataset.POSITIONING: frozenset({Frequency.HOUR_1})},
    )

    assert venue.can_serve_positioning(PositioningRequest("BTC/USDT:USDT"))
    assert not venue.can_serve_positioning(PositioningRequest("BTC/USDT"))
    assert not venue.can_serve_positioning(
        PositioningRequest("BTC/USDT:USDT", frequency=Frequency.MINUTE_5)
    )
    assert venue.frequencies_of(Dataset.BARS) == frozenset(Frequency)
    assert venue.can_serve_bars(BarsRequest("BTC/USDT", Frequency.MINUTE_5), TODAY)
    bars_only = ProviderCapabilities(datasets=frozenset({Dataset.BARS}))
    assert not bars_only.can_serve_positioning(PositioningRequest("BTC/USDT:USDT"))


def test_a_positioning_request_is_validated() -> None:
    request = PositioningRequest("BTC/USDT:USDT")

    assert (request.venue, request.start, request.end) == (None, None, None)
    assert request.frequency is Frequency.HOUR_1
    with pytest.raises(DomainError, match="needs a symbol"):
        PositioningRequest(" ")
    with pytest.raises(DomainError, match="is after end"):
        PositioningRequest("BTC/USDT:USDT", start=date(2026, 11, 2), end=date(2026, 11, 1))


def test_book_depth_is_routed_by_its_own_identifiers_and_frequencies() -> None:
    venue = ProviderCapabilities(
        datasets=frozenset({Dataset.BARS, Dataset.BOOK_DEPTH}),
        frequencies=frozenset(Frequency),
        identifiers=r"[A-Z]+/[A-Z]+",
        identifiers_by_dataset={Dataset.BOOK_DEPTH: r"[A-Z]+/[A-Z]+:[A-Z]+"},
        frequencies_by_dataset={Dataset.BOOK_DEPTH: frozenset({Frequency.HOUR_1})},
        book_bands=frozenset({1.0, 2.0}),
    )

    assert venue.can_serve_book_depth(BookDepthRequest("BTC/USDT:USDT"))
    assert not venue.can_serve_book_depth(BookDepthRequest("BTC/USDT"))
    assert not venue.can_serve_book_depth(
        BookDepthRequest("BTC/USDT:USDT", frequency=Frequency.MINUTE_5)
    )
    bars_only = ProviderCapabilities(datasets=frozenset({Dataset.BARS}))
    assert not bars_only.can_serve_book_depth(BookDepthRequest("BTC/USDT:USDT"))


def test_a_book_depth_request_is_validated() -> None:
    request = BookDepthRequest("BTC/USDT:USDT")

    assert (request.venue, request.start, request.end) == (None, None, None)
    assert request.frequency is Frequency.HOUR_1
    with pytest.raises(DomainError, match="needs a symbol"):
        BookDepthRequest(" ")
    with pytest.raises(DomainError, match="is after end"):
        BookDepthRequest("BTC/USDT:USDT", start=date(2026, 11, 2), end=date(2026, 11, 1))
