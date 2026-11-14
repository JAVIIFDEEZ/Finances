"""Record CryptoWorld's indicators and patterns as parity fixtures (``just record-parity``).

The parity tests check that InvestingLab's indicators (``analytics/technical``) and price
patterns (``analytics/patterns``) give what CryptoWorld gives, so that a strategy keeps its
meaning when it moves platform. This script runs CryptoWorld's own code, never a copy of
it, on real recorded candles, with two parameter sets each (the lower end of the search
range and the middle):

* every indicator of ``strategy_spec``'s registry, on the daily Binance cassette
  ``binance/btc_usdt_1d_2025``;
* every pattern of ``price_patterns.PATTERNS``, on those daily candles and on the hourly
  ``binance/btc_usdt_1h_2026_10`` (the session patterns need intraday bars);
* the candles that only its screen had (``detect_candle_patterns``), on both. The screen
  only looks at the last five bars, so it is run on a window of five ending at each bar.

It needs CryptoWorld's pinned versions, in a throwaway environment that never touches the
project's (they are not dependencies of InvestingLab)::

    uv run just record-parity ../CryptoWorld

(the recipe runs this script with ``uv run --no-project --python 3.12`` and the three
pinned packages).

The outputs, ``tests/fixtures/parity/cryptoworld_indicators.json`` and
``cryptoworld_patterns.json``, are committed and never edited by hand.
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
HOURLY = "binance/btc_usdt_1h_2026_10"
OUTPUT = FIXTURES / "parity" / "cryptoworld_indicators.json"
PATTERNS_OUTPUT = FIXTURES / "parity" / "cryptoworld_patterns.json"
SCREEN = (
    "Inverted Hammer",
    "Morning Star",
    "Evening Star",
    "Three White Soldiers",
    "Three Black Crows",
)
"""The screen's candles that the strategy grammar does not have."""
SCREEN_WINDOW = 5
SIGNIFICANT = 15
"""Significant digits kept: well below any tolerance of the tests, half the file size."""


def _candles(name: str = CANDLES) -> Any:  # noqa: ANN401 - a DataFrame of CryptoWorld's environment
    """Open, high, low, close and volume of the recorded klines, oldest first."""
    import pandas as pd  # noqa: PLC0415 - only available in the throwaway environment

    cassette = json.loads((FIXTURES / "cassettes" / f"{name}.json").read_text("utf-8"))
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


def _patterns(name: str) -> dict[str, Any]:
    """What CryptoWorld's pattern detectors flag on one cassette's candles."""
    patterns = importlib.import_module("core.domain.services.price_patterns")
    screen = importlib.import_module("core.domain.services.technical_analysis_service")
    candles = _candles(name)
    frame = candles.assign(timestamp=candles["open_time"])  # its session patterns read it
    grammar = []
    for pattern, entry in patterns.PATTERNS.items():
        for params in _parameter_sets(entry.get("params", {})):
            flags = patterns.detect(frame.copy(), pattern, params)
            hits = [int(i) for i, flag in enumerate(flags) if flag]
            grammar.append({"name": pattern, "params": params, "hits": hits})
    found: dict[str, list[int]] = {candle: [] for candle in SCREEN}
    for end in range(SCREEN_WINDOW - 1, len(frame)):
        window = frame.iloc[end - SCREEN_WINDOW + 1 : end + 1].reset_index(drop=True)
        for hit in screen.detect_candle_patterns(window):
            if hit["index"] == -1 and hit["name"] in found:
                found[hit["name"]].append(end)
    return {
        "candles": name,
        "open_times": [int(t) for t in candles["open_time"]],
        "grammar": grammar,
        # The screen says nothing about the first bars: it needs five to look at.
        "screen": [
            {"name": candle, "from": SCREEN_WINDOW - 1, "hits": hits}
            for candle, hits in found.items()
        ],
    }


def main(source: Path) -> int:
    """Evaluate CryptoWorld's indicators and patterns and write the parity fixtures."""
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
    series = [_patterns(CANDLES), _patterns(HOURLY)]
    patterns = {
        "purpose": "Bars CryptoWorld's price patterns flag, for the parity tests.",
        "source": [
            "core.domain.services.price_patterns.PATTERNS",
            "core.domain.services.technical_analysis_service.detect_candle_patterns",
        ],
        "cryptoworld": fixture["cryptoworld"],
        "versions": fixture["versions"],
        "series": series,
    }
    PATTERNS_OUTPUT.write_text(json.dumps(patterns, separators=(",", ":")) + "\n", "utf-8")
    cases = sum(len(entry["grammar"]) + len(entry["screen"]) for entry in series)
    print(f"{cases} pattern cases over {len(series)} series -> {PATTERNS_OUTPUT}")  # noqa: T201
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="CryptoWorld's backend/src folder")
    sys.exit(main(parser.parse_args().source.resolve()))
