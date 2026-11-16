"""The panel of conventional rules, the trend state and the confluence across timeframes.

Three descriptions of a series as of its last bar (ADR-0038), following CryptoWorld's
signals dashboard and confluence card (checked by the parity tests):

* The **signal panel** applies eleven textbook rules and says which way each one points.
  They are of two opposite styles, and the panel keeps them apart: *trend* rules follow the
  move (the close above an average, the MACD above its signal, +DI above -DI with an ADX
  over 25) and *reversal* rules fade it (an RSI over 70 points down). In a strong trend
  they disagree by construction, so the net score alone hides what the two counts show.
* The **trend state** places the close against a long average and reads the slope of a
  medium one: up, down or sideways.
* The **confluence** weighs the panel scores of several timeframes (coarser frames weigh
  more) and says whether they agree.

A rule's direction is what the rule says, not a forecast: whether any of them anticipates
anything is for the validation of a strategy to measure. A rule that cannot be computed (a
series without highs and lows, too few bars) is left out and named, never guessed; an exact
tie is neutral.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import numpy as np

from investinglab.analytics.technical.averages import ema, sma
from investinglab.analytics.technical.oscillators import cci, macd, rsi, stoch_rsi, williams_r
from investinglab.analytics.technical.trend import adx
from investinglab.analytics.technical.volatility import bollinger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pandas as pd

__all__ = [
    "AGREEMENT_MIN",
    "ALIGNMENT_MIN",
    "MIN_FRAMES",
    "RULES",
    "UNDEFINED",
    "Bias",
    "Confluence",
    "ConfluenceVerdict",
    "PanelVerdict",
    "RuleReading",
    "SignalPanel",
    "Style",
    "TrendDirection",
    "TrendState",
    "confluence",
    "signal_panel",
    "trend_state",
]


class Bias(StrEnum):
    """The way a rule points."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Style(StrEnum):
    """What a rule does with a move: follow it or fade it."""

    TREND = "trend"
    REVERSAL = "reversal"


class PanelVerdict(StrEnum):
    """The net of the panel: the mean of its rules (+1 bullish, -1 bearish)."""

    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


class TrendDirection(StrEnum):
    """The background trend."""

    UP = "up"
    DOWN = "down"
    SIDEWAYS = "sideways"


class ConfluenceVerdict(StrEnum):
    """Whether the timeframes agree."""

    ALIGNED_BULLISH = "aligned_bullish"
    ALIGNED_BEARISH = "aligned_bearish"
    MIXED = "mixed"
    """A direction dominates but too few frames share it: the riskiest situation."""
    NEUTRAL = "neutral"
    INSUFFICIENT = "insufficient"
    """Fewer than two frames could be read: one opinion is not a consensus."""


RULES: Final = MappingProxyType(
    {
        "RSI": (Style.REVERSAL, {"window": 14}),
        "MACD": (Style.TREND, {"fast": 12, "slow": 26, "signal": 9}),
        "SMA_20": (Style.TREND, {"window": 20}),
        "SMA_50": (Style.TREND, {"window": 50}),
        "EMA_12": (Style.TREND, {"window": 12}),
        "EMA_26": (Style.TREND, {"window": 26}),
        "BOLLINGER": (Style.REVERSAL, {"window": 20, "deviations": 2}),
        "STOCH_RSI": (Style.REVERSAL, {"window": 14, "smooth": 3}),
        "ADX": (Style.TREND, {"window": 14}),
        "CCI": (Style.REVERSAL, {"window": 20}),
        "WILLR": (Style.REVERSAL, {"window": 14}),
    }
)
"""The rules of the panel, in order, with their style and parameters."""

STRONG: Final = 0.5
"""Net score beyond which the panel's verdict is strong."""
ADX_TREND: Final = 25.0
"""Wilder's ADX above which the directional lines are read."""
SLOPE_PCT: Final = 0.3
"""Slope of the medium average, in percent over the look-back, that counts as a trend."""
SLOPE_BARS: Final = 10
ALIGNMENT_MIN: Final = 0.15
"""Weighted score below which the frames have no direction."""
AGREEMENT_MIN: Final = 0.75
"""Share of the frames that must point the dominant way to call them aligned."""
MIN_FRAMES: Final = 2
UNDEFINED: Final = "undefined"
"""What a rule lacks when its bars give it no value."""


