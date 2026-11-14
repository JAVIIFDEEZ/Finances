from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytest

from investinglab.adapters.files import SeriesImporter
from investinglab.adapters.providers.files import CATALOGUE_FILE, LocalFilesProvider
from investinglab.domain import AssetClass, DomainError, Frequency
from investinglab.ports import (
    BarsRequest,
    Dataset,
    MarketDataProvider,
    ProviderDataError,
    SymbolNotFoundError,
    TradeFlowProvider,
    UnsupportedRequestError,
)
from support.factories import business_days, gbm_prices

if TYPE_CHECKING:
    from pathlib import Path

    from investinglab.domain import PriceSeries

CATALOGUE = """
["SYN.MC"]
name = "Synthetic Madrid"
currency = "EUR"
exchange = "XMAD"
adjustment = "splits_and_dividends"

["SYN.W"]
currency = "USD"
frequency = "1w"
"""


def _folder(tmp_path: Path, catalogue: str = CATALOGUE) -> Path:
    index = business_days(60)
    prices = gbm_prices(60)
    frame = pd.DataFrame({"Date": index.strftime("%Y-%m-%d"), "Close": prices})
    frame.to_csv(tmp_path / "SYN.MC.csv", index=False)
    (tmp_path / CATALOGUE_FILE).write_text(catalogue, encoding="utf-8")
    return tmp_path


async def test_serves_the_catalogued_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LocalFilesProvider(_folder(tmp_path))
    threads: list[str] = []
    read = SeriesImporter.from_file

    def recording(self: SeriesImporter, *args: Any, **kwargs: Any) -> PriceSeries:
        threads.append(threading.current_thread().name)
        return read(self, *args, **kwargs)

    monkeypatch.setattr(SeriesImporter, "from_file", recording)

    series = await provider.fetch_bars(BarsRequest("SYN.MC", start=business_days(60)[10].date()))

    assert threads
    assert threading.current_thread().name not in threads  # file I/O off the event loop

    assert isinstance(provider, MarketDataProvider)
    assert provider.name == "files"
    assert provider.directory == tmp_path
    assert provider.symbols == ("SYN.MC", "SYN.W")
    assert series.name == "Synthetic Madrid"
    assert series.source.provider == "files"
    assert series.source.dataset == "SYN.MC.csv"
    assert len(series) == 50
    capabilities = provider.capabilities
    assert capabilities.frequencies == frozenset({Frequency.DAY_1, Frequency.WEEK_1})
    assert AssetClass.CRYPTO in capabilities.asset_classes
    assert capabilities.serves("SYN.MC")
    assert not capabilities.serves("SYNXMC")  # the dot is literal
    assert not capabilities.serves("SAN.MC")  # only the catalogue is served
    assert not capabilities.cacheable  # an edited file must be seen at once


async def test_unknown_symbols_and_missing_files(tmp_path: Path) -> None:
    provider = LocalFilesProvider(_folder(tmp_path))

    with pytest.raises(SymbolNotFoundError, match=r"not in instruments\.toml"):
        await provider.fetch_bars(BarsRequest("NOPE"))
    with pytest.raises(SymbolNotFoundError, match=r"no SYN\.W\.csv or SYN\.W\.parquet"):
        await provider.fetch_bars(BarsRequest("SYN.W", Frequency.WEEK_1))


async def test_other_frequencies_are_not_invented(tmp_path: Path) -> None:
    provider = LocalFilesProvider(_folder(tmp_path))

    with pytest.raises(UnsupportedRequestError, match="stored at 1d, not 1w"):
        await provider.fetch_bars(BarsRequest("SYN.MC", Frequency.WEEK_1))


async def test_invalid_files_become_provider_data_errors(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    (folder / "SYN.MC.csv").write_text("Date,Close\n2024-01-02,-1\n2024-01-03,1\n2024-01-04,1\n")
    provider = LocalFilesProvider(folder)

    with pytest.raises(ProviderDataError, match=r"SYN\.MC\.csv"):
        await provider.fetch_bars(BarsRequest("SYN.MC"))


@pytest.mark.parametrize(
    ("catalogue", "message"),
    [
        ("not toml [", "not valid TOML"),
        ('SYN = "x"', "expected a table"),
        ('["SYN"]\ncurrency = "XYZ"', "XYZ"),
        ('["SYN"]\ncurrency = "EUR"\nexchange = "MOON"', "unknown exchange"),
    ],
)
def test_invalid_catalogues_are_rejected(tmp_path: Path, catalogue: str, message: str) -> None:
    with pytest.raises(DomainError, match=message):
        LocalFilesProvider(_folder(tmp_path, catalogue))


def test_the_folder_and_catalogue_must_exist(tmp_path: Path) -> None:
    with pytest.raises(DomainError, match="does not exist"):
        LocalFilesProvider(tmp_path / "missing")
    with pytest.raises(DomainError, match=r"has no instruments\.toml"):
        LocalFilesProvider(tmp_path)


async def test_a_file_with_volume_serves_it_as_flow(tmp_path: Path) -> None:
    index = business_days(30)
    volume = [float(1_000 + day) for day in range(30)]
    volume[4] = float("nan")  # a session without a reported volume
    pd.DataFrame(
        {"Date": index.strftime("%Y-%m-%d"), "Close": gbm_prices(30), "Volume": volume}
    ).to_csv(tmp_path / "SYN.MC.csv", index=False)
    (tmp_path / CATALOGUE_FILE).write_text(CATALOGUE, encoding="utf-8")
    provider = LocalFilesProvider(tmp_path)

    flow = await provider.fetch_flow(BarsRequest("SYN.MC"))

    assert isinstance(provider, TradeFlowProvider)
    assert Dataset.FLOW in provider.capabilities.datasets
    assert len(flow) == 29  # absent, never a zero
    assert flow.volume.iloc[0] == 1_000.0
    assert not flow.has_aggressor_side
    assert flow.source.provider == "files"


async def test_a_file_without_volume_has_no_flow(tmp_path: Path) -> None:
    provider = LocalFilesProvider(_folder(tmp_path))

    with pytest.raises(UnsupportedRequestError, match="has no volume"):
        await provider.fetch_flow(BarsRequest("SYN.MC"))


async def test_a_volume_that_breaks_the_rules_is_a_data_error(tmp_path: Path) -> None:
    index = business_days(30)
    volume = [float("nan")] * 28 + [1.0, 2.0]  # two sessions with volume: too few
    pd.DataFrame(
        {"Date": index.strftime("%Y-%m-%d"), "Close": gbm_prices(30), "Volume": volume}
    ).to_csv(tmp_path / "SYN.MC.csv", index=False)
    (tmp_path / CATALOGUE_FILE).write_text(CATALOGUE, encoding="utf-8")

    with pytest.raises(ProviderDataError, match="at least 3 observations"):
        await LocalFilesProvider(tmp_path).fetch_flow(BarsRequest("SYN.MC"))
