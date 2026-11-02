from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest
from pydantic import ValidationError

from investinglab.adapters.files import ImportSpec, SeriesImporter
from investinglab.adapters.files.importer import _PRICE_COLUMNS
from investinglab.domain import (
    GBP,
    DomainError,
    Frequency,
    InvalidSeriesError,
    PriceAdjustment,
    PriceField,
)

if TYPE_CHECKING:
    from pathlib import Path

IMPORTER = SeriesImporter()
SPEC = ImportSpec(symbol="SYN.MC", currency="EUR", exchange="XMAD")


def _yahoo_style() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2024-01-04", "2024-01-02", "2024-01-03", "2024-01-05"],
            "Open": [10.1, 10.0, 10.2, None],
            "High": [10.5, 10.4, 10.6, None],
            "Low": [9.9, 9.8, 10.0, None],
            "Close": [10.3, 10.2, 10.4, None],
            "Adj Close": [10.0, 9.9, 10.1, None],
            "Volume": [1000, 1200, 900, None],
        }
    )


def test_canonical_columns_cover_every_price_field() -> None:
    assert set(_PRICE_COLUMNS) | {"volume"} == {f.value for f in PriceField}


def test_dataframes_are_renamed_sorted_and_cleaned_of_empty_rows() -> None:
    series = IMPORTER.from_dataframe(_yahoo_style(), SPEC, dataset="sample")

    assert list(series.bars.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    assert list(series.bars.index) == list(pd.bdate_range("2024-01-02", periods=3))
    assert series.prices.tolist() == [9.9, 10.1, 10.0]
    assert series.instrument.exchange is not None
    assert series.instrument.exchange.code == "XMAD"
    assert series.source.provider == "file"
    assert series.source.dataset == "sample"


def test_spanish_headers_and_explicit_mappings() -> None:
    frame = pd.DataFrame(
        {
            "Fecha": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "Último": [1.0, 1.1, 1.2],
            "x": [5, 6, 7],
        }
    )
    spec = ImportSpec(symbol="ES", currency="EUR", columns={"x": "volume"})

    series = IMPORTER.from_dataframe(frame, spec)

    assert series.bars["volume"].tolist() == [5, 6, 7]
    assert series.prices.tolist() == [1.0, 1.1, 1.2]


def test_prices_in_pence_are_converted_to_pounds() -> None:
    frame = pd.DataFrame(
        {"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "close": [250.0, 260.0, 255.0]}
    )

    series = IMPORTER.from_dataframe(frame, ImportSpec(symbol="VOD.L", currency="GBp"))

    assert series.currency == GBP
    assert series.prices.tolist() == pytest.approx([2.5, 2.6, 2.55])


def test_intraday_timestamps_are_localised_then_stored_in_utc() -> None:
    frame = pd.DataFrame(
        {
            "datetime": ["2024-03-04 09:00", "2024-03-04 10:00", "2024-03-04 11:00"],
            "close": [1.0, 1.1, 1.2],
        }
    )
    spec = ImportSpec(
        symbol="I", currency="EUR", frequency=Frequency.HOUR_1, timezone="Europe/Madrid"
    )

    series = IMPORTER.from_dataframe(frame, spec)

    assert str(pd.DatetimeIndex(series.bars.index).tz) == "UTC"
    assert series.bars.index[0] == pd.Timestamp("2024-03-04 08:00", tz="UTC")


def test_timezone_aware_daily_dates_become_session_labels() -> None:
    index = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"]).tz_localize("UTC")
    frame = pd.DataFrame({"close": [1.0, 1.1, 1.2]}, index=index)

    series = IMPORTER.from_dataframe(frame, ImportSpec(symbol="D", currency="EUR"))

    assert pd.DatetimeIndex(series.bars.index).tz is None


def test_unmapped_columns_are_rejected() -> None:
    frame = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0], "mystery": [1]})

    with pytest.raises(DomainError, match=r"Cannot map columns \['mystery'\]"):
        IMPORTER.from_dataframe(frame, SPEC)


def test_two_columns_for_one_field_are_rejected() -> None:
    frame = pd.DataFrame({"date": ["2024-01-02"], "close": [1.0], "price": [1.0]})

    with pytest.raises(DomainError, match="map to the same field"):
        IMPORTER.from_dataframe(frame, SPEC)


def test_unreadable_dates_are_rejected() -> None:
    frame = pd.DataFrame(
        {"date": ["not a date", "2024-01-03", "2024-01-04"], "close": [1.0, 1.1, 1.2]}
    )

    with pytest.raises(DomainError, match="Unreadable dates"):
        IMPORTER.from_dataframe(frame, SPEC)


def test_duplicated_dates_and_missing_closes_are_never_repaired() -> None:
    duplicated = pd.DataFrame(
        {"date": ["2024-01-02", "2024-01-02", "2024-01-03"], "close": [1.0, 1.1, 1.2]}
    )
    missing_close = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [1.0, 1.0, 1.0],
            "close": [1.0, None, 1.2],
        }
    )

    with pytest.raises(InvalidSeriesError, match="duplicated"):
        IMPORTER.from_dataframe(duplicated, SPEC)
    with pytest.raises(InvalidSeriesError, match="missing, non-finite or non-positive"):
        IMPORTER.from_dataframe(missing_close, SPEC)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"currency": "XYZ"}, "XYZ"),
        ({"exchange": "NOPE"}, "unknown exchange"),
        ({"columns": {"x": "bogus"}}, "unknown target columns"),
        ({"surprise": 1}, "Extra inputs"),
    ],
)
def test_specs_are_validated(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ImportSpec(**{"symbol": "S", "currency": "EUR", **changes})  # type: ignore[arg-type]


def test_spec_builds_the_instrument() -> None:
    spec = ImportSpec(
        symbol="SAN.MC",
        name="Banco Santander",
        currency="eur",
        exchange="xmad",
        isin="ES0113900J37",
        adjustment=PriceAdjustment.SPLITS_AND_DIVIDENDS,
    )

    instrument = spec.instrument()

    assert instrument.name == "Banco Santander"
    assert str(instrument.currency) == "EUR"
    assert instrument.identifiers.isin == "ES0113900J37"


def test_csv_and_parquet_files(tmp_path: Path) -> None:
    frame = _yahoo_style()
    frame.to_csv(tmp_path / "s.csv", index=False)
    frame.dropna().assign(Date=lambda f: pd.to_datetime(f["Date"])).to_parquet(
        tmp_path / "s.parquet"
    )

    from_csv = IMPORTER.from_file(tmp_path / "s.csv", SPEC)
    from_parquet = IMPORTER.from_file(tmp_path / "s.parquet", SPEC)

    assert from_csv.bars.equals(from_parquet.bars)
    assert from_csv.source.dataset == "s.csv"
    assert from_csv.retrieved_at.tzinfo is not None


def test_other_file_types_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prices.xlsx"
    path.write_bytes(b"")

    with pytest.raises(DomainError, match=r"use \.csv or \.parquet"):
        IMPORTER.from_file(path, SPEC)