@dataclass(frozen=True, slots=True)
class RuleReading:
    """What one rule says on the last bar.

    Attributes:
        name: The rule (a key of :data:`RULES`).
        style: Trend-following or reversal.
        bias: The way it points.
        values: The figures it compared (``{"rsi": 71.2}``, ``{"macd": 0.4, "signal": 0.1}``).
        parameters: Its parameters.
    """

    name: str
    style: Style
    bias: Bias
    values: Mapping[str, float]
    parameters: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class SignalPanel:
    """The rules that could be read on the last bar, and those that could not.

    Attributes:
        rules: One reading per rule, in the order of :data:`RULES`.
        skipped: Rules left out, with what they lack: price columns, or ``"undefined"``
            when the bars give them no value (too few of them, or a price that never moves).
    """

    rules: tuple[RuleReading, ...]
    skipped: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def count(self, bias: Bias, style: Style | None = None) -> int:
        """Rules pointing ``bias`` (of one style, or of both)."""
        return sum(
            rule.bias is bias and (style is None or rule.style is style) for rule in self.rules
        )

    @property
    def total(self) -> int:
        """Rules read."""
        return len(self.rules)

    @property
    def bullish(self) -> int:
        """Rules pointing up."""
        return self.count(Bias.BULLISH)

    @property
    def bearish(self) -> int:
        """Rules pointing down."""
        return self.count(Bias.BEARISH)

    @property
    def neutral(self) -> int:
        """Rules pointing nowhere."""
        return self.count(Bias.NEUTRAL)

    def score_of(self, style: Style | None = None) -> float | None:
        """Mean of the rules (+1 bullish, -1 bearish, 0 neutral); ``None`` without rules."""
        rules = [rule for rule in self.rules if style is None or rule.style is style]
        if not rules:
            return None
        net = sum(
            (rule.bias is Bias.BULLISH) - (rule.bias is Bias.BEARISH)  # booleans as 0 and 1
            for rule in rules
        )
        return net / len(rules)

    @property
    def score(self) -> float | None:
        """Net score of the whole panel, in [-1, 1]."""
        return self.score_of()

    @property
    def trend_score(self) -> float | None:
        """Net score of the trend-following rules."""
        return self.score_of(Style.TREND)

    @property
    def reversal_score(self) -> float | None:
        """Net score of the reversal rules."""
        return self.score_of(Style.REVERSAL)

    @property
    def verdict(self) -> PanelVerdict | None:
        """The net of the panel in words (``None`` without rules)."""
        score = self.score
        if score is None:
            return None
        if score > STRONG:
            return PanelVerdict.STRONG_BULLISH
        if score > 0:
            return PanelVerdict.BULLISH
        if score < -STRONG:
            return PanelVerdict.STRONG_BEARISH
        return PanelVerdict.BEARISH if score < 0 else PanelVerdict.NEUTRAL


def _last(series: pd.Series) -> float:
    return float(series.iloc[-1]) if len(series) else float("nan")


def _cross(value: float, reference: float) -> Bias:
    """Bullish above the reference, bearish below it, neutral on it."""
    if value > reference:
        return Bias.BULLISH
    return Bias.BEARISH if value < reference else Bias.NEUTRAL


def _fade(value: float, lower: float, upper: float) -> Bias:
    """A reversal reading: bearish above the band, bullish below it."""
    if value > upper:
        return Bias.BEARISH
    return Bias.BULLISH if value < lower else Bias.NEUTRAL


def signal_panel(
    close: pd.Series, high: pd.Series | None = None, low: pd.Series | None = None
) -> SignalPanel:
    """Read the eleven rules of :data:`RULES` on the last bar of a series.

    Args:
        close: Closes, oldest first.
        high: Highs; without them (and the lows) the ADX, the CCI and Williams %R are
            skipped, never computed from the closes.
        low: Lows.
    """
    price = _last(close)
    lines = macd(close, 12, 26, 9)
    bands = bollinger(close, 20, 2.0)
    ranged = high is not None and low is not None
    found: dict[str, tuple[Bias, dict[str, float]]] = {}

    value = _last(rsi(close, 14))
    found["RSI"] = (_fade(value, 30.0, 70.0), {"rsi": value})
    line, trigger = _last(lines["line"]), _last(lines["signal"])
    found["MACD"] = (_cross(line, trigger), {"macd": line, "signal": trigger})
    for name, average in (
        ("SMA_20", sma(close, 20)),
        ("SMA_50", sma(close, 50)),
        ("EMA_12", ema(close, 12)),
        ("EMA_26", ema(close, 26)),
    ):
        level = _last(average)
        found[name] = (_cross(price, level), {"average": level, "close": price})
    lower, upper = _last(bands["lower"]), _last(bands["upper"])
    found["BOLLINGER"] = (_fade(price, lower, upper), {"lower": lower, "upper": upper})
    smoothed = _last(100.0 * stoch_rsi(close, 14).rolling(3).mean())
    found["STOCH_RSI"] = (_fade(smoothed, 20.0, 80.0), {"k": smoothed})
    if high is not None and low is not None:
        directional = adx(high, low, close, 14)
        strength = _last(directional["adx"])
        plus, minus = _last(directional["plus_di"]), _last(directional["minus_di"])
        bias = _cross(plus, minus) if strength > ADX_TREND else Bias.NEUTRAL
        found["ADX"] = (bias, {"adx": strength, "plus_di": plus, "minus_di": minus})
        channel = _last(cci(high, low, close, 20))
        found["CCI"] = (_fade(channel, -100.0, 100.0), {"cci": channel})
        range_position = _last(williams_r(high, low, close, 14))
        found["WILLR"] = (_fade(range_position, -80.0, -20.0), {"willr": range_position})

    rules = []
    skipped: dict[str, tuple[str, ...]] = {}
    for name, (style, parameters) in RULES.items():
        if name not in found:
            skipped[name] = ("high", "low") if not ranged else (UNDEFINED,)
            continue
        bias, values = found[name]
        if not all(np.isfinite(v) for v in values.values()):
            skipped[name] = (UNDEFINED,)
            continue
        rules.append(RuleReading(name, style, bias, values, parameters))
    return SignalPanel(tuple(rules), skipped)


