"""Snapshots of a whole market: validation, dominance and ranking (SYNTHETIC values)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from investinglab.domain import (
    USD,
    AssetClass,
    DomainError,
    MarketCapRanking,
    MarketShare,
    MarketSnapshot,
    RankedAsset,
)
from support.factories import SYNTHETIC_SOURCE

NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)


def _snapshot(**changes: object) -> MarketSnapshot:
    values: dict[str, object] = {
        "total_market_cap": 2.0e12,
        "total_volume_24h": 8.0e10,
        "market_cap_change_24h": -0.03,
        "assets": 21_000,
        "dominance": (MarketShare("ETH", 0.10), MarketShare("BTC", 0.59)),
    }
    values.update(changes)
    return MarketSnapshot(AssetClass.CRYPTO, USD, NOW, SYNTHETIC_SOURCE, **values)  # type: ignore[arg-type]


def _asset(rank: int, symbol: str = "BTC", **changes: object) -> RankedAsset:
    values: dict[str, object] = {"id": symbol.lower(), "name": f"Synthetic {symbol}"}
    values.update(changes)
    return RankedAsset(rank=rank, symbol=symbol, **values)  # type: ignore[arg-type]


def test_a_snapshot_orders_its_dominance_and_says_what_the_rest_hold() -> None:
    snapshot = _snapshot()

    assert [share.symbol for share in snapshot.dominance] == ["BTC", "ETH"]  # largest first
    assert snapshot.share_of("BTC") == pytest.approx(0.59)
    assert snapshot.share_of("SOL") is None  # not published: unknown, not zero
    assert snapshot.others == pytest.approx(0.31)


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"total_market_cap": 0.0}, "positive"),
        ({"total_market_cap": float("nan")}, "finite"),
        ({"total_volume_24h": -1.0}, "zero or more"),
        ({"market_cap_change_24h": -1.0}, "above -100 %"),
        ({"assets": -1}, "cannot be negative"),
        ({"dominance": (MarketShare("BTC", 0.7), MarketShare("ETH", 0.4))}, "more than the whole"),
        ({"dominance": (MarketShare("BTC", 0.5), MarketShare("BTC", 0.1))}, "appears twice"),
    ],
    ids=["no-total", "nan", "volume", "change", "assets", "over-one", "twice"],
)
def test_a_snapshot_is_validated(changes: dict[str, object], problem: str) -> None:
    with pytest.raises(DomainError, match=problem):
        _snapshot(**changes)


def test_shares_and_instants_are_validated() -> None:
    with pytest.raises(DomainError, match="between 0 and 1"):
        MarketShare("BTC", 1.2)
    with pytest.raises(DomainError, match="in capitals"):
        MarketShare("btc", 0.5)
    with pytest.raises(DomainError, match="needs a timezone"):
        MarketSnapshot(AssetClass.CRYPTO, USD, NOW.replace(tzinfo=None), SYNTHETIC_SOURCE, 1.0)
    assert _snapshot(dominance=()).others == 1.0  # a source that gives no shares


def test_a_ranking_keeps_its_order_and_reads_as_a_table() -> None:
    ranking = MarketCapRanking(
        AssetClass.CRYPTO,
        USD,
        NOW,
        SYNTHETIC_SOURCE,
        (
            _asset(1, "BTC", price=60_000.0, market_cap=1.2e12, max_supply=21e6),
            _asset(2, "ETH", price=1_700.0, market_cap=2.1e11),
            _asset(3, "NEW"),  # a figure the source does not give stays missing
        ),
    )

    assert len(ranking) == 3
    assert len(ranking.top(2)) == 2
    assert ranking.find("eth") is not None
    assert ranking.find("XYZ") is None
    table = ranking.frame()
    assert list(table.index) == [1, 2, 3]
    assert table.loc[1, "symbol"] == "BTC"
    assert table["market_cap"].isna().tolist() == [False, False, True]
    with pytest.raises(DomainError, match="one asset or more"):
        ranking.top(0)


@pytest.mark.parametrize(
    ("assets", "problem"),
    [
        ((), "at least one asset"),
        ((_asset(2), _asset(1, "ETH")), "increase without repeating"),
        ((_asset(1), _asset(1, "ETH")), "increase without repeating"),
        ((_asset(1, "BTC"), _asset(2, "BTC")), "appears twice"),
    ],
    ids=["empty", "unordered", "repeated-rank", "repeated-asset"],
)
def test_a_ranking_is_validated(assets: tuple[RankedAsset, ...], problem: str) -> None:
    with pytest.raises(DomainError, match=problem):
        MarketCapRanking(AssetClass.CRYPTO, USD, NOW, SYNTHETIC_SOURCE, assets)


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"rank": 0}, "starts at 1"),
        ({"symbol": "btc"}, "in capitals"),
        ({"name": " "}, "needs a name"),
        ({"price": -1.0}, "price"),
        ({"market_cap": float("inf")}, "capitalisation"),
        ({"updated": datetime(2026, 11, 22)}, "needs a timezone"),  # noqa: DTZ001 - on purpose
    ],
    ids=["rank", "ticker", "name", "price", "cap", "naive"],
)
def test_a_ranked_asset_is_validated(changes: dict[str, object], problem: str) -> None:
    values: dict[str, object] = {"rank": 1, "id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"}
    values.update(changes)
    with pytest.raises(DomainError, match=problem):
        RankedAsset(**values)  # type: ignore[arg-type]
