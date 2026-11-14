"""Write SYNTHETIC price files for the end-to-end tests (never market data).

Usage: ``uv run python e2e/synthetic_data.py <folder>``. Each series is a seeded geometric
Brownian motion with a seeded log-normal volume (none for currency pairs); a few also have
seeded opens, highs and lows (``WITH_RANGE``), so that both the price patterns and the
"cannot have" path are exercised. The catalogue names every instrument "Synthetic …" so
nobody can take the numbers for real prices.
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
WITH_RANGE = frozenset({"SAN.MC", "^GSPC", "BTC-USD"})
"""Instruments whose files also have open, high and low; the rest are closes only."""


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
        columns = {"Date": days.strftime("%Y-%m-%d"), "Close": prices}
        if asset_class != "fx":  # currency pairs have no volume
            columns["Volume"] = np.round(rng.lognormal(13.0, 0.4, len(days)))
        if symbol in WITH_RANGE:  # drawn last: the closes and volumes stay the same
            gap = rng.normal(0.0, sigma / np.sqrt(252) / 4, len(days))
            opens = np.concatenate([[start], prices[:-1]]) * np.exp(gap)
            reach = np.abs(rng.normal(0.0, sigma / np.sqrt(252) / 2, (2, len(days))))
            columns["Open"] = opens
            columns["High"] = np.maximum(opens, prices) * (1 + reach[0])
            columns["Low"] = np.minimum(opens, prices) * (1 - reach[1])
        pd.DataFrame(columns).to_csv(folder / f"{symbol}.csv", index=False)
        catalogue.append(
            f'["{symbol}"]\nname = "{name}"\ncurrency = "{currency}"\n'
            f'exchange = "{exchange}"\nasset_class = "{asset_class}"\n'
        )
    (folder / "instruments.toml").write_text("\n".join(catalogue), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
