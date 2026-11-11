"""Write SYNTHETIC price files for the end-to-end tests (never market data).

Usage: ``uv run python e2e/synthetic_data.py <folder>``. Each series is a seeded geometric
Brownian motion; the catalogue names every instrument "Synthetic …" so nobody can take the
numbers for real prices.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

INSTRUMENTS = {
    # symbol: (name, currency, exchange, asset class, annual drift, annual volatility)
    "SAN.MC": ("Synthetic Santander", "EUR", "XMAD", "equity", 0.07, 0.30),
    "ITX.MC": ("Synthetic Inditex", "EUR", "XMAD", "equity", 0.08, 0.25),
    "IBE.MC": ("Synthetic Iberdrola", "EUR", "XMAD", "equity", 0.06, 0.20),
    "BBVA.MC": ("Synthetic BBVA", "EUR", "XMAD", "equity", 0.07, 0.32),
    "^IBEX": ("Synthetic IBEX 35", "EUR", "XMAD", "index", 0.05, 0.18),
    "^GDAXI": ("Synthetic DAX", "EUR", "XETR", "index", 0.06, 0.18),
    "^GSPC": ("Synthetic S&P 500", "USD", "XNYS", "index", 0.08, 0.17),
    "EURUSD=X": ("Synthetic EUR/USD", "USD", "FX", "fx", 0.0, 0.07),
    "BTC-USD": ("Synthetic Bitcoin", "USD", "CRYPTO", "crypto", 0.20, 0.60),
}


def main(folder: Path) -> None:
    """Write one CSV per instrument and the ``instruments.toml`` catalogue into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1_600)
    catalogue = []
    for seed, (symbol, (name, currency, exchange, asset_class, mu, sigma)) in enumerate(
        INSTRUMENTS.items()
    ):
        rng = np.random.default_rng(seed + 1)
        shocks = rng.normal((mu - sigma**2 / 2) / 252, sigma / np.sqrt(252), len(days))
        start = 1.1 if asset_class == "fx" else 100.0
        prices = start * np.exp(np.cumsum(shocks))
        pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "Close": prices}).to_csv(
            folder / f"{symbol}.csv", index=False
        )
        catalogue.append(
            f'["{symbol}"]\nname = "{name}"\ncurrency = "{currency}"\n'
            f'exchange = "{exchange}"\nasset_class = "{asset_class}"\n'
        )
    (folder / "instruments.toml").write_text("\n".join(catalogue), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
