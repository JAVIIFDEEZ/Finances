"""Market-data cache on Parquet files, queried with DuckDB (ADR-0011).

Layout (one file per symbol and frequency, or per economic series)::

    <root>/bars/<frequency>/<url-encoded symbol>.parquet
    <root>/economic/<url-encoded series id>.parquet

Every file carries its domain metadata (instrument, provenance, coverage, storage time) as
Parquet key-value metadata, so a file is self-describing and the whole cache can be inspected
with DuckDB (see :meth:`ParquetSeriesStore.catalog`). Writes are atomic (temporary file and
rename). A corrupted or outdated file is reported and treated as a cache miss, never as an
error for the caller.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from investinglab.adapters.storage.codec import (
    decode_bars_request,
    decode_economic_request,
    decode_instrument,
    decode_source,
    encode_bars_request,
    encode_economic_request,
    encode_instrument,
    encode_source,
)
from investinglab.config.logging import get_logger
from investinglab.domain.economic import EconomicSeries
from investinglab.domain.errors import InvestingLabError
from investinglab.domain.series import TIME_INDEX_NAME, PriceAdjustment, PriceSeries
from investinglab.domain.time import Frequency
from investinglab.ports.storage import CachedBars, CachedEconomicSeries

if TYPE_CHECKING:
    from collections.abc import Callable

    from investinglab.ports.market_data import BarsRequest, EconomicRequest

__all__ = ["SCHEMA_VERSION", "ParquetSeriesStore"]

log = get_logger(__name__)

SCHEMA_VERSION: Final = 1
_METADATA_KEY: Final = b"investinglab"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ParquetSeriesStore:
    """:class:`~investinglab.ports.storage.SeriesStore` backed by local Parquet files.

    Args:
        root: Cache directory (created on first write).
        clock: Returns the current time, used to stamp entries (injectable for tests).
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._root = Path(root)
        self._clock = clock

    @property
    def root(self) -> Path:
        """Cache directory."""
        return self._root

    # ── Price bars ───────────────────────────────────────────────────

    def save_bars(self, series: PriceSeries, coverage: BarsRequest) -> None:
        """Store ``series`` (downloaded for ``coverage``), replacing any previous entry."""
        frame = series.bars.reset_index()
        metadata = {
            "schema": SCHEMA_VERSION,
            "kind": "bars",
            "instrument": encode_instrument(series.instrument),
            "frequency": series.frequency.value,
            "adjustment": series.adjustment.value,
            "source": encode_source(series.source),
            "coverage": encode_bars_request(coverage),
            "stored_at": self._clock().isoformat(),
            "rows": len(series),
            "start": series.start.isoformat(),
            "end": series.end.isoformat(),
        }
        self._write(frame, metadata, self._bars_path(series.symbol, series.frequency))

    def load_bars(self, request: BarsRequest) -> CachedBars | None:
        """Cached entry for the request's symbol and frequency, or ``None``."""
        path = self._bars_path(request.symbol, request.frequency)
        metadata = self._metadata(path, kind="bars")
        if metadata is None:
            return None
        try:
            frequency = Frequency(metadata["frequency"])
            frame = self._read(path)
            index = pd.DatetimeIndex(frame.pop(TIME_INDEX_NAME))
            if frequency.is_intraday:
                # Parquet holds UTC instants; DuckDB may hand them back without a zone.
                index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
            series = PriceSeries(
                instrument=decode_instrument(metadata["instrument"]),
                frequency=frequency,
                source=decode_source(metadata["source"]),
                data=frame.set_index(index),
                adjustment=PriceAdjustment(metadata["adjustment"]),
            )
            return CachedBars(
                series=series,
                coverage=decode_bars_request(metadata["coverage"]),
                stored_at=datetime.fromisoformat(metadata["stored_at"]),
            )
        except (InvestingLabError, KeyError, ValueError, duckdb.Error) as error:
            log.warning("cache_entry_unreadable", path=str(path), error=str(error))
            return None

    # ── Economic series ──────────────────────────────────────────────

    def save_economic(self, series: EconomicSeries, coverage: EconomicRequest) -> None:
        """Store an economic series (all its vintages), replacing any previous entry."""
        metadata = {
            "schema": SCHEMA_VERSION,
            "kind": "economic",
            "series_id": series.series_id,
            "title": series.title,
            "units": series.units,
            "frequency": series.frequency.value,
            "seasonal_adjustment": series.seasonal_adjustment,
            "source": encode_source(series.source),
            "coverage": encode_economic_request(coverage),
            "stored_at": self._clock().isoformat(),
            "rows": len(series.observations),
        }
        self._write(series.observations, metadata, self._economic_path(series.series_id))

    def load_economic(self, request: EconomicRequest) -> CachedEconomicSeries | None:
        """Cached entry for the request's series id, or ``None``."""
        path = self._economic_path(request.series_id)
        metadata = self._metadata(path, kind="economic")
        if metadata is None:
            return None
        try:
            series = EconomicSeries(
                series_id=metadata["series_id"],
                title=metadata["title"],
                units=metadata["units"],
                frequency=Frequency(metadata["frequency"]),
                source=decode_source(metadata["source"]),
                data=self._read(path),
                seasonal_adjustment=metadata.get("seasonal_adjustment"),
            )
            return CachedEconomicSeries(
                series=series,
                coverage=decode_economic_request(metadata["coverage"]),
                stored_at=datetime.fromisoformat(metadata["stored_at"]),
            )
        except (InvestingLabError, KeyError, ValueError, duckdb.Error) as error:
            log.warning("cache_entry_unreadable", path=str(path), error=str(error))
            return None

    # ── Inspection ───────────────────────────────────────────────────

    def catalog(self) -> pd.DataFrame:
        """One row per cached entry, read with DuckDB from the files' metadata only.

        Columns: ``kind``, ``key`` (symbol or series id), ``frequency``, ``provider``,
        ``rows``, ``start``, ``end``, ``stored_at`` and ``path``.
        """
        columns = ["kind", "key", "frequency", "provider", "rows", "start", "end", "stored_at"]
        files = sorted(str(p) for p in self._root.glob("*/**/*.parquet"))
        if not files:
            return pd.DataFrame(columns=[*columns, "path"])
        with duckdb.connect() as connection:
            rows = connection.execute(
                "SELECT file_name, value FROM parquet_kv_metadata(?) WHERE key = ?",
                [files, _METADATA_KEY],
            ).fetchall()
        records = []
        for file_name, value in rows:
            meta = json.loads(bytes(value))
            records.append(
                {
                    "kind": meta.get("kind"),
                    "key": meta.get("instrument", {}).get("symbol", meta.get("series_id")),
                    "frequency": meta.get("frequency"),
                    "provider": meta.get("source", {}).get("provider"),
                    "rows": meta.get("rows"),
                    "start": meta.get("start"),
                    "end": meta.get("end"),
                    "stored_at": meta.get("stored_at"),
                    "path": file_name,
                }
            )
        return pd.DataFrame.from_records(records).sort_values(["kind", "key"], ignore_index=True)

    # ── Internals ────────────────────────────────────────────────────

    def _bars_path(self, symbol: str, frequency: Frequency) -> Path:
        return self._root / "bars" / frequency.value / f"{quote(symbol, safe='')}.parquet"

    def _economic_path(self, series_id: str) -> Path:
        return self._root / "economic" / f"{quote(series_id, safe='')}.parquet"

    def _write(self, frame: pd.DataFrame, metadata: dict[str, Any], path: Path) -> None:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        merged = {**(table.schema.metadata or {}), _METADATA_KEY: json.dumps(metadata).encode()}
        table = table.replace_schema_metadata(merged)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            pq.write_table(table, temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _metadata(self, path: Path, *, kind: str) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            raw = (pq.read_schema(path).metadata or {}).get(_METADATA_KEY)
            metadata: dict[str, Any] = json.loads(raw) if raw else {}
        except (OSError, ValueError, pa.ArrowException) as error:
            log.warning("cache_entry_unreadable", path=str(path), error=str(error))
            return None
        if metadata.get("schema") != SCHEMA_VERSION or metadata.get("kind") != kind:
            log.info("cache_entry_outdated", path=str(path), schema=metadata.get("schema"))
            return None
        return metadata

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        with duckdb.connect() as connection:
            connection.execute("SET TimeZone = 'UTC'")
            frame: pd.DataFrame = connection.execute(
                "SELECT * FROM read_parquet(?)", [str(path)]
            ).df()
        return frame
