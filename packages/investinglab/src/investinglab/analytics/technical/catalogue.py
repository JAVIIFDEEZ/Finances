"""The indicator catalogue of CryptoWorld's strategy grammar, on any price series (ADR-0034).

Each entry has CryptoWorld's name (``RSI``, ``BB_UPPER``...), the price columns it needs,
its parameters with their search ranges and the threshold range of the oscillators. The
values are those CryptoWorld's ``strategy_spec`` computed with the ``ta`` library (checked
by the parity tests), including its choices for strategies: the stochastic RSI in percent,
the ATR as a percentage of the close, and the Donchian and Fibonacci levels of the bar
before, so that a close can break them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

import pandas as pd

from investinglab.analytics.technical import averages, oscillators, trend, volatility, volume

__all__ = ["CATALOGUE", "Column", "Indicator", "Parameter", "compute"]


class Column(StrEnum):
    """Price columns an indicator or a price pattern reads."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


@dataclass(frozen=True, slots=True)
class Parameter:
    """A parameter of an indicator: integer or real, its search range and its default."""

    low: float
    high: float
    default: float
    integer: bool = True

    def __post_init__(self) -> None:
        if not self.low <= self.default <= self.high:
            raise ValueError(f"default {self.default} outside [{self.low}, {self.high}]")

    def check(self, name: str, value: float) -> float:
        """The value, if it is valid for this parameter.

        Raises:
            ValueError: A non-integer value for an integer parameter, or one below 1 (windows)
                or not positive (steps, ratios).
        """
        if self.integer and float(value) != int(value):
            raise ValueError(f"{name} must be a whole number, got {value}")
        if (self.integer and value < 1) or (not self.integer and value <= 0):
            raise ValueError(f"{name} must be positive, got {value}")
        return int(value) if self.integer else float(value)


type Bars = Mapping[str, pd.Series]
type Compute = Callable[[Bars, Mapping[str, float]], pd.Series]


@dataclass(frozen=True, slots=True)
class Indicator:
    """One indicator of the catalogue.

    Attributes:
        name: CryptoWorld's name.
        columns: Price columns it needs.
        parameters: Parameters by name.
        compute: Values for the bars and the parameters.
        threshold: Range of meaningful thresholds of an oscillator; ``None`` for a level in
            price units (averages, bands), compared with the price instead.
    """

    name: str
    columns: frozenset[Column]
    parameters: Mapping[str, Parameter]
    compute: Compute = field(repr=False)
    threshold: tuple[float, float] | None = None

    @property
    def defaults(self) -> dict[str, float]:
        """The default value of every parameter."""
        return {name: parameter.default for name, parameter in self.parameters.items()}


def _window(low: int, high: int, default: int) -> dict[str, Parameter]:
    return {"window": Parameter(low, high, default)}


def _w(params: Mapping[str, float]) -> int:
    return int(params["window"])


def _previous(values: pd.Series) -> pd.Series:
    """The value of the bar before: a level a close can break (CryptoWorld's ``_shift1``)."""
    return values.shift(1)


HLC: Final = frozenset({Column.HIGH, Column.LOW, Column.CLOSE})
CLOSE: Final = frozenset({Column.CLOSE})
HL: Final = frozenset({Column.HIGH, Column.LOW})
HLCV: Final = frozenset({Column.HIGH, Column.LOW, Column.CLOSE, Column.VOLUME})


def _fibonacci(bars: Bars, params: Mapping[str, float]) -> pd.Series:
    window = _w(params)
    top = bars["high"].rolling(window, min_periods=window).max()
    bottom = bars["low"].rolling(window, min_periods=window).min()
    return _previous(top - float(params["ratio"]) * (top - bottom))


