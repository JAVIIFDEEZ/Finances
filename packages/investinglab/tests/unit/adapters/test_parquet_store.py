from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pandas as pd
import pyarrow.parquet as pq
import pytest

from investinglab.adapters.storage import SCHEMA_VERSION, ParquetSeriesStore
from investinglab.domain import (
    EXCHANGES,
    USD,
    AssetClass,
    Exchange,
    Frequency,
    Identifiers,
    Instrument,
    MarketSchedule,
    PriceSeries,
)
from investinglab.ports import BarsRequest, EconomicRequest, VintageMode
from investinglab.services import MarketDataService, ProviderRegistry
from support.factories import make_economic_series, make_series

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> ParquetSeriesStore:
    return ParquetSeriesStore(tmp_path / "cache", clock=lambda: NOW)


def test_daily_bars_round_trip(store: ParquetSeriesStore) -> None:
    series = make_series(symbol="^GSPC", ohlc=True, volume=[1, 2, 3, 4, 5])
    coverage = BarsRequest("^GSPC", start=date(2024, 1, 1))

    store.save_bars(series, coverage)
    cached = store.load_bars(BarsRequest("^GSPC"))

    assert cached is not None
    assert cached.series == series
    assert cached.coverage == coverage
    assert cached.stored_at == NOW
    assert (store.root / "bars" / "1d" / "%5EGSPC.parquet").exists()


def test_intraday_bars_keep_utc_timestamps(store: ParquetSeriesStore) -> None:
    index = pd.date_range("2024-01-02 14:30", periods=5, freq="1min", tz="UTC")
    series = make_series(
        [1.0, 2.0, 3.0, 4.0, 5.0],
        index=index,
        symbol="AAPL",
        frequency=Frequency.MINUTE_1,
        exchange=EXCHANGES["XNYS"],
    )

    store.save_bars(series, BarsRequest("AAPL", Frequency.MINUTE_1))
    cached = store.load_bars(BarsRequest("AAPL", Frequency.MINUTE_1))

    assert cached is not None
    assert cached.series == series
    assert str(pd.DatetimeIndex(cached.series.bars.index).tz) == "UTC"


def test_metadata_round_trips_unknown_venues_and_identifiers(store: ParquetSeriesStore) -> None:
    venue = Exchange("XWAR", "Warsaw Stock Exchange", "Europe/Warsaw", MarketSchedule(250, 8.0))
    instrument = Instrument(
        "PKO.WA",
        "PKO Bank Polski",
        AssetClass.EQUITY,
        USD,
        venue,
        Identifiers(isin="US0378331005", cik="320193"),
    )
    base = make_series(symbol="PKO.WA")
    series = PriceSeries(instrument, Frequency.DAY_1, base.source, base.bars)

    store.save_bars(series, BarsRequest("PKO.WA", asset_class=AssetClass.EQUITY))
    cached = store.load_bars(BarsRequest("PKO.WA"))

    assert cached is not None
    assert cached.series.instrument == instrument
    assert cached.coverage.asset_class is AssetClass.EQUITY


def test_economic_series_round_trip_with_vintages(store: ParquetSeriesStore) -> None:
    series = make_economic_series()
    coverage = EconomicRequest("SYNTH_RATE", mode=VintageMode.ALL_VINTAGES)

    store.save_economic(series, coverage)
    cached = store.load_economic(EconomicRequest("SYNTH_RATE"))

    assert cached is not None
    assert cached.series.observations.equals(series.observations)
    assert cached.series.title == series.title
    assert cached.series.seasonal_adjustment == "NSA"
    assert cached.coverage == coverage


def test_missing_entries_are_cache_misses(store: ParquetSeriesStore) -> None:
    assert store.load_bars(BarsRequest("SPY")) is None
    assert store.load_economic(EconomicRequest("UNRATE")) is None


def test_corrupted_files_are_cache_misses(store: ParquetSeriesStore) -> None:
    store.save_bars(make_series(symbol="SPY"), BarsRequest("SPY"))
    path = store.root / "bars" / "1d" / "SPY.parquet"
    path.write_bytes(b"not a parquet file")

    assert store.load_bars(BarsRequest("SPY")) is None


def _rewrite_metadata(path: Path, **changes: object) -> None:
    table = pq.read_table(path)
    meta = json.loads(table.schema.metadata[b"investinglab"])
    meta.update(changes)
    table = table.replace_schema_metadata(
        {**table.schema.metadata, b"investinglab": json.dumps(meta).encode()}
    )
    pq.write_table(table, path)


def test_outdated_schema_versions_are_cache_misses(store: ParquetSeriesStore) -> None:
    store.save_bars(make_series(symbol="SPY"), BarsRequest("SPY"))
    _rewrite_metadata(store.root / "bars" / "1d" / "SPY.parquet", schema=SCHEMA_VERSION + 1)

    assert store.load_bars(BarsRequest("SPY")) is None


def test_entries_failing_validation_are_cache_misses(store: ParquetSeriesStore) -> None:
    store.save_bars(make_series(symbol="SPY"), BarsRequest("SPY"))
    _rewrite_metadata(store.root / "bars" / "1d" / "SPY.parquet", frequency="1mo")
    store.save_economic(make_economic_series(), EconomicRequest("SYNTH_RATE"))
    _rewrite_metadata(store.root / "economic" / "SYNTH_RATE.parquet", source={})

    assert store.load_bars(BarsRequest("SPY")) is None
    assert store.load_economic(EconomicRequest("SYNTH_RATE")) is None


def test_writes_are_atomic_and_replace_previous_entries(store: ParquetSeriesStore) -> None:
    store.save_bars(make_series(symbol="SPY"), BarsRequest("SPY"))
    newer = make_series([1.0, 2.0, 3.0], symbol="SPY")
    store.save_bars(newer, BarsRequest("SPY"))

    cached = store.load_bars(BarsRequest("SPY"))

    assert cached is not None
    assert cached.series == newer
    assert sorted(p.name for p in (store.root / "bars" / "1d").iterdir()) == ["SPY.parquet"]


def test_catalog_lists_entries_from_metadata(store: ParquetSeriesStore) -> None:
    assert store.catalog().empty
    store.save_bars(make_series(symbol="SPY"), BarsRequest("SPY"))
    store.save_economic(make_economic_series(), EconomicRequest("SYNTH_RATE"))

    catalog = store.catalog()

    assert catalog[["kind", "key", "provider", "rows"]].to_dict("records") == [
        {"kind": "bars", "key": "SPY", "provider": "synthetic", "rows": 5},
        {"kind": "economic", "key": "SYNTH_RATE", "provider": "synthetic", "rows": 4},
    ]
    assert catalog.loc[0, "frequency"] == "1d"


async def test_service_uses_the_parquet_cache_end_to_end(store: ParquetSeriesStore) -> None:
    store.save_bars(make_series(symbol="SPY"), BarsRequest("SPY"))
    service = MarketDataService(ProviderRegistry(), store=store, clock=lambda: NOW)

    series = await service.get_bars(BarsRequest("SPY", start=date(2024, 1, 3)))

    assert series.prices.iloc[0] == 101.0
