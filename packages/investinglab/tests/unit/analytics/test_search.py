"""The strategy grammar and its compiler, on SYNTHETIC bars (ADR-0050).

The grammar refuses what CryptoWorld's refused, saying where; its JSON form is canonical.
The compiler gives each condition its meaning, holds no signal on what it cannot know yet,
and lets an exit win over an entry on the same bar.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.backtest import RiskModel, SizingMode, SizingModel
from investinglab.analytics.patterns import detect, occurred_within
from investinglab.analytics.search import (
    CLASSICS,
    Block,
    Combine,
    Compare,
    Cross,
    Leg,
    Operator,
    PatternCondition,
    Regime,
    Slope,
    StrategyDirection,
    StrategySpec,
    Threshold,
    compile_sides,
)
from investinglab.analytics.technical import compute
from support.factories import gbm_prices

BARS = 160


def _bars(size: int = BARS, seed: int = 11) -> dict[str, pd.Series]:
    """A SYNTHETIC random walk with coherent open, high, low, close and volume."""
    close = gbm_prices(size, sigma=0.45, seed=seed)
    rng = np.random.default_rng(seed)
    open_ = close * np.exp(rng.normal(0.0, 0.01, size))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.0, 0.02, size))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.0, 0.02, size))
    index = pd.RangeIndex(size)
    columns = {"open": open_, "high": high, "low": low, "close": close}
    bars = {name: pd.Series(values, index=index) for name, values in columns.items()}
    bars["volume"] = pd.Series(rng.uniform(1e3, 5e3, size), index=index)
    return bars


RSI = Leg("RSI", {"window": 14})
PRICE = Leg("PRICE")
FAST, SLOW = Leg("SMA", {"window": 10}), Leg("SMA", {"window": 30})


def _spec(entry: Any, exit_: Any, **options: Any) -> StrategySpec:
    return StrategySpec(entry=Block((entry,)), exit=Block((exit_,)), **options)


def _threshold(op: Operator, value: float, **options: Any) -> Threshold:
    return Threshold(RSI, op, value, **options)


# ── The grammar ────────────────────────────────────────────────────


def _threshold_dict(**changes: Any) -> dict[str, Any]:
    condition = {"type": "threshold", "indicator": "RSI", "params": {"window": 14}, "op": "lt"}
    return {**condition, "threshold": 30.0, **changes}


def _spec_dict(entry: dict[str, Any] | None = None, **changes: Any) -> dict[str, Any]:
    block = {"combine": "AND", "conditions": [entry or _threshold_dict()]}
    exit_ = {"combine": "AND", "conditions": [_threshold_dict(op="gt", threshold=70.0)]}
    return {"entry": block, "exit": exit_, **changes}


CROSS = {
    "type": "cross",
    "a": {"indicator": "PRICE"},
    "b": {"indicator": "EMA"},
    "op": "cross_above",
}
SWEEP = {"type": "pattern", "pattern": "SWEEP_LOW", "lookback": 2}
THREE = [_threshold_dict(), _threshold_dict(threshold=20.0), _threshold_dict(threshold=10.0)]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            _spec_dict(_threshold_dict(indicator="NOPE")),
            "entry.conditions\\[0\\]: unknown indicator",
        ),
        (_spec_dict(_threshold_dict(indicator="SMA")), "is a level in price units"),
        (_spec_dict(_threshold_dict(params={"window": 2.5})), "window must be a whole number"),
        (_spec_dict(_threshold_dict(params={"window": True})), "must be a finite number"),
        (_spec_dict(_threshold_dict(params={"span": 3})), "RSI has no parameters \\['span'\\]"),
        (_spec_dict(_threshold_dict(threshold="30")), "threshold must be a finite number"),
        (_spec_dict(_threshold_dict(op="above")), "a threshold compares with \\['gt', 'lt'\\]"),
        (_spec_dict(_threshold_dict(negate="yes")), "negate must be true or false"),
        (_spec_dict(_threshold_dict(colour="red")), "unknown \\['colour'\\]"),
        (_spec_dict({"type": "spline"}), "entry.conditions\\[0\\].type: one of"),
        (_spec_dict(_threshold_dict(op="nope")), "a threshold compares with"),
        (_spec_dict({**SWEEP, "pattern": "UNICORN"}), "unknown pattern 'UNICORN'"),
        (_spec_dict({**CROSS, "a": {"indicator": "RSI"}}), "RSI\\(14\\) is an oscillator"),
        (_spec_dict({**CROSS, "b": {"indicator": "PRICE"}}), "PRICE against itself"),
        (_spec_dict({**CROSS, "negate": True}), "a cross is an event and cannot be negated"),
        (_spec_dict({**CROSS, "a": "PRICE"}), "entry.conditions\\[0\\].a: expected an object"),
        (_spec_dict({**SWEEP, "negate": True}), "needs a lookback of 3 bars or more"),
        (_spec_dict({**SWEEP, "lookback": 0}), "lookback must be at least 1"),
        (
            _spec_dict({"type": "slope", "indicator": "RSI", "op": "rising", "bars": 0}),
            "slope's bars must be at least 1",
        ),
        ({**_spec_dict(), "entry": {"combine": "AND"}}, "entry: missing \\['conditions'\\]"),
        (
            {**_spec_dict(), "entry": {"combine": "AND", "conditions": _threshold_dict()}},
            "entry.conditions: expected a list",
        ),
        (
            {**_spec_dict(), "entry": {"combine": "AND", "conditions": [*THREE, THREE[0]]}},
            "joins 1 to 3 conditions, not 4",
        ),
        (
            {**_spec_dict(), "entry": {"combine": "K_OF_N", "k": 3, "conditions": THREE}},
            "k must be from 2 to 2",
        ),
        (
            {**_spec_dict(), "entry": {"combine": "K_OF_N", "conditions": THREE}},
            "K_OF_N needs k",
        ),
        (
            {**_spec_dict(), "entry": {"combine": "OR", "k": 2, "conditions": THREE}},
            "only K_OF_N takes k",
        ),
        (
            {**_spec_dict(), "entry": {"combine": "XOR", "conditions": THREE}},
            "a block combines with",
        ),
        (_spec_dict(direction="sideways"), "a strategy trades"),
        (_spec_dict(direction="both"), "needs short_entry and short_exit"),
        (
            _spec_dict(short_entry=_spec_dict()["entry"], short_exit=_spec_dict()["exit"]),
            "only for both ways",
        ),
        (_spec_dict(regime={"adx_min": 120}), "between 0 and 100"),
        (_spec_dict(regime={"adx": 20}), "regime: missing \\['adx_min'\\]"),
        (_spec_dict(risk={"max_bars": 2.5}), "risk.max_bars: max_bars must be a whole number"),
        (_spec_dict(risk={"stop": 0.1}), "risk: unknown \\['stop'\\]"),
        (_spec_dict(risk={"stop_loss_pct": "5%"}), "risk.stop_loss_pct"),
        (_spec_dict(sizing={"mode": "conviction"}), "sizing.mode: full, fraction or risk"),
        (_spec_dict(sizing={"mode": "fraction"}), "sizing: missing \\['fraction'\\]"),
        (_spec_dict(colour="red"), "strategy: unknown \\['colour'\\]"),
        ([], "strategy: expected an object"),
    ],
)
def test_an_illegal_strategy_is_refused_saying_where(data: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        StrategySpec.from_dict(data)


def test_the_json_form_is_canonical() -> None:
    loose = _spec_dict(
        {"type": "threshold", "indicator": "RSI", "op": "lt", "threshold": 30, "negate": False},
        risk={"stop_loss_pct": 0.05, "max_bars": 10.0},
        sizing={"mode": "full"},
    )
    strict = _spec_dict(risk={"stop_loss_pct": 0.05, "max_bars": 10})

    spec = StrategySpec.from_dict(loose)

    assert spec.to_dict() == strict  # defaults written, types fixed, silence not written
    assert spec.definition_hash == StrategySpec.from_dict(strict).definition_hash
    assert StrategySpec.from_dict(spec.to_dict()) == spec
    assert isinstance(spec.to_dict()["risk"]["max_bars"], int)
    assert isinstance(spec.to_dict()["entry"]["conditions"][0]["threshold"], float)


def test_what_says_nothing_is_dropped_and_what_cannot_be_said_is_refused() -> None:
    entry, exit_ = _threshold(Operator.LT, 30), _threshold(Operator.GT, 70)

    plain = _spec(entry, exit_, risk=RiskModel(), sizing=SizingModel())
    sized = _spec(entry, exit_, sizing=SizingModel(SizingMode.RISK, risk_pct=1))

    assert plain.risk is None
    assert plain.sizing is None
    assert sized.to_dict()["sizing"] == {"mode": "risk", "risk_pct": 1.0}
    with pytest.raises(ValueError, match="comes from a model"):
        _spec(entry, exit_, sizing=SizingModel(SizingMode.CONVICTION))
    with pytest.raises(ValueError, match="unknown sizing"):
        _spec(entry, exit_, sizing=SizingModel("half"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="negate must be true or false"):
        Threshold(RSI, Operator.LT, 30, negate=1)  # type: ignore[arg-type]


def test_legs_read_as_their_indicator_and_parameters() -> None:
    spec = CLASSICS["donchian_breakout"]
    regime = StrategySpec(entry=spec.entry, exit=spec.exit, regime=Regime(25))

    assert str(Leg("BB_UPPER", {"window": 20, "dev": 2.5})) == "BB_UPPER(20,2.5)"
    assert str(PRICE) == "PRICE"
    assert str(Leg("SMA")) == "SMA(50)"  # its default
    assert [str(leg) for leg in spec.legs] == [
        "PRICE",
        "DONCH_UPPER(20)",
        "SMA(100)",
        "DONCH_LOWER(10)",
    ]
    assert regime.legs[-1] == Leg("ADX", {"window": 14})
    assert len({Leg("SMA", {"window": 50}), Leg("SMA")}) == 1
    assert spec.trades_long
    assert not spec.trades_short
    mixed = StrategySpec(
        entry=Block((_threshold(Operator.LT, 30), PatternCondition("DOJI"))),
        exit=Block((Slope(FAST, Operator.FALLING, 3), _threshold(Operator.GT, 70))),
    )
    assert mixed.legs == (RSI, FAST)  # each once; a pattern reads no indicator


def test_the_classics_are_valid_and_distinct() -> None:
    hashes = {spec.definition_hash for spec in CLASSICS.values()}

    assert len(hashes) == len(CLASSICS)
    assert all(StrategySpec.from_dict(s.to_dict()) == s for s in CLASSICS.values())


# ── The compiler ───────────────────────────────────────────────────


def test_a_threshold_signals_where_the_oscillator_says() -> None:
    bars = _bars()
    rsi = compute("RSI", bars, window=14).to_numpy()
    spec = _spec(_threshold(Operator.LT, 40), _threshold(Operator.GT, 60))

    sides = compile_sides(spec, bars)

    known = ~np.isnan(rsi)
    expected = np.where(known & (rsi > 60), -1.0, np.where(known & (rsi < 40), 1.0, 0.0))
    np.testing.assert_array_equal(sides.long.to_numpy(), expected)
    assert sides.short is None
    assert sides.ready == int(np.argmax(known))
    assert sides.long.index.equals(bars["close"].index)


def test_an_exit_wins_over_an_entry_on_the_same_bar() -> None:
    always = _threshold(Operator.GT, -1.0)  # an RSI is always above -1
    spec = _spec(always, always)

    sides = compile_sides(spec, _bars())

    assert set(np.unique(sides.long.to_numpy()[sides.ready :])) == {-1.0}


def test_a_cross_fires_on_the_bar_it_happens_only() -> None:
    bars = _bars()
    gap = (compute("SMA", bars, window=10) - compute("SMA", bars, window=30)).to_numpy()
    spec = _spec(Cross(FAST, SLOW, Operator.CROSS_ABOVE), Cross(FAST, SLOW, Operator.CROSS_BELOW))

    signals = compile_sides(spec, bars).long.to_numpy()

    before = np.concatenate(([np.nan], gap[:-1]))
    with np.errstate(invalid="ignore"):
        up = (before <= 0) & (gap > 0)
        down = (before >= 0) & (gap < 0)
    assert up.any()
    assert down.any()
    np.testing.assert_array_equal(signals == 1, up)
    np.testing.assert_array_equal(signals == -1, down)


def test_an_unknown_condition_holds_no_signal_even_negated() -> None:
    bars = _bars()
    rsi = compute("RSI", bars, window=14).to_numpy()
    never = Compare(PRICE, Leg("SMA", {"window": 120}), Operator.BELOW, negate=True)
    spec = _spec(_threshold(Operator.LT, 30, negate=True), never)

    sides = compile_sides(spec, bars)

    first = int(np.argmax(~np.isnan(rsi)))
    assert not sides.long.to_numpy()[:first].any()  # "not below 30" is unknown until then
    assert sides.long.iloc[first] == (1.0 if rsi[first] >= 30 else 0.0)
    assert sides.ready == 119  # the SMA(120) has its first value on the 120th bar


def test_an_or_holds_with_one_condition_known_to_hold() -> None:
    bars = _bars()
    rising = Slope(PRICE, Operator.RISING, 1)
    late = Threshold(Leg("RSI", {"window": 100}), Operator.GT, 50)
    spec = StrategySpec(
        entry=Block((rising, late), Combine.OR), exit=Block((_threshold(Operator.LT, -1),))
    )

    sides = compile_sides(spec, bars)

    close = bars["close"].to_numpy()
    np.testing.assert_array_equal(sides.long.to_numpy()[1:20] == 1, np.diff(close)[:19] > 0)
    assert sides.ready == 99  # the RSI(100)'s first value: everything is known from there


def test_k_of_n_counts_the_conditions_that_hold() -> None:
    bars = _bars()
    conditions = (
        Slope(PRICE, Operator.RISING, 1),
        Slope(PRICE, Operator.RISING, 2),
        Slope(PRICE, Operator.RISING, 3),
    )
    two = StrategySpec(
        entry=Block(conditions, Combine.K_OF_N, k=2),
        exit=Block((_threshold(Operator.LT, -1),)),
    )

    signals = compile_sides(two, bars).long.to_numpy()

    close = bars["close"].to_numpy()
    votes = sum((close[3:] > close[3 - lag : -lag]).astype(int) for lag in (1, 2, 3))
    np.testing.assert_array_equal(signals[3:] == 1, votes >= 2)


def test_the_regime_holds_back_entries_but_never_exits() -> None:
    bars = _bars()
    adx = compute("ADX", bars, window=14).to_numpy()
    plain = _spec(Slope(PRICE, Operator.RISING, 1), Slope(PRICE, Operator.FALLING, 1))
    trend = StrategySpec(entry=plain.entry, exit=plain.exit, regime=Regime(25))

    free, filtered = compile_sides(plain, bars).long, compile_sides(trend, bars).long

    with np.errstate(invalid="ignore"):
        trending = adx >= 25
    np.testing.assert_array_equal(filtered == -1, free == -1)
    np.testing.assert_array_equal(filtered == 1, (free == 1) & trending)
    assert compile_sides(trend, bars).ready == int(np.argmax(~np.isnan(adx)))


def test_each_direction_trades_its_side() -> None:
    bars = _bars()
    entry, exit_ = Slope(PRICE, Operator.RISING, 1), Slope(PRICE, Operator.FALLING, 1)
    long = compile_sides(_spec(entry, exit_), bars)
    short = compile_sides(_spec(entry, exit_, direction=StrategyDirection.SHORT), bars)
    both = compile_sides(
        _spec(
            entry,
            exit_,
            direction=StrategyDirection.BOTH,
            short_entry=Block((exit_,)),
            short_exit=Block((entry,)),
        ),
        bars,
    )

    assert not short.long.any()
    assert short.short is not None
    assert short.short.equals(long.long.rename("short"))  # the same blocks, the other side
    assert both.long.equals(long.long)
    assert both.short is not None
    assert both.short.equals(-long.long.rename("short"))


def test_a_pattern_holds_through_its_window() -> None:
    bars = _bars()
    flags = detect("SWEEP_LOW", bars, None, window=10)
    seen = PatternCondition("SWEEP_LOW", {"window": 10}, lookback=4)
    quiet = PatternCondition("SWEEP_LOW", {"window": 10}, lookback=4, negate=True)

    entries = compile_sides(_spec(seen, _threshold(Operator.LT, -1)), bars).long.to_numpy()
    calm = compile_sides(_spec(quiet, _threshold(Operator.LT, -1)), bars)

    within = occurred_within(flags, 4).to_numpy()
    assert flags.any()
    np.testing.assert_array_equal(entries == 1, within)
    start = seen.warmup + seen.lookback - 2  # the window is past the warm-up from there
    np.testing.assert_array_equal(calm.long.to_numpy()[start:] == 1, ~within[start:])
    assert not calm.long.to_numpy()[:start].any()


def test_what_the_bars_lack_is_said() -> None:
    bars = _bars()
    closes = {"close": bars["close"]}
    breakout = PatternCondition("ORB_UP", {"bars": 2})

    with pytest.raises(KeyError, match="high"):
        compile_sides(CLASSICS["donchian_breakout"], closes)
    with pytest.raises(ValueError, match="session"):
        compile_sides(_spec(breakout, _threshold(Operator.LT, -1)), bars)
    hours = compile_sides(
        _spec(breakout, _threshold(Operator.LT, -1)), bars, [i // 8 for i in range(BARS)]
    )
    assert hours.long.max() <= 1.0


def test_a_slope_longer_than_the_series_is_never_known() -> None:
    spec = _spec(Slope(PRICE, Operator.RISING, 500), _threshold(Operator.GT, 70))

    sides = compile_sides(spec, _bars())

    assert sides.ready == BARS
    assert not (sides.long == 1).any()


def test_a_series_too_short_is_never_ready() -> None:
    spec = CLASSICS["trend_pullback"]  # an SMA(150)

    sides = compile_sides(spec, _bars(100))

    assert sides.ready == 100
    assert not (sides.long == 1).any()  # its exits fire, but nothing ever opens
