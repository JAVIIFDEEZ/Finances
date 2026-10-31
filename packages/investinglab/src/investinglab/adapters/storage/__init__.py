"""Storage adapters for the market-data cache (Parquet + DuckDB)."""

from investinglab.adapters.storage.parquet import SCHEMA_VERSION, ParquetSeriesStore

__all__ = ["SCHEMA_VERSION", "ParquetSeriesStore"]