def _entries() -> list[Indicator]:
    macd_params = {
        "fast": Parameter(8, 16, 12),
        "slow": Parameter(20, 34, 26),
        "signal": Parameter(6, 12, 9),
    }
    bands = {"window": Parameter(10, 40, 20), "dev": Parameter(1.5, 3.0, 2.0, integer=False)}
    return [
        Indicator(
            "RSI",
            CLOSE,
            _window(7, 21, 14),
            lambda b, p: oscillators.rsi(b["close"], _w(p)),
            (15.0, 85.0),
        ),
        Indicator(
            "STOCHRSI",
            CLOSE,
            _window(7, 21, 14),
            lambda b, p: 100.0 * oscillators.stoch_rsi(b["close"], _w(p)),
            (10.0, 90.0),
        ),
        Indicator(
            "CCI",
            HLC,
            _window(14, 30, 20),
            lambda b, p: oscillators.cci(b["high"], b["low"], b["close"], _w(p)),
            (-150.0, 150.0),
        ),
        Indicator(
            "WILLR",
            HLC,
            _window(10, 21, 14),
            lambda b, p: oscillators.williams_r(b["high"], b["low"], b["close"], _w(p)),
            (-90.0, -10.0),
        ),
        Indicator(
            "ADX",
            HLC,
            _window(10, 30, 14),
            lambda b, p: trend.adx(b["high"], b["low"], b["close"], _w(p))["adx"],
            (15.0, 40.0),
        ),
        Indicator(
            "MFI",
            HLCV,
            _window(10, 21, 14),
            lambda b, p: volume.mfi(b["high"], b["low"], b["close"], b["volume"], _w(p)),
            (15.0, 85.0),
        ),
        Indicator(
            "CMF",
            HLCV,
            _window(14, 30, 20),
            lambda b, p: volume.cmf(b["high"], b["low"], b["close"], b["volume"], _w(p)),
            (-0.3, 0.3),
        ),
        Indicator(
            "VOLRATIO",
            frozenset({Column.VOLUME}),
            _window(10, 30, 20),
            lambda b, p: volume.volume_ratio(b["volume"], _w(p)),
            (0.7, 2.5),
        ),
        Indicator(
            "STOCH",
            HLC,
            _window(10, 21, 14),
            lambda b, p: oscillators.stochastic(b["high"], b["low"], b["close"], _w(p)),
            (10.0, 90.0),
        ),
        Indicator(
            "ROC",
            CLOSE,
            _window(5, 30, 12),
            lambda b, p: oscillators.roc(b["close"], _w(p)),
            (-10.0, 10.0),
        ),
        Indicator(
            "ATR_PCT",
            HLC,
            _window(7, 30, 14),
            lambda b, p: volatility.atr(b["high"], b["low"], b["close"], _w(p)) / b["close"] * 100,
            (0.5, 8.0),
        ),
        Indicator(
            "AROON",
            HL,
            _window(14, 30, 25),
            lambda b, p: oscillators.aroon(b["high"], b["low"], _w(p))["oscillator"],
            (-80.0, 80.0),
        ),
        Indicator(
            "TRIX",
            CLOSE,
            _window(9, 20, 15),
            lambda b, p: oscillators.trix(b["close"], _w(p)),
            (-0.3, 0.3),
        ),
        Indicator("PRICE", CLOSE, {}, lambda b, p: b["close"].astype(float)),
        Indicator("SMA", CLOSE, _window(5, 200, 50), lambda b, p: averages.sma(b["close"], _w(p))),
        Indicator("EMA", CLOSE, _window(5, 200, 21), lambda b, p: averages.ema(b["close"], _w(p))),
        Indicator("WMA", CLOSE, _window(5, 100, 20), lambda b, p: averages.wma(b["close"], _w(p))),
        Indicator("HMA", CLOSE, _window(8, 80, 20), lambda b, p: averages.hull(b["close"], _w(p))),
        Indicator("KAMA", CLOSE, _window(8, 30, 10), lambda b, p: averages.kama(b["close"], _w(p))),
        Indicator(
            "BB_UPPER",
            CLOSE,
            bands,
            lambda b, p: volatility.bollinger(b["close"], _w(p), float(p["dev"]))["upper"],
        ),
        Indicator(
            "BB_LOWER",
            CLOSE,
            bands,
            lambda b, p: volatility.bollinger(b["close"], _w(p), float(p["dev"]))["lower"],
        ),
        Indicator(
            "MACD_LINE",
            CLOSE,
            macd_params,
            lambda b, p: oscillators.macd(
                b["close"], int(p["fast"]), int(p["slow"]), int(p["signal"])
            )["line"],
        ),
        Indicator(
            "MACD_SIGNAL",
            CLOSE,
            macd_params,
            lambda b, p: oscillators.macd(
                b["close"], int(p["fast"]), int(p["slow"]), int(p["signal"])
            )["signal"],
        ),
        Indicator(
            "ICHI_CONV",
            HL,
            _window(7, 12, 9),
            lambda b, p: trend.ichimoku(b["high"], b["low"], conversion=_w(p))["conversion"],
        ),
        Indicator(
            "ICHI_BASE",
            HL,
            _window(20, 34, 26),
            lambda b, p: trend.ichimoku(b["high"], b["low"], base=_w(p))["base"],
        ),
        Indicator(
            "PSAR",
            HLC,
            {
                "step": Parameter(0.01, 0.05, 0.02, integer=False),
                "max_step": Parameter(0.1, 0.3, 0.2, integer=False),
            },
            lambda b, p: trend.psar(
                b["high"], b["low"], b["close"], float(p["step"]), float(p["max_step"])
            ),
        ),
        Indicator(
            "DONCH_UPPER",
            HL,
            _window(10, 60, 20),
            lambda b, p: _previous(volatility.donchian(b["high"], b["low"], _w(p))["upper"]),
        ),
        Indicator(
            "DONCH_LOWER",
            HL,
            _window(10, 60, 20),
            lambda b, p: _previous(volatility.donchian(b["high"], b["low"], _w(p))["lower"]),
        ),
        Indicator(
            "KELT_UPPER",
            HLC,
            _window(10, 40, 20),
            lambda b, p: volatility.keltner(b["high"], b["low"], b["close"], _w(p))["upper"],
        ),
        Indicator(
            "KELT_LOWER",
            HLC,
            _window(10, 40, 20),
            lambda b, p: volatility.keltner(b["high"], b["low"], b["close"], _w(p))["lower"],
        ),
        Indicator(
            "FIB_RETR",
            HL,
            {
                "window": Parameter(30, 120, 60),
                "ratio": Parameter(0.38, 0.62, 0.5, integer=False),
            },
            _fibonacci,
        ),
    ]


CATALOGUE: Final[Mapping[str, Indicator]] = MappingProxyType(
    {indicator.name: indicator for indicator in _entries()}
)
"""Every indicator of the catalogue by name."""


def compute(name: str, bars: Bars, **params: float) -> pd.Series:
    """Values of indicator ``name`` over ``bars`` (columns by name), defaults filled in.

    Raises:
        KeyError: An unknown indicator, or a price column it needs is missing.
        ValueError: An unknown or invalid parameter.
    """
    indicator = CATALOGUE.get(name)
    if indicator is None:
        raise KeyError(f"unknown indicator {name!r}; known: {sorted(CATALOGUE)}")
    missing = sorted(column.value for column in indicator.columns if column.value not in bars)
    if missing:
        raise KeyError(f"{name} needs the {missing} columns")
    unknown = sorted(set(params) - set(indicator.parameters))
    if unknown:
        raise ValueError(f"{name} has no parameters {unknown}")
    values = {
        key: parameter.check(key, params.get(key, parameter.default))
        for key, parameter in indicator.parameters.items()
    }
    return indicator.compute(bars, values).rename(name)
