"""The card of an instrument: what each pillar of evidence says about it (ADR-0040).

A card gathers, for one instrument of any asset class, the readings the platform already
computes, grouped in *pillars*. Which pillars an instrument has depends on its asset class
(:data:`PILLARS`): every instrument has a technical reading, a risk profile and the quality
of its data; only crypto has perpetual swaps, with their funding and their positioning. A
pillar that applies but could not be read (no source serves its data) says so instead of
being left out.

A pillar is *directional* when what it reads points up or down: its score is in [-1, 1].
The others describe (how volatile, how deep the fall, how clean the data) and have no
score. Nothing is fused into a verdict: weights between pillars have to be learned from
resolved readings (G4), and a card describes, it does not recommend.

Facts are data, not sentences: a key, a value and its unit, so that each interface words
them in its language.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics.risk import value_at_risk
from investinglab.domain.instruments import AssetClass
from investinglab.domain.positioning import PositioningField
from investinglab.domain.rate_series import RateKind

if TYPE_CHECKING:
    from investinglab.domain.confluence import TimeframeConfluence
    from investinglab.domain.instruments import Instrument
    from investinglab.domain.positioning import PositioningSeries
    from investinglab.domain.quality import DataQualityReport
    from investinglab.domain.rate_series import RateSeries
    from investinglab.domain.series import DataSource, PriceSeries
    from investinglab.domain.structure import PriceStructure

__all__ = [
    "PILLARS",
    "AssetCard",
    "Fact",
    "Pillar",
    "PillarIssue",
    "PillarReading",
    "PillarSpec",
    "Unit",
    "asset_card",
    "derivatives_pillar",
    "pillars_for",
    "quality_pillar",
    "risk_pillar",
    "technical_pillar",
]

VAR_LEVEL: Final = 0.95
"""Confidence of the value at risk the risk pillar reports."""


class Pillar(StrEnum):
    """A kind of evidence about an instrument."""

    TECHNICAL = "technical"
    """Rules of technical analysis across timeframes, and the price structure."""
    RISK = "risk"
    """How much the price has moved and fallen."""
    DERIVATIVES = "derivatives"
    """Its perpetual swap: who pays whom to hold a position, and how traders stand in it."""
    QUALITY = "quality"
    """How far its data can be trusted."""


class Unit(StrEnum):
    """What the value of a fact is, so that an interface can format it."""

    RATIO = "ratio"
    """A fraction, shown as a percentage."""
    NUMBER = "number"
    COUNT = "count"
    CODE = "code"
    """One of a closed set of words, to be translated."""
    DATE = "date"


class PillarIssue(StrEnum):
    """Why a pillar that applies could not be read."""

    NO_DATA = "no_data"
    """No source serves what it reads."""


@dataclass(frozen=True, slots=True)
class Fact:
    """One figure of a pillar.

    Attributes:
        key: What it is (``alignment``, ``volatility``...).
        value: Its value; ``None`` when it could not be told.
        unit: How to read the value.
    """

    key: str
    value: float | str | None
    unit: Unit


@dataclass(frozen=True, slots=True)
class PillarSpec:
    """A pillar of the registry.

    Attributes:
        pillar: Which one.
        applies_to: The asset classes that have it.
        directional: Whether its reading points up or down (and so has a score).
    """

    pillar: Pillar
    applies_to: frozenset[AssetClass]
    directional: bool


_EVERY: Final = frozenset(AssetClass)

PILLARS: Final[tuple[PillarSpec, ...]] = (
    PillarSpec(Pillar.TECHNICAL, _EVERY, directional=True),
    PillarSpec(Pillar.RISK, _EVERY, directional=False),
    PillarSpec(Pillar.DERIVATIVES, frozenset({AssetClass.CRYPTO}), directional=False),
    PillarSpec(Pillar.QUALITY, _EVERY, directional=False),
)
"""The registry, in the order a card shows them. A new pillar is a new entry and its reader."""


def pillars_for(asset_class: AssetClass) -> tuple[PillarSpec, ...]:
    """The pillars an instrument of ``asset_class`` has."""
    return tuple(spec for spec in PILLARS if asset_class in spec.applies_to)


def _spec(pillar: Pillar) -> PillarSpec:
    return next(spec for spec in PILLARS if spec.pillar is pillar)


@dataclass(frozen=True, slots=True)
class PillarReading:
    """What a pillar says about the instrument.

    Attributes:
        pillar: Which one.
        directional: Whether it points up or down.
        score: Its direction in [-1, 1]; ``None`` if it is not directional or could not be
            told.
        facts: Its figures, in the order they are shown.
        issue: Why it could not be read (``None`` if it was).
    """

    pillar: Pillar
    directional: bool
    score: float | None
    facts: tuple[Fact, ...]
    issue: PillarIssue | None = None

    def fact(self, key: str) -> Fact:
        """The fact named ``key``.

        Raises:
            KeyError: If the pillar has no such fact.
        """
        for fact in self.facts:
            if fact.key == key:
                return fact
        raise KeyError(f"The {self.pillar.value} pillar has no fact {key!r}")


def _read(pillar: Pillar, facts: tuple[Fact, ...], score: float | None = None) -> PillarReading:
    return PillarReading(pillar, _spec(pillar).directional, score, facts)


def _unread(pillar: Pillar) -> PillarReading:
    return PillarReading(pillar, _spec(pillar).directional, None, (), PillarIssue.NO_DATA)


def _number(value: float | None) -> float | None:
    """``value`` as a float, or ``None`` if it is missing or not finite."""
    return None if value is None or not np.isfinite(value) else float(value)


def technical_pillar(
    confluence: TimeframeConfluence | None, structure: PriceStructure | None = None
) -> PillarReading:
    """The technical reading: the timeframes' rules and the price structure.

    Its score is the alignment of the timeframes (the weighted mean of their net scores).

    Args:
        confluence: The frames read (``None`` if none could be).
        structure: The price structure of the finest frame, for the nearest levels.
    """
    if confluence is None:
        return _unread(Pillar.TECHNICAL)
    summary = confluence.summary
    read = next((frame for frame in confluence.frames if frame.panel is not None), None)
    trend = None if read is None else read.trend
    panel = None if read is None else read.panel
    support = None if structure is None else structure.nearest_support
    resistance = None if structure is None else structure.nearest_resistance
    facts = (
        Fact("verdict", summary.verdict.value, Unit.CODE),
        Fact("alignment", _number(summary.alignment), Unit.NUMBER),
        Fact("agreement", _number(summary.agreement), Unit.RATIO),
        Fact("frames_read", float(summary.frames), Unit.COUNT),
        Fact("trend", None if trend is None else trend.direction.value, Unit.CODE),
        Fact(
            "price_vs_average",
            None if trend is None else _number(trend.price_vs_sma_pct / 100),
            Unit.RATIO,
        ),
        Fact("rules_bullish", None if panel is None else float(panel.bullish), Unit.COUNT),
        Fact("rules_bearish", None if panel is None else float(panel.bearish), Unit.COUNT),
        Fact(
            "support_distance",
            None if support is None else _number(support.distance_pct / 100),
            Unit.RATIO,
        ),
        Fact(
            "resistance_distance",
            None if resistance is None else _number(resistance.distance_pct / 100),
            Unit.RATIO,
        ),
    )
    return _read(Pillar.TECHNICAL, facts, _number(summary.alignment))


def risk_pillar(series: PriceSeries) -> PillarReading:
    """How much the price has moved and fallen over the bars of ``series``."""
    stats = series.stats
    drawdown = series.drawdown()
    facts = (
        Fact("volatility", _number(stats.annualized_volatility), Unit.RATIO),
        Fact("max_drawdown", _number(stats.max_drawdown), Unit.RATIO),
        Fact("drawdown", _number(drawdown.iloc[-1]) if len(drawdown) else None, Unit.RATIO),
        Fact("value_at_risk", _number(value_at_risk(series.returns(), VAR_LEVEL)), Unit.RATIO),
        Fact("total_return", _number(stats.total_return), Unit.RATIO),
        Fact("since", stats.start.date().isoformat(), Unit.DATE),
    )
    return _read(Pillar.RISK, facts)


def _funding_facts(funding: RateSeries) -> tuple[Fact, ...]:
    if funding.kind is not RateKind.FUNDING:
        raise ValueError(f"The derivatives pillar reads funding, not {funding.kind.value}")
    annual = funding.annualized()
    return (
        Fact("funding_last", _number(annual.iloc[-1]), Unit.RATIO),
        Fact("funding_mean", _number(annual.mean()), Unit.RATIO),
        Fact("funding_positive", _number((funding.rates > 0).mean()), Unit.RATIO),
        Fact("payments", float(len(funding)), Unit.COUNT),
        Fact("funding_since", funding.start.date().isoformat(), Unit.DATE),
    )


def _open_interest_change(positioning: PositioningSeries) -> Fact:
    """How much the open interest grew over the series, in contracts if the venue gives them.

    Contracts (units of the base asset) count the positions open: their change is
    ``open_interest_change``. Their value in a currency also moves with the price, so it is
    read (as ``open_interest_value_change``) only when the venue publishes nothing else.
    """
    for name, key in (
        (PositioningField.OPEN_INTEREST, "open_interest_change"),
        (PositioningField.OPEN_INTEREST_VALUE, "open_interest_value_change"),
    ):
        if name in positioning.fields:
            values = positioning.column(name).dropna()
            first = float(values.iloc[0])
            change = None if first <= 0 else _number(float(values.iloc[-1]) / first - 1)
            return Fact(key, change, Unit.RATIO)
    return Fact("open_interest_change", None, Unit.RATIO)


def _positioning_facts(positioning: PositioningSeries) -> tuple[Fact, ...]:
    latest = positioning.latest()
    return (
        _open_interest_change(positioning),
        Fact(
            "long_short_accounts",
            _number(latest.get(PositioningField.LONG_SHORT_ACCOUNTS)),
            Unit.NUMBER,
        ),
        Fact(
            "top_long_short_positions",
            _number(latest.get(PositioningField.TOP_LONG_SHORT_POSITIONS)),
            Unit.NUMBER,
        ),
        Fact("positioning_venue", positioning.venue, Unit.CODE),
        Fact("positioning_until", positioning.end.date().isoformat(), Unit.DATE),
    )


def derivatives_pillar(
    funding: RateSeries | None, positioning: PositioningSeries | None = None
) -> PillarReading:
    """The funding of the instrument's perpetual swap and how its traders stand in it.

    A positive funding rate means longs pay shorts to stay in, and a long/short ratio above
    one that more accounts are long than short: both say how the market is positioned, not
    where the price goes. Each part is read when a source serves it; the pillar is unread
    only when neither is.

    Args:
        funding: The funding rates (``None`` if no source serves them).
        positioning: Daily open interest and long/short ratios (``None`` if no source
            serves them); the change of the open interest is measured over its range.

    Raises:
        ValueError: If ``funding`` holds another kind of rate.
    """
    facts: tuple[Fact, ...] = ()
    if funding is not None and len(funding) > 0:
        facts += _funding_facts(funding)
    if positioning is not None and len(positioning) > 0:
        facts += _positioning_facts(positioning)
    return _read(Pillar.DERIVATIVES, facts) if facts else _unread(Pillar.DERIVATIVES)


def quality_pillar(report: DataQualityReport) -> PillarReading:
    """How far the data behind the other pillars can be trusted."""
    worst = report.worst_severity
    expected = report.expected_sessions
    facts = (
        Fact("state", "ok" if report.ok else "issues", Unit.CODE),
        Fact("worst", None if worst is None else worst.value, Unit.CODE),
        Fact("issues", float(len(report.issues)), Unit.COUNT),
        Fact("observations", float(report.observations), Unit.COUNT),
        Fact(
            "coverage",
            None if not expected else _number(min(1.0, report.observations / expected)),
            Unit.RATIO,
        ),
        Fact("until", report.end.date().isoformat(), Unit.DATE),
    )
    return _read(Pillar.QUALITY, facts)


@dataclass(frozen=True, slots=True, eq=False)
class AssetCard:
    """The pillars of an instrument on its last bar.

    Attributes:
        instrument: The instrument read.
        source: Provenance of its bars.
        as_of: Its last bar.
        last_close: The close of that bar.
        pillars: One reading per pillar of its asset class, in the registry's order.
        not_applicable: The pillars of the registry its asset class does not have.
    """

    instrument: Instrument
    source: DataSource
    as_of: pd.Timestamp
    last_close: float
    pillars: tuple[PillarReading, ...]
    not_applicable: tuple[Pillar, ...]

    def pillar(self, pillar: Pillar) -> PillarReading:
        """The reading of one pillar.

        Raises:
            KeyError: If the instrument's asset class does not have it.
        """
        for reading in self.pillars:
            if reading.pillar is pillar:
                return reading
        raise KeyError(f"{self.instrument.symbol} has no {pillar.value} pillar")


def asset_card(
    series: PriceSeries,
    *,
    confluence: TimeframeConfluence | None,
    structure: PriceStructure | None,
    quality: DataQualityReport,
    funding: RateSeries | None = None,
    positioning: PositioningSeries | None = None,
) -> AssetCard:
    """Read every pillar the asset class of ``series`` has.

    Args:
        series: The bars of the instrument (daily, as a rule).
        confluence: Its timeframes (``None`` if none could be read).
        structure: Its price structure.
        quality: The quality report of ``series``.
        funding: The funding of its perpetual swap; only read for the asset classes that
            have the derivatives pillar.
        positioning: The positioning of that swap, read likewise.
    """
    readers = {
        Pillar.TECHNICAL: lambda: technical_pillar(confluence, structure),
        Pillar.RISK: lambda: risk_pillar(series),
        Pillar.DERIVATIVES: lambda: derivatives_pillar(funding, positioning),
        Pillar.QUALITY: lambda: quality_pillar(quality),
    }
    applicable = pillars_for(series.asset_class)
    names = {spec.pillar for spec in applicable}
    return AssetCard(
        instrument=series.instrument,
        source=series.source,
        as_of=pd.Timestamp(series.end),
        last_close=float(series.prices.iloc[-1]),
        pillars=tuple(readers[spec.pillar]() for spec in applicable),
        not_applicable=tuple(spec.pillar for spec in PILLARS if spec.pillar not in names),
    )
