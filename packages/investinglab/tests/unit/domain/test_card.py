"""The card of an instrument: its pillars by asset class (SYNTHETIC bars and rates)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.risk import value_at_risk
from investinglab.domain import (
    PILLARS,
    AssetClass,
    Fact,
    Frequency,
    Pillar,
    PillarIssue,
    PriceSeries,
    Unit,
    asset_card,
    pillars_for,
    timeframe_confluence,
)
from investinglab.domain.card import (
    PillarReading,
    derivatives_pillar,
    quality_pillar,
    risk_pillar,
    technical_pillar,
)
from investinglab.domain.positioning import PositioningField, PositioningSeries
from investinglab.domain.quality import assess_quality
from investinglab.domain.rate_series import RateKind, RateSeries
from investinglab.domain.structure import price_structure
from support.factories import (
    SYNTHETIC_SOURCE,
    business_days,
    gbm_prices,
    make_instrument,
    make_series,
)

if TYPE_CHECKING:
    from investinglab.domain.confluence import TimeframeConfluence

DAYS = business_days(800, start="2021-01-04")
SHARE = make_series(gbm_prices(800, seed=5), symbol="SYN.MC", index=DAYS, ohlc=True)
COIN = make_series(
    gbm_prices(800, sigma=0.6, seed=6),
    symbol="BTC/USDT",
    index=DAYS,
    asset_class=AssetClass.CRYPTO,
    exchange=None,
    ohlc=True,
)


def _figure(reading: PillarReading, key: str) -> float:
    """A numeric fact (the test fails if it is text or could not be told)."""
    value = reading.fact(key).value
    assert isinstance(value, float), f"{key} is {value!r}"
    return value


def _frames(series: PriceSeries) -> TimeframeConfluence:
    return timeframe_confluence(
        {Frequency.DAY_1: series, Frequency.WEEK_1: series.resample(Frequency.WEEK_1)},
        derived=[Frequency.WEEK_1],
    )


def _funding(values: list[float], kind: RateKind = RateKind.FUNDING) -> RateSeries:
    index = pd.date_range("2026-01-01", periods=len(values), freq="8h", tz="UTC")
    swap = make_instrument("BTC/USDT:USDT", asset_class=AssetClass.CRYPTO, exchange=None)
    return RateSeries(swap, "synthetic", kind, SYNTHETIC_SOURCE, pd.Series(values, index=index))


def _positioning(columns: dict[PositioningField, list[float]]) -> PositioningSeries:
    """SYNTHETIC daily positioning of the swap, one value per day for each field given."""
    length = len(next(iter(columns.values())))
    index = pd.date_range("2026-01-01", periods=length, freq="D", tz="UTC")
    swap = make_instrument("BTC/USDT:USDT", asset_class=AssetClass.CRYPTO, exchange=None)
    frame = pd.DataFrame({name.value: values for name, values in columns.items()}, index=index)
    valued = PositioningField.OPEN_INTEREST_VALUE in columns
    return PositioningSeries(
        swap,
        "synthetic",
        SYNTHETIC_SOURCE,
        Frequency.DAY_1,
        frame,
        value_currency=swap.currency if valued else None,
    )


def test_every_asset_class_has_its_pillars_and_only_crypto_has_derivatives() -> None:
    for asset_class in AssetClass:
        names = [spec.pillar for spec in pillars_for(asset_class)]
        assert names[0] is Pillar.TECHNICAL
        assert (Pillar.DERIVATIVES in names) == (asset_class is AssetClass.CRYPTO)
        assert {Pillar.RISK, Pillar.QUALITY} <= set(names)
    assert [spec.pillar for spec in PILLARS if spec.directional] == [Pillar.TECHNICAL]


def test_the_technical_pillar_scores_the_alignment_of_the_timeframes() -> None:
    frames = _frames(SHARE)
    structure = price_structure(SHARE)

    reading = technical_pillar(frames, structure)

    summary = frames.summary
    daily = frames.frames[0]
    assert daily.trend is not None
    assert daily.panel is not None
    assert (reading.pillar, reading.directional, reading.issue) == (Pillar.TECHNICAL, True, None)
    assert reading.score == summary.alignment
    assert reading.score is not None
    assert -1 <= reading.score <= 1
    assert reading.fact("verdict") == Fact("verdict", summary.verdict.value, Unit.CODE)
    assert reading.fact("frames_read").value == 2
    assert reading.fact("trend").value == daily.trend.direction.value
    assert reading.fact("price_vs_average").value == pytest.approx(
        daily.trend.price_vs_sma_pct / 100
    )
    assert reading.fact("rules_bullish").value == daily.panel.bullish
    support = structure.nearest_support
    assert reading.fact("support_distance").value == (
        None if support is None else pytest.approx(support.distance_pct / 100)
    )
    with pytest.raises(KeyError, match="no fact 'nope'"):
        reading.fact("nope")


def test_a_technical_pillar_without_frames_is_unread_and_without_structure_lacks_levels() -> None:
    unread = technical_pillar(None)
    bare = technical_pillar(_frames(SHARE))

    assert (unread.score, unread.facts, unread.issue) == (None, (), PillarIssue.NO_DATA)
    assert bare.fact("support_distance").value is None
    assert bare.fact("resistance_distance").value is None
    assert bare.score is not None


def test_the_risk_pillar_describes_and_has_no_score() -> None:
    reading = risk_pillar(SHARE)

    stats = SHARE.stats
    assert (reading.directional, reading.score, reading.issue) == (False, None, None)
    assert reading.fact("volatility").value == pytest.approx(stats.annualized_volatility)
    assert reading.fact("max_drawdown").value == pytest.approx(stats.max_drawdown)
    assert reading.fact("drawdown").value == pytest.approx(SHARE.drawdown().iloc[-1])
    assert _figure(reading, "drawdown") <= 0
    assert reading.fact("value_at_risk").value == pytest.approx(
        value_at_risk(SHARE.returns(), 0.95)
    )
    assert reading.fact("since") == Fact("since", "2021-01-04", Unit.DATE)


def test_the_derivatives_pillar_reads_funding_and_nothing_else() -> None:
    reading = derivatives_pillar(_funding([0.0001, 0.0003, -0.0002, 0.0001]))

    assert (reading.score, reading.issue) == (None, None)
    assert reading.fact("funding_last").value == pytest.approx(0.0001 * 1095)
    assert reading.fact("funding_mean").value == pytest.approx(0.000075 * 1095)
    assert reading.fact("funding_positive").value == pytest.approx(0.75)
    assert reading.fact("payments").value == 4
    assert derivatives_pillar(None).issue is PillarIssue.NO_DATA
    with pytest.raises(ValueError, match="reads funding, not borrow"):
        derivatives_pillar(_funding([0.01, 0.02], RateKind.BORROW))


def test_the_derivatives_pillar_adds_how_traders_stand_in_the_swap() -> None:
    positioning = _positioning(
        {
            PositioningField.OPEN_INTEREST: [100.0, 104.0, 110.0],
            # The value rose more than the contracts: the price went up too.
            PositioningField.OPEN_INTEREST_VALUE: [5_000.0, 5_600.0, 6_600.0],
            PositioningField.LONG_SHORT_ACCOUNTS: [1.4, 1.2, np.nan],  # the last one skipped
            PositioningField.TOP_LONG_SHORT_POSITIONS: [0.9, 1.1, 1.05],
        }
    )

    reading = derivatives_pillar(_funding([0.0001, 0.0003]), positioning)

    assert [fact.key for fact in reading.facts] == [
        "funding_last",
        "funding_mean",
        "funding_positive",
        "payments",
        "funding_since",
        "open_interest_change",
        "long_short_accounts",
        "top_long_short_positions",
        "positioning_venue",
        "positioning_until",
    ]
    assert reading.fact("open_interest_change").value == pytest.approx(0.10)  # in contracts
    assert reading.fact("long_short_accounts").value == pytest.approx(1.2)  # last published
    assert reading.fact("top_long_short_positions").value == pytest.approx(1.05)
    assert reading.fact("positioning_venue") == Fact("positioning_venue", "synthetic", Unit.CODE)
    assert reading.fact("positioning_until").value == "2026-01-03"
    assert (reading.score, reading.issue) == (None, None)


def test_the_derivatives_pillar_reads_what_is_served_and_nothing_more() -> None:
    valued_only = _positioning({PositioningField.OPEN_INTEREST_VALUE: [200.0, 150.0]})
    from_zero = _positioning({PositioningField.OPEN_INTEREST: [0.0, 5.0]})

    alone = derivatives_pillar(None, valued_only)

    assert alone.issue is None
    # Without contracts, the change of their value, named as such (it moves with the price).
    assert alone.facts[0].key == "open_interest_value_change"
    assert alone.fact("open_interest_value_change").value == pytest.approx(-0.25)
    assert alone.fact("long_short_accounts").value is None  # this venue publishes no ratio
    with pytest.raises(KeyError):
        alone.fact("funding_last")
    assert derivatives_pillar(None, from_zero).fact("open_interest_change").value is None
    ratios_only = _positioning({PositioningField.LONG_SHORT_ACCOUNTS: [1.0, 2.0]})
    assert derivatives_pillar(None, ratios_only).fact("open_interest_change").value is None
    assert derivatives_pillar(None, None).issue is PillarIssue.NO_DATA


def test_the_quality_pillar_says_how_far_the_data_can_be_trusted() -> None:
    clean = quality_pillar(assess_quality(SHARE, expected_sessions=DAYS))
    kept = np.arange(800) % 5 != 2  # one session in five never arrived
    holed = make_series(gbm_prices(800, seed=5)[kept], symbol="SYN.MC", index=DAYS[kept])
    gapped = quality_pillar(assess_quality(holed, expected_sessions=DAYS))

    assert clean.fact("state").value == "ok"
    assert (clean.fact("worst").value, clean.fact("issues").value) == (None, 0)
    assert clean.fact("coverage").value == pytest.approx(1.0)
    assert clean.fact("until").value == str(DAYS[-1].date())
    assert gapped.fact("state").value == "issues"
    assert gapped.fact("worst").value in {"warning", "critical"}
    assert gapped.fact("coverage").value == pytest.approx(0.8)  # 640 of the 800 expected
    assert quality_pillar(assess_quality(SHARE)).fact("coverage").value is None  # no calendar


def test_a_card_reads_the_pillars_of_its_asset_class() -> None:
    share = asset_card(
        SHARE,
        confluence=_frames(SHARE),
        structure=price_structure(SHARE),
        quality=assess_quality(SHARE),
        funding=_funding([0.0001, 0.0002]),  # a share has no swap: never read
    )
    coin = asset_card(
        COIN,
        confluence=None,
        structure=None,
        quality=assess_quality(COIN),
        funding=_funding([0.0001, 0.0002]),
    )

    assert [r.pillar for r in share.pillars] == [Pillar.TECHNICAL, Pillar.RISK, Pillar.QUALITY]
    assert share.not_applicable == (Pillar.DERIVATIVES,)
    assert (share.as_of, share.last_close) == (DAYS[-1], float(SHARE.prices.iloc[-1]))
    assert share.instrument is SHARE.instrument
    with pytest.raises(KeyError, match=r"SYN\.MC has no derivatives pillar"):
        share.pillar(Pillar.DERIVATIVES)
    assert [r.pillar for r in coin.pillars] == [
        Pillar.TECHNICAL,
        Pillar.RISK,
        Pillar.DERIVATIVES,
        Pillar.QUALITY,
    ]
    assert coin.not_applicable == ()
    assert coin.pillar(Pillar.TECHNICAL).issue is PillarIssue.NO_DATA
    assert coin.pillar(Pillar.DERIVATIVES).fact("payments").value == 2
    standing = _positioning({PositioningField.LONG_SHORT_ACCOUNTS: [1.0, 2.0]})
    only_positioning = asset_card(
        COIN, confluence=None, structure=None, quality=assess_quality(COIN), positioning=standing
    )
    derivatives = only_positioning.pillar(Pillar.DERIVATIVES)
    assert (derivatives.issue, derivatives.fact("long_short_accounts").value) == (None, 2.0)
    assert _figure(coin.pillar(Pillar.RISK), "volatility") > 0


def test_a_figure_that_cannot_be_told_is_none_never_nan() -> None:
    flat = make_series(np.full(60, 50.0), symbol="FLAT.MC", index=business_days(60))

    reading = risk_pillar(flat)

    for fact in reading.facts:
        assert fact.value is None or isinstance(fact.value, str) or np.isfinite(fact.value)
    assert reading.fact("volatility").value == 0.0
