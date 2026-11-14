"""Technical indicators on any price series: averages, oscillators, trend, volatility, volume.

Pure, causal functions over pandas series (ADR-0034): no domain types, no I/O. Their
definitions follow the ``ta`` library CryptoWorld used, so that its strategies keep their
meaning, except that a value is never made up during warm-up (``NaN`` instead of zeros or
partial windows). :mod:`~investinglab.analytics.technical.catalogue` exposes them under
CryptoWorld's names with their parameter ranges.
"""

from investinglab.analytics.technical.averages import ema, hull, kama, sma, wma
from investinglab.analytics.technical.catalogue import (
    CATALOGUE,
    Column,
    Indicator,
    Parameter,
    compute,
)
from investinglab.analytics.technical.oscillators import (
    aroon,
    cci,
    macd,
    roc,
    rsi,
    stoch_rsi,
    stochastic,
    trix,
    williams_r,
)
from investinglab.analytics.technical.trend import adx, ichimoku, psar
from investinglab.analytics.technical.volatility import (
    atr,
    bollinger,
    donchian,
    keltner,
    true_range,
)
from investinglab.analytics.technical.volume import cmf, mfi, volume_ratio

__all__ = [
    "CATALOGUE",
    "Column",
    "Indicator",
    "Parameter",
    "adx",
    "aroon",
    "atr",
    "bollinger",
    "cci",
    "cmf",
    "compute",
    "donchian",
    "ema",
    "hull",
    "ichimoku",
    "kama",
    "keltner",
    "macd",
    "mfi",
    "psar",
    "roc",
    "rsi",
    "sma",
    "stoch_rsi",
    "stochastic",
    "trix",
    "true_range",
    "volume_ratio",
    "williams_r",
    "wma",
]
