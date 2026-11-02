"""Strict import of the user's own price files (CSV, Parquet) and DataFrames.

External data passes through :class:`ImportSpec` (Pydantic) before it becomes a
:class:`~investinglab.domain.PriceSeries`, so a wrong currency, an unknown venue or a
mislabelled column fails at the edge with a precise message (ADR-0006).

Accepted transformations are only the ones that do not change any value: renaming columns,
sorting by date and dropping rows where *every* price is empty (a holiday exported as a row
of nulls is not an observation). Prices quoted in minor units (``GBp``) are converted to the
major currency. Duplicated dates, missing closes and impossible prices are rejected, never
repaired.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import EXCHANGES, AssetClass, Identifiers, Instrument
from investinglab.domain.money import parse_quote_currency
from investinglab.domain.series import DataSource, PriceAdjustment, PriceSeries
from investinglab.domain.time import Frequency

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["ImportSpec", "SeriesImporter"]

_PRICE_COLUMNS: Final = ("open", "high", "low", "close", "adj_close")
_CANONICAL: Final[Mapping[str, str]] = {
    "date": "date",
    "datetime": "date",
    "timestamp": "date",
    "time": "date",
    "fecha": "date",
    "open": "open",
    "apertura": "open",
    "high": "high",
    "maximo": "high",
    "máximo": "high",
    "low": "low",
    "minimo": "low",
    "mínimo": "low",
    "close": "close",
    "cierre": "close",
    "último": "close",
    "ultimo": "close",
    "price": "close",
    "adj close": "adj_close",
    "adj_close": "adj_close",
    "adjclose": "adj_close",
    "adjusted close": "adj_close",
    "volume": "volume",
    "volumen": "volume",
    "vol.": "volume",
}


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


class ImportSpec(BaseModel):
    """What a price file contains: the instrument behind it and how to read it.

    Attributes:
        symbol: Canonical symbol (``SAN.MC``).
        name: Instrument name (defaults to the symbol).
        currency: Quote currency as written by the source (ISO 4217; ``GBp`` for pence).
        asset_class: Asset class.
        exchange: Venue MIC (``XMAD``, ``XNYS``, ``CRYPTO``...), if known.
        isin: ISIN, validated with its checksum.
        frequency: Bar frequency.
        adjustment: Adjustment applied to open/high/low/close.
        columns: Extra mapping ``source column -> canonical name`` for unusual headers
            (``open``, ``high``, ``low``, ``close``, ``adj_close``, ``volume``, ``date``).
        timezone: Timezone of naive intraday timestamps (UTC when ``None``).
        provider: Provenance slug written in the series' ``DataSource``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    symbol: str = Field(min_length=1)
    name: str | None = None
    currency: str = Field(min_length=3)
    asset_class: AssetClass = AssetClass.EQUITY
    exchange: str | None = None
    isin: str | None = None
    frequency: Frequency = Frequency.DAY_1
    adjustment: PriceAdjustment = PriceAdjustment.RAW
    columns: dict[str, str] = Field(default_factory=dict)
    timezone: str | None = None
    provider: str = "file"

    @field_validator("currency")
    @classmethod
    def _known_currency(cls, value: str) -> str:
        parse_quote_currency(value)
        return value

    @field_validator("exchange")
    @classmethod
    def _known_exchange(cls, value: str | None) -> str | None:
        if value is not None and value.upper() not in EXCHANGES:
            known = ", ".join(sorted(EXCHANGES))
            raise ValueError(f"unknown exchange {value!r}; known: {known}")
        return value.upper() if value is not None else None

    @field_validator("columns")
    @classmethod
    def _canonical_targets(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {*_PRICE_COLUMNS, "volume", "date"}
        wrong = sorted(target for target in value.values() if target not in allowed)
        if wrong:
            raise ValueError(f"unknown target columns {wrong}; allowed: {sorted(allowed)}")
        return value

    def instrument(self) -> Instrument:
        """The instrument described by the spec."""
        unit = parse_quote_currency(self.currency)
        return Instrument(
            symbol=self.symbol,
            name=self.name or self.symbol,
            asset_class=self.asset_class,
            currency=unit.currency,
            exchange=EXCHANGES[self.exchange] if self.exchange else None,
            identifiers=Identifiers(isin=self.isin),
        )


class SeriesImporter:
    """Turns user files and DataFrames into validated price series."""

    def from_dataframe(
        self,
        frame: pd.DataFrame,
        spec: ImportSpec,
        *,
        retrieved_at: datetime | None = None,
        dataset: str | None = None,
    ) -> PriceSeries:
        """Build a series from a DataFrame with a date column or a DatetimeIndex.

        Raises:
            DomainError: If a column cannot be mapped or a date is unreadable.
            InvalidSeriesError: If the data breaks any rule of a price series.
        """
        renamed = self._renamed(frame, spec)
        if "date" in renamed.columns:
            renamed = renamed.set_index("date")
        index = self._index(renamed.index, spec)
        bars = renamed.set_axis(index).sort_index(kind="stable")
        prices = [c for c in _PRICE_COLUMNS if c in bars.columns]
        bars = bars.dropna(how="all", subset=prices) if prices else bars
        scale = parse_quote_currency(spec.currency).scale
        if scale != 1.0:
            bars[prices] = bars[prices] * scale
        source = DataSource(
            provider=spec.provider,
            retrieved_at=retrieved_at or datetime.now(UTC),
            dataset=dataset,
        )
        return PriceSeries(
            instrument=spec.instrument(),
            frequency=spec.frequency,
            source=source,
            data=bars,
            adjustment=spec.adjustment,
        )

    def from_file(self, path: str | Path, spec: ImportSpec) -> PriceSeries:
        """Read a ``.csv`` or ``.parquet`` file; its modification time is the retrieval time.

        Raises:
            DomainError: If the format is not supported or the file cannot be parsed.
        """
        source = Path(path)
        suffix = source.suffix.lower()
        if suffix == ".csv":
            frame = pd.read_csv(source)
        elif suffix in {".parquet", ".pq"}:
            frame = pd.read_parquet(source)
        else:
            raise DomainError(f"Unsupported price file {source.name!r}: use .csv or .parquet")
        modified = datetime.fromtimestamp(source.stat().st_mtime, tz=UTC)
        return self.from_dataframe(frame, spec, retrieved_at=modified, dataset=source.name)

    @staticmethod
    def _renamed(frame: pd.DataFrame, spec: ImportSpec) -> pd.DataFrame:
        explicit = {_normalise(k): v for k, v in spec.columns.items()}
        mapping: dict[str, str] = {}
        unknown: list[str] = []
        for column in frame.columns:
            key = _normalise(str(column))
            target = explicit.get(key) or _CANONICAL.get(key)
            if target is None:
                unknown.append(str(column))
            else:
                mapping[str(column)] = target
        if unknown:
            raise DomainError(
                f"Cannot map columns {unknown} of {spec.symbol}; name them with ImportSpec.columns"
            )
        if len(set(mapping.values())) != len(mapping):
            raise DomainError(f"Several columns of {spec.symbol} map to the same field: {mapping}")
        return frame.rename(columns=mapping)

    @staticmethod
    def _index(index: pd.Index, spec: ImportSpec) -> pd.DatetimeIndex:
        try:
            parsed = pd.DatetimeIndex(pd.to_datetime(index, format="mixed"))
        except (ValueError, TypeError) as error:
            raise DomainError(f"Unreadable dates in {spec.symbol}: {error}") from error
        if spec.frequency.is_intraday:
            if parsed.tz is None:
                parsed = parsed.tz_localize(spec.timezone or "UTC")
            return parsed.tz_convert("UTC")
        if parsed.tz is not None:
            parsed = parsed.tz_localize(None)
        return parsed