@dataclass(frozen=True, slots=True)
class TrendState:
    """The background trend on the last bar.

    Attributes:
        direction: Up (the close above the long average and the medium one rising), down
            (below and falling) or sideways.
        sma_window: Bars of the long simple average (200, or fewer on a short series).
        sma: Its value.
        price_vs_sma_pct: Distance of the close from it, in percent.
        ema_window: Bars of the medium exponential average (50, or fewer).
        ema_slope_pct: Its change over the last :data:`SLOPE_BARS` bars, in percent.
    """

    direction: TrendDirection
    sma_window: int
    sma: float
    price_vs_sma_pct: float
    ema_window: int
    ema_slope_pct: float


def trend_state(close: pd.Series) -> TrendState | None:
    """The background trend of a series, or ``None`` when it is too short to tell.

    The close against its 200-bar simple average, and the slope of its 50-bar exponential
    average over the last 10 bars (more than 0.3 % either way counts). Shorter series use
    shorter averages, which the result names: half the bars (20 at least) and a third of
    them (10 at least).
    """
    bars = len(close)
    if bars == 0:
        return None
    sma_window = 200 if bars >= 200 else max(20, bars // 2)  # noqa: PLR2004 - the long average
    ema_window = 50 if bars >= 60 else max(10, bars // 3)  # noqa: PLR2004 - the medium one
    long_average = _last(sma(close, sma_window))
    medium = ema(close, ema_window)
    back = min(SLOPE_BARS, bars - 1)
    now, before = _last(medium), float(medium.iloc[-1 - back])
    price = _last(close)
    if not (np.isfinite(long_average) and np.isfinite(now) and np.isfinite(before)):
        return None
    slope = (now - before) / before * 100.0 if before else 0.0
    distance = (price - long_average) / long_average * 100.0 if long_average else 0.0
    if price > long_average and slope > SLOPE_PCT:
        direction = TrendDirection.UP
    elif price < long_average and slope < -SLOPE_PCT:
        direction = TrendDirection.DOWN
    else:
        direction = TrendDirection.SIDEWAYS
    return TrendState(direction, sma_window, long_average, distance, ema_window, slope)


@dataclass(frozen=True, slots=True)
class Confluence:
    """Whether the timeframes point the same way.

    Attributes:
        verdict: Aligned, mixed, neutral or insufficient.
        alignment: Weighted mean of the frames' scores, in [-1, 1] (``None`` without frames).
        agreement: Share of the frames read that point the dominant way (``None`` when
            fewer than :data:`MIN_FRAMES` could be read).
        frames: Frames that could be read.
    """

    verdict: ConfluenceVerdict
    alignment: float | None
    agreement: float | None
    frames: int


def confluence(frames: Sequence[tuple[float, float | None]]) -> Confluence:
    """Weigh the scores of several timeframes and say whether they agree.

    Args:
        frames: ``(weight, score)`` per frame; a score of ``None`` is a frame that could
            not be read, which neither counts nor weighs.

    Raises:
        ValueError: If a weight is not positive or a score is outside [-1, 1].
    """
    read = [(weight, score) for weight, score in frames if score is not None]
    for weight, score in read:
        if not weight > 0:
            raise ValueError(f"weights must be positive, got {weight}")
        if not -1.0 <= score <= 1.0:
            raise ValueError(f"scores must be within [-1, 1], got {score}")
    if not read:
        return Confluence(ConfluenceVerdict.INSUFFICIENT, None, None, 0)
    alignment = sum(weight * score for weight, score in read) / sum(w for w, _ in read)
    if len(read) < MIN_FRAMES:
        return Confluence(ConfluenceVerdict.INSUFFICIENT, alignment, None, len(read))
    agreeing = sum(score * alignment > 0 for _, score in read)
    agreement = agreeing / len(read)
    if abs(alignment) < ALIGNMENT_MIN:
        verdict = ConfluenceVerdict.NEUTRAL
    elif agreement >= AGREEMENT_MIN:
        verdict = (
            ConfluenceVerdict.ALIGNED_BULLISH
            if alignment > 0
            else ConfluenceVerdict.ALIGNED_BEARISH
        )
    else:
        verdict = ConfluenceVerdict.MIXED
    return Confluence(verdict, alignment, agreement, len(read))
