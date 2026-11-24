"""What trading costs on each market, on SYNTHETIC series (ADR-0051).

Taxes pay the rate in force on each day and follow the issuer; profiles say what they assume;
the funding of a perpetual is paid by the bar it settles in, and an unknown one is never zero.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from investinglab.analytics.search import Block, Leg, Operator, Slope, StrategySpec
from investinglab.domain import (
    ASSUMED_BORROW_BPS,
    ASSUMED_COMMISSION_BPS,
    COST_PROFILES,
    EXCHANGES,
    TRANSACTION_TAXES,
    USD,
    AssetClass,
    DataSource,
    DomainError,
    Frequency,
    Identifiers,
    PriceSeries,
    Product,
    RateKind,
    RateSeries,
    TaxRate,
    TransactionTax,
    backtest_strategy,
    cost_profile,
    default_profile,
    funding_per_bar,
    market_costs,
)
from support.factories import SYNTHETIC_SOURCE, gbm_prices, make_bars, make_instrument, make_series

PRICES = gbm_prices(260, sigma=0.4, seed=3)
DAYS = pd.bdate_range("2024-11-01", periods=len(PRICES))  # across France's 2025 rise
RISING = Slope(Leg("PRICE"), Operator.RISING, 1)
FALLING = Slope(Leg("PRICE"), Operator.FALLING, 1)
SWING = StrategySpec(entry=Block((RISING,)), exit=Block((FALLING,)))
SHORT_SWING = replace(SWING, direction="short")  # type: ignore[arg-type]


def _share(
    mic: str, *, isin: str | None = None, asset_class: AssetClass = AssetClass.EQUITY
) -> PriceSeries:
    instrument = replace(
        make_instrument("TEST", exchange=EXCHANGES[mic], asset_class=asset_class),
        identifiers=Identifiers(isin=isin),
    )
    return PriceSeries(
        instrument, Frequency.DAY_1, SYNTHETIC_SOURCE, make_bars(PRICES, DAYS, ohlc=True)
    )


def _coin(
    provider: str, *, index: pd.DatetimeIndex | None = None, frequency: Frequency = Frequency.DAY_1
) -> PriceSeries:
    days = index if index is not None else pd.date_range("2026-10-01", periods=30, freq="D")
    instrument = make_instrument(
        "BTC/USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=EXCHANGES["CRYPTO"]
    )
    source = DataSource(provider=provider, retrieved_at=datetime(2026, 11, 1, tzinfo=UTC))
    return PriceSeries(
        instrument, frequency, source, make_bars(PRICES[: len(days)], days, ohlc=True)
    )


# ── Taxes ──────────────────────────────────────────────────────────


def test_a_tax_charges_the_rate_in_force_on_each_day() -> None:
    ttf = TRANSACTION_TAXES["FR"]

    assert ttf.rate_on(date(2012, 7, 31)) == 0.0  # it did not exist yet
    assert ttf.rate_on(date(2016, 12, 31)) == 20.0
    assert ttf.rate_on(date(2025, 3, 31)) == 30.0
    assert ttf.rate_on(date(2025, 4, 1)) == 40.0
    assert TRANSACTION_TAXES["ES"].rate_on(date(2021, 1, 15)) == 0.0
    assert TRANSACTION_TAXES["ES"].rate_on(date(2021, 1, 16)) == 20.0
    assert TRANSACTION_TAXES["IT"].rate_on(date(2026, 1, 1)) == 20.0
    np.testing.assert_allclose(ttf.rates_on([date(2025, 3, 31), date(2025, 4, 1)]), [0.003, 0.004])
    assert all(tax.sources for tax in TRANSACTION_TAXES.values())


def test_a_tax_is_well_formed() -> None:
    with pytest.raises(DomainError, match="oldest first"):
        TransactionTax("X", "XX", (TaxRate(date(2020, 1, 1), 1), TaxRate(date(2019, 1, 1), 2)), "")
    with pytest.raises(DomainError, match="oldest first"):
        TransactionTax("X", "XX", (), "")
    with pytest.raises(DomainError, match="from 0 to 10,000"):
        TaxRate(date(2020, 1, 1), -1)


def test_the_tax_follows_the_issuer_and_is_presumed_without_an_isin() -> None:
    french = market_costs(_share("XPAR", isin="FR0000120271"))  # TotalEnergies
    dutch = market_costs(_share("XMAD", isin="NL0015001FS8"))  # a Dutch company in Madrid
    presumed = market_costs(_share("XPAR"))
    etf = market_costs(_share("XPAR", asset_class=AssetClass.ETF))
    small = market_costs(_share("XPAR"), taxable=False)
    xetra = market_costs(_share("XETR", isin="DE0007164600"))

    assert french.taxable
    assert not french.tax_presumed
    assert french.tax is not None
    assert french.tax.loc["2025-03-31"] == pytest.approx(0.003)
    assert french.tax.loc["2025-04-01"] == pytest.approx(0.004)
    assert not dutch.taxable
    assert dutch.tax is None
    assert presumed.taxable
    assert presumed.tax_presumed
    assert not etf.taxable
    assert not small.taxable
    assert not xetra.taxable  # Germany has no tax on purchases


# ── Profiles ───────────────────────────────────────────────────────


def test_every_venue_has_a_profile_that_says_what_it_assumes() -> None:
    equities = [mic for mic in EXCHANGES if mic not in {"CRYPTO", "FX"}]

    assert set(equities) <= set(COST_PROFILES)
    madrid = cost_profile("XMAD")
    assert madrid.commission_bps == ASSUMED_COMMISSION_BPS
    assert madrid.borrow_bps == ASSUMED_BORROW_BPS
    assert "commission_bps" in madrid.assumed
    assert madrid.tax is TRANSACTION_TAXES["ES"]
    assert cost_profile("XHKG").unmodelled  # its stamp duty charges both sides
    perpetual = cost_profile("binance-usdm")
    assert perpetual.product is Product.PERPETUAL
    assert perpetual.commission_bps == 5.0
    assert not cost_profile("binance-spot").shortable
    assert all(p.sources for p in COST_PROFILES.values() if p.product is Product.PERPETUAL)
    with pytest.raises(DomainError, match="Unknown cost profile 'NOPE'"):
        cost_profile("NOPE")


def test_the_default_profile_is_where_it_trades() -> None:
    index = make_series(symbol="^IBEX", asset_class=AssetClass.INDEX)

    assert default_profile(_share("XMAD")) is cost_profile("XMAD")
    assert default_profile(_coin("binance")) is cost_profile("binance-spot")
    assert default_profile(_coin("coingecko")) is None  # not a venue
    assert default_profile(index) is None
    with pytest.raises(DomainError, match="No cost profile for \\^IBEX"):
        market_costs(index)


def test_your_brokers_fees_replace_the_assumed_ones() -> None:
    mine = market_costs(
        _share("XMAD"), "XMAD", commission_bps=5, minimum_commission=3, slippage_bps=2
    )

    assert mine.costs.commission_bps == 5
    assert mine.costs.minimum_commission == 3
    assert mine.costs.slippage_bps == 2
    assert mine.costs.transaction_tax_bps == 0  # the tax goes day by day


def test_a_short_share_pays_its_borrow_by_calendar_day() -> None:
    costs = market_costs(_share("XMAD"))

    assert costs.borrow is not None
    rate = ASSUMED_BORROW_BPS / 10_000 / 365
    assert costs.borrow.loc["2024-11-01"] == pytest.approx(3 * rate)  # a Friday: until Monday
    assert costs.borrow.loc["2024-11-04"] == pytest.approx(rate)
    assert costs.borrow.iloc[-1] == 0.0
    assert market_costs(_coin("binance")).borrow is None  # a spot market lends nothing


# ── Funding ────────────────────────────────────────────────────────


def _funding(start: str, periods: int, rate: float = 0.0001) -> RateSeries:
    stamps = pd.date_range(start, periods=periods, freq="8h", tz="UTC")
    swap = make_instrument(
        "BTC/USDT:USDT", currency=USD, asset_class=AssetClass.CRYPTO, exchange=None
    )
    return RateSeries(
        swap, "binance", RateKind.FUNDING, SYNTHETIC_SOURCE, pd.Series(rate, index=stamps)
    )


def test_funding_is_paid_by_the_bar_it_settles_in() -> None:
    coin = _coin("binance")
    funding = _funding("2026-09-30 16:00", 3 * 33)

    paid = funding_per_bar(funding, coin)

    # Settlements at 08:00, 16:00 and the next 00:00: three a day.
    assert paid.iloc[0] == pytest.approx(0.0003)
    np.testing.assert_allclose(paid.iloc[1:].to_numpy(), 0.0003)


def test_funding_not_published_is_unknown_never_zero() -> None:
    coin = _coin("binance")
    late = _funding("2026-10-10 00:00", 3 * 10)

    paid = funding_per_bar(late, coin)

    # Settlements from 10 October 00:00 to 19 October 16:00.
    assert paid.loc[:"2026-10-09"].isna().all()  # its 08:00 and 16:00 are not published
    np.testing.assert_allclose(paid.loc["2026-10-10":"2026-10-18"].to_numpy(), 0.0003)
    assert paid.loc["2026-10-19":].isna().all()  # it ends with a settlement not published


def test_hourly_bars_pay_the_settlement_at_their_end() -> None:
    hours = pd.date_range("2026-10-01 00:00", periods=24, freq="h", tz="UTC")
    coin = _coin("binance", index=hours, frequency=Frequency.HOUR_1)

    paid = funding_per_bar(_funding("2026-09-30 16:00", 6), coin)

    settled = pd.DatetimeIndex(paid[paid > 0].index)
    assert list(settled.hour) == [7, 15, 23]  # the bars that end at 08:00, 16:00 and 00:00


# ── Backtests with a market's costs ────────────────────────────────


def test_a_backtest_pays_the_tax_of_each_purchase_day() -> None:
    share = _share("XPAR", isin="FR0000120271")
    taxed = backtest_strategy(share, SWING, costs=market_costs(share))
    untaxed = backtest_strategy(share, SWING, costs=market_costs(share, taxable=False))

    assert taxed.market is not None
    assert taxed.market.profile.key == "XPAR"
    assert taxed.costs.tax > 0
    assert untaxed.costs.tax == 0
    commission = ASSUMED_COMMISSION_BPS / 10_000
    days = {trade.entry_time >= pd.Timestamp("2025-04-01") for trade in taxed.trades}
    assert days == {False, True}  # trades on both sides of the rise
    for trade in taxed.trades:
        rate = 0.004 if trade.entry_time >= pd.Timestamp("2025-04-01") else 0.003
        bought = trade.notional * (1 - commission) / (1 + rate)  # what was left for shares
        assert trade.tax == pytest.approx(bought * rate)


def test_a_spot_market_cannot_be_sold_short() -> None:
    coin = _coin("binance")

    with pytest.raises(DomainError, match=r"cannot be sold short.*binance-usdm"):
        backtest_strategy(coin, SHORT_SWING, costs=market_costs(coin))


def test_a_perpetual_needs_its_funding_and_pays_it() -> None:
    coin = _coin("binance")
    perpetual = market_costs(coin, "binance-usdm")
    funding = funding_per_bar(_funding("2026-09-30 16:00", 3 * 31), coin)

    with pytest.raises(DomainError, match="is a perpetual: give its funding"):
        backtest_strategy(coin, SHORT_SWING, costs=perpetual)
    result = backtest_strategy(coin, SHORT_SWING, costs=perpetual, funding=funding)

    assert result.costs.funding < 0  # a short earns a positive funding
    assert result.costs.borrow == 0  # nothing is borrowed


def test_an_unknown_funding_is_refused() -> None:
    coin = _coin("binance")
    perpetual = market_costs(coin, "binance-usdm")
    partial = funding_per_bar(_funding("2026-10-10 00:00", 30), coin)

    with pytest.raises(DomainError, match=r"funding is unknown at .* bars"):
        backtest_strategy(coin, SWING, costs=perpetual, funding=partial)


def test_a_short_share_pays_the_assumed_borrow() -> None:
    share = _share("XMAD")

    result = backtest_strategy(share, SHORT_SWING, costs=market_costs(share))

    assert result.costs.borrow > 0


def test_intraday_bars_pay_the_tax_of_their_local_day() -> None:
    hours = pd.date_range("2025-03-31 13:00", periods=24, freq="h", tz="UTC")  # 15:00 in Paris
    instrument = make_instrument("MC.PA", exchange=EXCHANGES["XPAR"])
    bars = make_bars(PRICES[:24], hours, ohlc=True)
    series = PriceSeries(instrument, Frequency.HOUR_1, SYNTHETIC_SOURCE, bars)

    tax = market_costs(series).tax

    assert tax is not None
    assert tax.iloc[0] == pytest.approx(0.003)  # 31 March in Paris
    assert tax.iloc[-1] == pytest.approx(0.004)  # 1 April in Paris


def test_a_backtest_trades_from_a_later_bar_after_warming_up() -> None:
    share = _share("XMAD")
    later = DAYS[100]

    result = backtest_strategy(share, SWING, costs=market_costs(share), trade_from=later)

    assert result.equity.index[0] == later
    assert result.market is not None
    assert result.market.tax is not None
    assert result.market.tax.index.equals(result.equity.index)
    with pytest.raises(DomainError, match="has no bars from"):
        backtest_strategy(share, SWING, trade_from=DAYS[-1] + pd.Timedelta(days=30))
