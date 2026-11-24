"""Strategies as data: CryptoWorld's strategy grammar, validated and canonical (ADR-0050).

A strategy is a :class:`StrategySpec`: a block of entry conditions and a block of exit
conditions over the indicator catalogue (:mod:`~investinglab.analytics.technical.catalogue`)
and the price patterns (:mod:`~investinglab.analytics.patterns`), with five kinds of
condition:

* :class:`Threshold`: an oscillator above or below a value (``RSI(14) < 30``);
* :class:`Cross`: a level crossing another on this bar (``SMA(20)`` over ``SMA(50)``);
* :class:`Compare`: a level above or below another while it lasts (the price over its
  ``SMA(200)``);
* :class:`Slope`: any indicator rising or falling against ``bars`` ago;
* :class:`PatternCondition`: a price pattern on this bar or on one of the ``lookback - 1``
  before.

A block joins one to three conditions with ``AND``, ``OR`` or "at least ``k`` of them". A
strategy trades long, short (its blocks open and close shorts) or both ways (with blocks of
its own for the short side); it may carry its risk barriers, its sizing and a regime filter
(a minimum ADX to enter).

Its JSON form (:meth:`StrategySpec.to_dict`) is CryptoWorld's, so that a strategy found
there keeps its meaning and its :attr:`~StrategySpec.definition_hash` here (the parity tests
check both). It is canonical: every parameter is written, with its type, so the same strategy
always has the same hash.

What is legal is the grammar's structure and each value's own domain (a window is a whole
number of bars, at least one). The search ranges of the catalogue only bound what the
generator samples (G4), not what a strategy may say.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from investinglab.analytics.backtest import RiskModel, SizingMode, SizingModel
from investinglab.analytics.patterns import PATTERNS, Pattern
from investinglab.analytics.technical import CATALOGUE, Indicator, Parameter

__all__ = [
    "MAX_CONDITIONS",
    "MIN_NEGATED_LOOKBACK",
    "REGIME_ADX_WINDOW",
    "Block",
    "Combine",
    "Compare",
    "Condition",
    "ConditionKind",
    "Cross",
    "Leg",
    "Operator",
    "PatternCondition",
    "Regime",
    "Slope",
    "StrategyDirection",
    "StrategySpec",
    "Threshold",
]

MAX_CONDITIONS: Final = 3
"""Conditions a block may join (CryptoWorld's limit: more is a recipe for overfitting)."""

MIN_NEGATED_LOOKBACK: Final = 3
"""Bars a negated pattern must look back over.

A pattern is an event: "no engulfing on this bar" is true almost always. Over a window,
"no sweep in the last five bars" describes a quiet market instead.
"""

REGIME_ADX_WINDOW: Final = 14
"""Bars of the ADX the regime filter reads (CryptoWorld's)."""

ADX_SCALE: Final = 100.0
"""The ADX lies between 0 and this."""

type Value = int | float
type Parameters = Mapping[str, Value]


class ConditionKind(StrEnum):
    """The five kinds of condition, by their name in the JSON form."""

    THRESHOLD = "threshold"
    CROSS = "cross"
    COMPARE = "compare"
    SLOPE = "slope"
    PATTERN = "pattern"


class Operator(StrEnum):
    """How a condition compares, by kind."""

    GT = "gt"
    """A threshold: the oscillator above the value."""
    LT = "lt"
    """A threshold: the oscillator below the value."""
    CROSS_ABOVE = "cross_above"
    """A cross: the first level was at or below the second on the bar before, above now."""
    CROSS_BELOW = "cross_below"
    """A cross: at or above on the bar before, below now."""
    ABOVE = "above"
    """A comparison: the first level above the second."""
    BELOW = "below"
    """A comparison: the first level below the second."""
    RISING = "rising"
    """A slope: higher than ``bars`` ago."""
    FALLING = "falling"
    """A slope: lower than ``bars`` ago."""


class Combine(StrEnum):
    """How a block joins its conditions."""

    AND = "AND"
    OR = "OR"
    K_OF_N = "K_OF_N"
    """At least ``k`` of them: partial confirmation, which ``AND`` and ``OR`` cannot say."""


class StrategyDirection(StrEnum):
    """Which side of the market a strategy trades."""

    LONG = "long"
    """Its blocks open and close long positions."""
    SHORT = "short"
    """The same blocks open and close short positions."""
    BOTH = "both"
    """Long with ``entry`` and ``exit``, short with ``short_entry`` and ``short_exit``: two
    strategies evolved apart, since a reversal upwards is not a reversal downwards."""


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _whole(value: object, what: str, *, least: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise ValueError(f"{what} must be a whole number, got {value!r}")
    if value < least:
        raise ValueError(f"{what} must be at least {least}, got {value}")
    return int(value)


def _parameters(owner: str, declared: Mapping[str, Parameter], given: Parameters) -> Parameters:
    """Every declared parameter, with its type: the given value or its default."""
    unknown = sorted(set(given) - set(declared))
    if unknown:
        raise ValueError(f"{owner} has no parameters {unknown}; it has {sorted(declared)}")
    values: dict[str, Value] = {}
    for name, parameter in declared.items():
        value = given.get(name, parameter.default)
        _number(value, f"{owner} {name}")
        try:
            values[name] = parameter.check(name, value)
        except ValueError as error:
            raise ValueError(f"{owner}: {error}") from None
    return MappingProxyType(values)


def _text(values: Parameters) -> str:
    return ",".join(f"{value:g}" for value in values.values())


def _operator(
    value: Operator | str, allowed: tuple[Operator, ...], kind: ConditionKind
) -> Operator:
    try:
        op = Operator(value)
    except ValueError:
        op = None
    if op is None or op not in allowed:
        raise ValueError(f"a {kind} compares with {[str(a) for a in allowed]}, not {value!r}")
    return op


def _flag(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{what} must be true or false, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class Leg:
    """An indicator of the catalogue with its parameters: one side of a condition.

    Attributes:
        indicator: Its name in the catalogue (``"SMA"``, ``"PRICE"``...).
        params: Its parameters; those left out take their defaults.

    Raises:
        ValueError: An unknown indicator, or a parameter it has not or out of its domain.
    """

    indicator: str
    params: Parameters = field(default_factory=dict)

    def __post_init__(self) -> None:
        entry = CATALOGUE.get(self.indicator)
        if entry is None:
            raise ValueError(f"unknown indicator {self.indicator!r}; known: {sorted(CATALOGUE)}")
        object.__setattr__(
            self, "params", _parameters(self.indicator, entry.parameters, self.params)
        )

    @property
    def entry(self) -> Indicator:
        """Its entry in the catalogue."""
        return CATALOGUE[self.indicator]

    @property
    def is_level(self) -> bool:
        """Whether it is a level in price units (an average, a band) rather than an oscillator."""
        return self.entry.threshold is None

    def key(self) -> tuple[str, tuple[tuple[str, Value], ...]]:
        """What identifies its values: the indicator and its parameters."""
        return self.indicator, tuple(sorted(self.params.items()))

    def __hash__(self) -> int:
        return hash(self.key())

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return {"indicator": self.indicator, "params": dict(self.params)}

    def __str__(self) -> str:
        return f"{self.indicator}({_text(self.params)})" if self.params else self.indicator


@dataclass(frozen=True, slots=True)
class Threshold:
    """An oscillator above (``gt``) or below (``lt``) a value.

    Raises:
        ValueError: A level instead of an oscillator, another operator, or a value that is not
            a finite number.
    """

    leg: Leg
    op: Operator
    threshold: float
    negate: bool = False

    kind: ClassVar[ConditionKind] = ConditionKind.THRESHOLD
    OPERATORS: ClassVar[tuple[Operator, ...]] = (Operator.GT, Operator.LT)

    def __post_init__(self) -> None:
        if self.leg.is_level:
            raise ValueError(
                f"{self.leg} is a level in price units: compare or cross it with another level"
            )
        object.__setattr__(self, "op", _operator(self.op, self.OPERATORS, self.kind))
        object.__setattr__(self, "threshold", _number(self.threshold, "the threshold"))
        _flag(self.negate, "negate")

    @property
    def legs(self) -> tuple[Leg, ...]:
        """The indicators it reads."""
        return (self.leg,)

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return _negated(
            {
                "type": str(self.kind),
                **self.leg.to_dict(),
                "op": str(self.op),
                "threshold": self.threshold,
            },
            negate=self.negate,
        )


def _two_levels(a: Leg, b: Leg) -> None:
    for leg in (a, b):
        if not leg.is_level:
            raise ValueError(f"{leg} is an oscillator, not a price level: give it a threshold")
    if a == b:
        raise ValueError(f"{a} against itself never says anything")


@dataclass(frozen=True, slots=True)
class Cross:
    """A level crossing another on this bar (the bar before on the other side, or on it).

    A cross is an event: it cannot be negated ("no cross on this bar" is nearly always true).

    Raises:
        ValueError: An oscillator for a leg, the same leg twice, or another operator.
    """

    a: Leg
    b: Leg
    op: Operator

    kind: ClassVar[ConditionKind] = ConditionKind.CROSS
    OPERATORS: ClassVar[tuple[Operator, ...]] = (Operator.CROSS_ABOVE, Operator.CROSS_BELOW)
    negate: ClassVar[bool] = False

    def __post_init__(self) -> None:
        _two_levels(self.a, self.b)
        object.__setattr__(self, "op", _operator(self.op, self.OPERATORS, self.kind))

    @property
    def legs(self) -> tuple[Leg, ...]:
        """The indicators it reads."""
        return self.a, self.b

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return {
            "type": str(self.kind),
            "a": self.a.to_dict(),
            "b": self.b.to_dict(),
            "op": str(self.op),
        }


@dataclass(frozen=True, slots=True)
class Compare:
    """A level above or below another while it lasts: a state, unlike a cross.

    Raises:
        ValueError: An oscillator for a leg, the same leg twice, or another operator.
    """

    a: Leg
    b: Leg
    op: Operator
    negate: bool = False

    kind: ClassVar[ConditionKind] = ConditionKind.COMPARE
    OPERATORS: ClassVar[tuple[Operator, ...]] = (Operator.ABOVE, Operator.BELOW)

    def __post_init__(self) -> None:
        _two_levels(self.a, self.b)
        object.__setattr__(self, "op", _operator(self.op, self.OPERATORS, self.kind))
        _flag(self.negate, "negate")

    @property
    def legs(self) -> tuple[Leg, ...]:
        """The indicators it reads."""
        return self.a, self.b

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return _negated(
            {
                "type": str(self.kind),
                "a": self.a.to_dict(),
                "b": self.b.to_dict(),
                "op": str(self.op),
            },
            negate=self.negate,
        )


@dataclass(frozen=True, slots=True)
class Slope:
    """Any indicator higher (``rising``) or lower (``falling``) than ``bars`` ago.

    Raises:
        ValueError: Another operator, or ``bars`` not a whole number of at least one.
    """

    leg: Leg
    op: Operator
    bars: int
    negate: bool = False

    kind: ClassVar[ConditionKind] = ConditionKind.SLOPE
    OPERATORS: ClassVar[tuple[Operator, ...]] = (Operator.RISING, Operator.FALLING)

    def __post_init__(self) -> None:
        object.__setattr__(self, "op", _operator(self.op, self.OPERATORS, self.kind))
        object.__setattr__(self, "bars", _whole(self.bars, "a slope's bars"))
        _flag(self.negate, "negate")

    @property
    def legs(self) -> tuple[Leg, ...]:
        """The indicators it reads."""
        return (self.leg,)

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return _negated(
            {"type": str(self.kind), **self.leg.to_dict(), "op": str(self.op), "bars": self.bars},
            negate=self.negate,
        )


@dataclass(frozen=True, slots=True)
class PatternCondition:
    """A price pattern on this bar or on one of the ``lookback - 1`` before.

    The window lets two events combine: "a sweep and then an engulfing" is an ``AND`` of the
    sweep within the last four bars and the engulfing on this one.

    Attributes:
        pattern: Its name in the catalogue (``"SWEEP_LOW"``...).
        params: Its parameters; those left out take their defaults.
        lookback: Bars the window spans, this one included.
        negate: Whether the condition is that it did *not* happen in the window; it needs a
            window of at least :data:`MIN_NEGATED_LOOKBACK` bars.

    Raises:
        ValueError: An unknown pattern, a parameter it has not or out of its domain, a
            lookback below one, or a negation over too short a window.
    """

    pattern: str
    params: Parameters = field(default_factory=dict)
    lookback: int = 1
    negate: bool = False

    kind: ClassVar[ConditionKind] = ConditionKind.PATTERN

    def __post_init__(self) -> None:
        entry = PATTERNS.get(self.pattern)
        if entry is None:
            raise ValueError(f"unknown pattern {self.pattern!r}; known: {sorted(PATTERNS)}")
        object.__setattr__(self, "params", _parameters(self.pattern, entry.parameters, self.params))
        object.__setattr__(self, "lookback", _whole(self.lookback, "a pattern's lookback"))
        if _flag(self.negate, "negate") and self.lookback < MIN_NEGATED_LOOKBACK:
            raise ValueError(
                f"a negated pattern needs a lookback of {MIN_NEGATED_LOOKBACK} bars or more: "
                f"not having happened on one bar is true almost always"
            )

    @property
    def entry(self) -> Pattern:
        """Its entry in the catalogue."""
        return PATTERNS[self.pattern]

    @property
    def legs(self) -> tuple[Leg, ...]:
        """The indicators it reads: none."""
        return ()

    @property
    def warmup(self) -> int:
        """Bars before it can fire: the catalogue's warm-up, or its window if longer."""
        return max(self.entry.warmup, *(math.ceil(v) + 1 for v in self.params.values()), 1)

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return _negated(
            {
                "type": str(self.kind),
                "pattern": self.pattern,
                "params": dict(self.params),
                "lookback": self.lookback,
            },
            negate=self.negate,
        )


type Condition = Threshold | Cross | Compare | Slope | PatternCondition


def _negated(data: dict[str, Any], *, negate: bool) -> dict[str, Any]:
    """The JSON form, with ``negate`` written only when it says something (CryptoWorld's)."""
    return {**data, "negate": True} if negate else data


@dataclass(frozen=True, slots=True)
class Block:
    """One to :data:`MAX_CONDITIONS` conditions joined by ``combine``.

    Attributes:
        conditions: The conditions, in order.
        combine: ``AND``, ``OR`` or ``K_OF_N``.
        k: How many must hold, with ``K_OF_N``: from 2 to one fewer than the conditions (at
            the ends, it is an ``OR`` or an ``AND``, and one strategy would have two forms).

    Raises:
        ValueError: No conditions or too many, or a ``k`` that does not fit.
    """

    conditions: tuple[Condition, ...]
    combine: Combine = Combine.AND
    k: int | None = None

    def __post_init__(self) -> None:
        conditions = tuple(self.conditions)
        object.__setattr__(self, "conditions", conditions)
        if not 1 <= len(conditions) <= MAX_CONDITIONS:
            raise ValueError(
                f"a block joins 1 to {MAX_CONDITIONS} conditions, not {len(conditions)}"
            )
        try:
            combine = Combine(self.combine)
        except ValueError:
            raise ValueError(f"a block combines with {[str(c) for c in Combine]}") from None
        object.__setattr__(self, "combine", combine)
        if combine is Combine.K_OF_N:
            if self.k is None:
                raise ValueError("K_OF_N needs k: how many conditions must hold")
            k = _whole(self.k, "k", least=2)
            if k > len(conditions) - 1:
                raise ValueError(
                    f"k must be from 2 to {len(conditions) - 1} with {len(conditions)} "
                    f"conditions: at the ends, K_OF_N is an OR or an AND"
                )
            object.__setattr__(self, "k", k)
        elif self.k is not None:
            raise ValueError(f"only K_OF_N takes k, not {combine}")

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        data: dict[str, Any] = {"combine": str(self.combine)}
        if self.k is not None:
            data["k"] = self.k
        data["conditions"] = [condition.to_dict() for condition in self.conditions]
        return data


@dataclass(frozen=True, slots=True)
class Regime:
    """Enter only in a trend: the ADX (over :data:`REGIME_ADX_WINDOW` bars) at least ``adx_min``.

    It filters entries only: a position can always be closed.

    Raises:
        ValueError: A minimum outside (0, 100), the range of the ADX.
    """

    adx_min: float

    def __post_init__(self) -> None:
        value = _number(self.adx_min, "the regime's adx_min")
        if not 0 < value < ADX_SCALE:
            raise ValueError(f"the regime's adx_min must be between 0 and 100, got {value}")
        object.__setattr__(self, "adx_min", value)

    @property
    def leg(self) -> Leg:
        """The indicator it reads."""
        return Leg("ADX", {"window": REGIME_ADX_WINDOW})

    def to_dict(self) -> dict[str, Any]:
        """Its JSON form."""
        return {"adx_min": self.adx_min}


_RISK_FIELDS: Final = (
    "stop_loss_pct",
    "take_profit_pct",
    "trailing_stop_pct",
    "max_bars",
    "atr_stop_mult",
    "atr_target_mult",
)


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """A strategy as data.

    Attributes:
        entry: When to open (a long one, or a short one if the direction is ``short``).
        exit: When to close it. A bar with both signals closes (no whipsaw).
        direction: Which side it trades.
        short_entry: When to open a short, with ``both``.
        short_exit: When to close it, with ``both``.
        risk: Its barriers (stops, targets, exit by time); none if it has none.
        sizing: How large each position is; all the equity if ``None``. A conviction sizing
            is not part of a strategy: it comes from a model.
        regime: The minimum ADX to enter.

    The values of ``risk`` and ``sizing`` are checked where they are used, by the backtest's
    configuration (:class:`investinglab.domain.BacktestConfig`).

    Raises:
        ValueError: Short blocks without ``both``, or ``both`` without them; a conviction
            sizing.
        TypeError: A flag (``negate``) that is not a boolean.
    """

    entry: Block
    exit: Block
    direction: StrategyDirection = StrategyDirection.LONG
    short_entry: Block | None = None
    short_exit: Block | None = None
    risk: RiskModel | None = None
    sizing: SizingModel | None = None
    regime: Regime | None = None

    def __post_init__(self) -> None:
        try:
            direction = StrategyDirection(self.direction)
        except ValueError:
            raise ValueError(
                f"a strategy trades {[str(d) for d in StrategyDirection]}, not {self.direction!r}"
            ) from None
        object.__setattr__(self, "direction", direction)
        shorts = (self.short_entry, self.short_exit)
        if direction is StrategyDirection.BOTH and None in shorts:
            raise ValueError("a strategy that trades both ways needs short_entry and short_exit")
        if direction is not StrategyDirection.BOTH and shorts != (None, None):
            raise ValueError(
                f"short_entry and short_exit are only for both ways; a {direction} strategy "
                "trades with entry and exit"
            )
        object.__setattr__(self, "risk", _canonical_risk(self.risk))
        object.__setattr__(self, "sizing", _canonical_sizing(self.sizing))

    @property
    def blocks(self) -> dict[str, Block]:
        """Its blocks by name, in CryptoWorld's order."""
        found = {
            "entry": self.entry,
            "exit": self.exit,
            "short_entry": self.short_entry,
            "short_exit": self.short_exit,
        }
        return {name: block for name, block in found.items() if block is not None}

    @property
    def conditions(self) -> tuple[Condition, ...]:
        """Every condition of every block."""
        return tuple(c for block in self.blocks.values() for c in block.conditions)

    @property
    def legs(self) -> tuple[Leg, ...]:
        """Every indicator it reads (the regime's ADX included), each once."""
        found = [leg for condition in self.conditions for leg in condition.legs]
        if self.regime is not None:
            found.append(self.regime.leg)
        return tuple(dict.fromkeys(found))

    @property
    def trades_long(self) -> bool:
        """Whether it opens long positions."""
        return self.direction is not StrategyDirection.SHORT

    @property
    def trades_short(self) -> bool:
        """Whether it opens short positions."""
        return self.direction is not StrategyDirection.LONG

    def to_dict(self) -> dict[str, Any]:
        """Its canonical JSON form, CryptoWorld's: what is not said is not written."""
        data: dict[str, Any] = {name: block.to_dict() for name, block in self.blocks.items()}
        if self.direction is not StrategyDirection.LONG:
            data["direction"] = str(self.direction)
        if self.risk is not None:
            data["risk"] = {
                name: getattr(self.risk, name)
                for name in _RISK_FIELDS
                if getattr(self.risk, name) is not None
            }
        if self.sizing is not None:
            mode = self.sizing.mode
            value = self.sizing.fraction if mode is SizingMode.FRACTION else self.sizing.risk_pct
            data["sizing"] = {"mode": str(mode), _SIZING_FIELD[mode]: value}
        if self.regime is not None:
            data["regime"] = self.regime.to_dict()
        return data

    @property
    def definition_hash(self) -> str:
        """Twelve hexadecimal digits that identify the definition: CryptoWorld's ``spec_hash``.

        The SHA-1 of the canonical JSON form with sorted keys: two strategies with the same
        hash are the same strategy, which is what lets a search count what it has tried.
        """
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()[:12]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StrategySpec:
        """Read a strategy from its JSON form (CryptoWorld's, or :meth:`to_dict`'s).

        Raises:
            ValueError: Saying where (``exit.conditions[1].threshold: ...``) what is wrong.
        """
        try:
            return _parse_spec(data)
        except TypeError as error:  # a wrong type where an object or a list was expected
            raise ValueError(str(error)) from None


_SIZING_FIELD: Final = {SizingMode.FRACTION: "fraction", SizingMode.RISK: "risk_pct"}


def _canonical_risk(risk: RiskModel | None) -> RiskModel | None:
    """The barriers with their types (whole bars, real multiples); ``None`` if there are none."""
    if risk is None or not risk.active:
        return None
    values: dict[str, Any] = {}
    for name in _RISK_FIELDS:
        given = getattr(risk, name)
        if given is not None:
            values[name] = _whole(given, name) if name == "max_bars" else _number(given, name)
    return RiskModel(**values)


def _canonical_sizing(sizing: SizingModel | None) -> SizingModel | None:
    """The sizing with its types; ``None`` for all the equity."""
    if sizing is None:
        return None
    try:
        mode = SizingMode(sizing.mode)
    except ValueError:
        raise ValueError(f"unknown sizing {sizing.mode!r}") from None
    if mode is SizingMode.CONVICTION:
        raise ValueError("a conviction sizing comes from a model, not from a strategy")
    if mode is SizingMode.FULL:
        return None
    return SizingModel(
        mode,
        fraction=_number(sizing.fraction, "fraction"),
        risk_pct=_number(sizing.risk_pct, "risk_pct"),
    )


# ── Reading the JSON form ──────────────────────────────────────────


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path}: expected an object, got {value!r}")
    return value


def _keys(data: Mapping[str, Any], path: str, required: set[str], optional: set[str]) -> None:
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"{path}: missing {missing}")
    unknown = sorted(set(data) - required - optional)
    if unknown:
        raise ValueError(f"{path}: unknown {unknown}")


def _at[T](path: str, build: Callable[..., T], *args: object, **kwargs: object) -> T:
    """``build(*args, **kwargs)``, with ``path`` in front of the error it raises."""
    try:
        return build(*args, **kwargs)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{path}: {error}") from None


def _parameters_of(data: Mapping[str, Any], path: str) -> Parameters:
    return dict(_mapping(data.get("params", {}), f"{path}.params"))


def _leg(value: object, path: str) -> Leg:
    data = _mapping(value, path)
    _keys(data, path, {"indicator"}, {"params"})
    return _at(path, Leg, data["indicator"], _parameters_of(data, path))


def _negate_of(data: Mapping[str, Any], path: str) -> bool:
    return _at(f"{path}.negate", _flag, data.get("negate", False), "negate")


def _condition(value: object, path: str) -> Condition:
    data = _mapping(value, path)
    given = data.get("type")
    if given not in set(ConditionKind):
        raise ValueError(f"{path}.type: one of {[str(k) for k in ConditionKind]}, got {given!r}")
    kind = ConditionKind(str(given))
    if kind is ConditionKind.THRESHOLD:
        _keys(data, path, {"type", "indicator", "op", "threshold"}, {"params", "negate"})
        leg = _at(path, Leg, data["indicator"], _parameters_of(data, path))
        return _at(path, Threshold, leg, data["op"], data["threshold"], _negate_of(data, path))
    if kind is ConditionKind.SLOPE:
        _keys(data, path, {"type", "indicator", "op", "bars"}, {"params", "negate"})
        leg = _at(path, Leg, data["indicator"], _parameters_of(data, path))
        return _at(path, Slope, leg, data["op"], data["bars"], _negate_of(data, path))
    if kind is ConditionKind.PATTERN:
        _keys(data, path, {"type", "pattern"}, {"params", "lookback", "negate"})
        return _at(
            path,
            PatternCondition,
            data["pattern"],
            _parameters_of(data, path),
            data.get("lookback", 1),
            _negate_of(data, path),
        )
    if kind is ConditionKind.CROSS:
        _keys(data, path, {"type", "a", "b", "op"}, {"negate"})
        if _negate_of(data, path):
            raise ValueError(f"{path}.negate: a cross is an event and cannot be negated")
        return _at(
            path, Cross, _leg(data["a"], f"{path}.a"), _leg(data["b"], f"{path}.b"), data["op"]
        )
    _keys(data, path, {"type", "a", "b", "op"}, {"negate"})
    return _at(
        path,
        Compare,
        _leg(data["a"], f"{path}.a"),
        _leg(data["b"], f"{path}.b"),
        data["op"],
        _negate_of(data, path),
    )


def _block(value: object, path: str) -> Block:
    data = _mapping(value, path)
    _keys(data, path, {"combine", "conditions"}, {"k"})
    conditions = data["conditions"]
    if not isinstance(conditions, Sequence) or isinstance(conditions, str):
        raise TypeError(f"{path}.conditions: expected a list, got {conditions!r}")
    parsed = tuple(_condition(c, f"{path}.conditions[{i}]") for i, c in enumerate(conditions))
    return _at(path, Block, parsed, data["combine"], data.get("k"))


def _risk(value: object, path: str) -> RiskModel:
    data = _mapping(value, path)
    _keys(data, path, set(), set(_RISK_FIELDS))
    values: dict[str, Any] = {}
    for name, given in data.items():
        if name == "max_bars":
            values[name] = _at(f"{path}.{name}", _whole, given, name)
        else:
            values[name] = _at(f"{path}.{name}", _number, given, name)
    return RiskModel(**values)


def _sizing(value: object, path: str) -> SizingModel:
    data = _mapping(value, path)
    mode = data.get("mode", str(SizingMode.FULL))
    if mode not in {str(SizingMode.FULL), *(str(m) for m in _SIZING_FIELD)}:
        raise ValueError(f"{path}.mode: full, fraction or risk, got {mode!r}")
    chosen = SizingMode(mode)
    wanted = _SIZING_FIELD.get(chosen)
    _keys(data, path, {wanted} if wanted else set(), {"mode"})
    if wanted is None:
        return SizingModel()
    return SizingModel(chosen, **{wanted: _at(f"{path}.{wanted}", _number, data[wanted], wanted)})


def _parse_spec(value: object) -> StrategySpec:
    data = _mapping(value, "strategy")
    _keys(
        data,
        "strategy",
        {"entry", "exit"},
        {"direction", "short_entry", "short_exit", "risk", "sizing", "regime"},
    )
    regime = None
    if data.get("regime") is not None:
        found = _mapping(data["regime"], "regime")
        _keys(found, "regime", {"adx_min"}, set())
        regime = _at("regime", Regime, found["adx_min"])
    return _at(
        "strategy",
        StrategySpec,
        entry=_block(data["entry"], "entry"),
        exit=_block(data["exit"], "exit"),
        direction=data.get("direction", str(StrategyDirection.LONG)),
        short_entry=None
        if data.get("short_entry") is None
        else _block(data["short_entry"], "short_entry"),
        short_exit=None
        if data.get("short_exit") is None
        else _block(data["short_exit"], "short_exit"),
        risk=None if data.get("risk") is None else _risk(data["risk"], "risk"),
        sizing=None if data.get("sizing") is None else _sizing(data["sizing"], "sizing"),
        regime=regime,
    )
