"""Provider of the user's own price files: a folder of CSV/Parquet files and a catalogue.

The folder holds one file per symbol (``SAN.MC.csv``, ``EURUSD=X.parquet``...) and an
``instruments.toml`` describing each one, because a price file alone does not say which
currency or venue its numbers belong to, and the platform never guesses::

    ["SAN.MC"]
    name = "Banco Santander"
    currency = "EUR"
    exchange = "XMAD"
    adjustment = "splits_and_dividends"

    ["EURUSD=X"]
    currency = "USD"
    asset_class = "fx"
    exchange = "FX"

Every key of :class:`~investinglab.adapters.files.ImportSpec` is accepted. The provider
plugs into the registry like any remote provider, so the same code works with downloaded
data or with local files (offline, reproducible, ideal for demos and exports from brokers).
A file with a volume column also serves its flow: the volume of the same bars, without
aggressor side (ADR-0031).
"""

from __future__ import annotations

import asyncio
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from investinglab.adapters.files.importer import ImportSpec, SeriesImporter
from investinglab.domain.errors import DomainError, InvalidSeriesError
from investinglab.domain.flow import FlowField, FlowSeries
from investinglab.domain.instruments import AssetClass
from investinglab.domain.series import PriceField
from investinglab.ports.errors import (
    ProviderDataError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)
from investinglab.ports.market_data import Dataset, ProviderCapabilities

if TYPE_CHECKING:
    from investinglab.domain.series import PriceSeries
    from investinglab.ports.market_data import BarsRequest

__all__ = ["CATALOGUE_FILE", "LocalFilesProvider"]

CATALOGUE_FILE: Final = "instruments.toml"
_SUFFIXES: Final = (".csv", ".parquet", ".pq")


class LocalFilesProvider:
    """Serves price series from a folder of files described by ``instruments.toml``.

    Args:
        directory: Folder with the price files and the catalogue.
        name: Provider slug (written in every series' provenance).

    Raises:
        DomainError: If the folder or the catalogue is missing or invalid.
    """

    def __init__(self, directory: str | Path, *, name: str = "files") -> None:
        self._directory = Path(directory)
        self._name = name
        self._importer = SeriesImporter()
        self._catalogue = self._load_catalogue()

    @property
    def name(self) -> str:
        """Provider slug."""
        return self._name

    @property
    def directory(self) -> Path:
        """Folder the files are read from."""
        return self._directory

    @property
    def symbols(self) -> tuple[str, ...]:
        """Symbols described in the catalogue."""
        return tuple(sorted(self._catalogue))

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Bars of the catalogue's symbols, at the frequencies declared for them, and their flow."""
        return ProviderCapabilities(
            datasets=frozenset({Dataset.BARS, Dataset.FLOW}),
            asset_classes=frozenset(AssetClass),
            frequencies=frozenset(spec.frequency for spec in self._catalogue.values()),
            identifiers="|".join(re.escape(symbol) for symbol in self.symbols) or "(?!)",
            cacheable=False,  # reading the file is as cheap as the cache, and never stale
        )

    async def fetch_bars(self, request: BarsRequest) -> PriceSeries:
        """Read the file of ``request.symbol`` and cut it to the requested dates.

        Raises:
            SymbolNotFoundError: If the symbol has no catalogue entry or no file.
            UnsupportedRequestError: If the file holds another frequency.
            ProviderDataError: If the file breaks any validation rule.
        """
        spec = self._catalogue.get(request.symbol)
        if spec is None:
            raise SymbolNotFoundError(self._name, f"{request.symbol} is not in {CATALOGUE_FILE}")
        if spec.frequency is not request.frequency:
            raise UnsupportedRequestError(
                self._name,
                f"{request.symbol} is stored at {spec.frequency.value}, "
                f"not {request.frequency.value}",
            )
        path = self._file_of(request.symbol)
        try:
            # Reading and validating a file blocks: keep it off the event loop.
            series = await asyncio.to_thread(self._importer.from_file, path, spec)
            if request.start is not None or request.end is not None:
                series = series.between(request.start, request.end)
        except (DomainError, InvalidSeriesError, OSError, ValueError) as error:
            raise ProviderDataError(self._name, f"{path.name}: {error}") from error
        return series

    async def fetch_flow(self, request: BarsRequest) -> FlowSeries:
        """The volume of the bars :meth:`fetch_bars` returns, as flow without aggressor side.

        A bar without volume is absent from the flow, never a zero.

        Raises:
            UnsupportedRequestError: If the file has no volume column.
            ProviderError: As :meth:`fetch_bars`.
        """
        series = await self.fetch_bars(request)
        if PriceField.VOLUME not in series.bars.columns:
            raise UnsupportedRequestError(self._name, f"{request.symbol}: the file has no volume")
        volume = series.bars[PriceField.VOLUME].dropna()
        try:
            return FlowSeries(
                series.instrument,
                series.frequency,
                series.source,
                volume.to_frame(FlowField.VOLUME.value),
            )
        except DomainError as error:
            raise ProviderDataError(self._name, f"{request.symbol}: {error}") from error

    def _file_of(self, symbol: str) -> Path:
        for suffix in _SUFFIXES:
            path = self._directory / f"{symbol}{suffix}"
            if path.is_file():
                return path
        raise SymbolNotFoundError(
            self._name, f"no {symbol}.csv or {symbol}.parquet in {self._directory}"
        )

    def _load_catalogue(self) -> dict[str, ImportSpec]:
        path = self._directory / CATALOGUE_FILE
        if not self._directory.is_dir():
            raise DomainError(f"Local data folder {self._directory} does not exist")
        if not path.is_file():
            raise DomainError(f"Local data folder {self._directory} has no {CATALOGUE_FILE}")
        try:
            raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise DomainError(f"{path} is not valid TOML: {error}") from error
        catalogue: dict[str, ImportSpec] = {}
        problems: list[str] = []
        for symbol, entry in raw.items():
            if not isinstance(entry, dict):
                problems.append(f"{symbol}: expected a table of fields")
                continue
            try:
                catalogue[symbol] = ImportSpec(symbol=symbol, provider=self._name, **entry)
            except ValidationError as error:
                details = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
                )
                problems.append(f"{symbol}: {details}")
        if problems:
            raise DomainError(f"Invalid {CATALOGUE_FILE}: " + " | ".join(problems))
        return catalogue
