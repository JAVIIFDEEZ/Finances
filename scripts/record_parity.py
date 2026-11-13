"""Record CryptoWorld's indicator values as parity fixtures (``just record-parity <path>``).

The parity tests check that InvestingLab's indicators (``analytics/technical``) give the
values CryptoWorld's strategy grammar gives, so that a strategy keeps its meaning when it
moves platform. This script runs CryptoWorld's own code, never a copy of it: it imports
``core.domain.services.strategy_spec`` from a CryptoWorld checkout and evaluates every
indicator of its registry on real recorded candles (the Binance cassette
``binance/btc_usdt_1d_2025``), with two parameter sets each: the lower end of its search
range and the middle.

It needs CryptoWorld's pinned versions, in a throwaway environment that never touches the
project's (they are not dependencies of InvestingLab)::

    uv run just record-parity ../CryptoWorld

(the recipe runs this script with ``uv run --no-project --python 3.12`` and the three
pinned packages).

The output, ``tests/fixtures/parity/cryptoworld_indicators.json``, is committed and never
edited by hand.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "packages/investinglab/tests/fixtures"
CANDLES = "binance/btc_usdt_1d_2025"
OUTPUT = FIXTURES / "parity" / "cryptoworld_indicators.json"
SIGNIFICANT = 15
"""Significant digits kept: well below any tolerance of the tests, half the file size."""


def _candles() -> Any:  # noqa: ANN401 - a pandas DataFrame of CryptoWorld's environment
    """Open, high, low, close and volume of the recorded klines, oldest first."""
    import pandas as pd  # noqa: PLC0415 - only available in the throwaway environment

    cassette = json.loads((FIXTURES / "cassettes" / f"{CANDLES}.json").read_text("utf-8"))
    rows = [row for exchange in cassette["exchanges"] for row in exchange["json"]]
    frame = pd.DataFrame(
        {
            "open_time": [int(row[0]) for row in rows],
            "open": [float(row[1]) for row in rows],
            "high": [float(row[2]) for row in rows],
            "low": [float(row[3]) for row in rows],
            "close": [float(row[4]) for row in rows],
            "volume": [float(row[5]) for row in rows],
        }
    )
    return frame.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def _parameter_sets(spec: dict[str, tuple[str, float, float]]) -> list[dict[str, float]]:
    """The lower end of every range and the middle (rounded as CryptoWorld samples them)."""
    low = {name: (int(lo) if kind == "int" else float(lo)) for name, (kind, lo, _) in spec.items()}
    middle = {
        name: ((int(lo) + int(hi)) // 2 if kind == "int" else round((lo + hi) / 2, 3))
        for name, (kind, lo, hi) in spec.items()
    }
    return [low] if low == middle else [low, middle]


def _number(value: float) -> float | None:
    return None if math.isnan(value) or math.isinf(value) else float(f"{value:.{SIGNIFICANT}g}")


def _commit(path: Path) -> str:
    done = subprocess.run(  # noqa: S603 - fixed git command on the given checkout
        ["git", "-C", str(path), "rev-parse", "--short=12", "HEAD"],  # noqa: S607 - git on PATH
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or "unknown"


def main(source: Path) -> int:
    """Evaluate CryptoWorld's indicators and write the parity fixture."""
    sys.path.insert(0, str(source))
    spec = importlib.import_module("core.domain.services.strategy_spec")
    registry: dict[str, dict[str, Any]] = spec._ALL  # noqa: SLF001 - CryptoWorld's registry
    candles = _candles()
    indicators = []
    for name, entry in registry.items():
        for params in _parameter_sets(entry.get("params", {})):
            values = entry["compute"](candles.copy(), params)
            indicators.append(
                {"name": name, "params": params, "values": [_number(v) for v in values]}
            )
    fixture = {
        "purpose": "Values of CryptoWorld's strategy indicators, for the parity tests.",
        "source": "core.domain.services.strategy_spec._ALL",
        "cryptoworld": f"JAVIIFDEEZ/CryptoWorld@{_commit(source)}",
        "versions": {
            package: importlib.metadata.version(package) for package in ("ta", "pandas", "numpy")
        },
        "candles": CANDLES,
        "open_times": [int(t) for t in candles["open_time"]],
        "indicators": indicators,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(fixture, indent=None, separators=(",", ":")) + "\n", "utf-8")
    print(f"{len(indicators)} indicator series over {len(candles)} candles -> {OUTPUT}")  # noqa: T201
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="CryptoWorld's backend/src folder")
    sys.exit(main(parser.parse_args().source.resolve()))
