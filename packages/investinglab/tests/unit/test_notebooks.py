"""The demo notebook stays runnable and is committed without outputs.

It runs here against SYNTHETIC files written to a temporary folder (labelled as synthetic and
never committed): the test proves the code works, not any market result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import matplotlib as mpl
import pandas as pd
import pytest

from investinglab.config import get_settings
from support.factories import business_days, gbm_prices

if TYPE_CHECKING:
    from collections.abc import Iterator

NOTEBOOKS = Path(__file__).resolve().parents[4] / "notebooks"
DEMO = NOTEBOOKS / "b1_toolkit_demo.ipynb"
SYMBOLS = ("SAN.MC", "ITX.MC", "IBE.MC", "BBVA.MC")


def _cells(path: Path) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["cells"]
    return cells


def test_notebooks_are_committed_without_outputs() -> None:
    for path in sorted(NOTEBOOKS.glob("*.ipynb")):
        for cell in _cells(path):
            if cell["cell_type"] == "code":
                assert cell["outputs"] == [], f"{path.name} has outputs: clear them"
                assert cell["execution_count"] is None


@pytest.fixture
def synthetic_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    folder = tmp_path / "synthetic-data"
    folder.mkdir()
    index = business_days(1_000, start="2019-01-02")
    catalogue = []
    for seed, symbol in enumerate(SYMBOLS, start=1):
        prices = gbm_prices(len(index), seed=seed)
        pd.DataFrame({"Date": index.strftime("%Y-%m-%d"), "Close": prices}).to_csv(
            folder / f"{symbol}.csv", index=False
        )
        catalogue.append(
            f'["{symbol}"]\nname = "Synthetic {symbol}"\ncurrency = "EUR"\nexchange = "XMAD"\n'
        )
    (folder / "instruments.toml").write_text("\n".join(catalogue), encoding="utf-8")
    monkeypatch.setenv("INVESTINGLAB_LOCAL_DATA_DIR", str(folder))
    monkeypatch.setenv("INVESTINGLAB_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    mpl.use("Agg")
    yield folder
    get_settings.cache_clear()


def test_the_demo_notebook_runs_end_to_end(synthetic_folder: Path) -> None:
    namespace: dict[str, Any] = {"__name__": "__notebook__"}

    for number, cell in enumerate(_cells(DEMO)):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        exec(compile(source, f"{DEMO.name}[{number}]", "exec"), namespace)  # noqa: S102

    assert namespace["batch"].ok
    assert namespace["cartera"].symbols == SYMBOLS
    assert "## Diagnósticos y advertencias" in namespace["informe"]
    assert set(namespace["graficos"]) >= {"growth", "correlation", "risk_contribution"}
    assert Path("salidas/cartera.md").is_file()
    assert (
        Path("salidas/portfolio.md")
        .read_text(encoding="utf-8")
        .startswith("# Núcleo portfolio report")
    )
