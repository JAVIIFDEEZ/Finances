"""What trading costs on each market: profiles with their sources and dates (ADR-0051).

A backtest's costs are not one number. They come from four places, and each is told apart:

* **The venue's fee.** A crypto exchange publishes it: the taker fee, since the backtest's
  orders are market orders at the next open (Binance's spot and perpetual, Kraken Pro's and
  Coinbase Advanced's entry tiers, as of :attr:`CostProfile.as_of`).
* **The broker's commission** on a stock exchange, which depends on the broker: the profiles
  *assume* 0.10 % of each order and say so (:attr:`CostProfile.assumed`). Give yours.
* **Taxes on purchases** (:class:`TransactionTax`): Spain's ITF, France's TTF, Italy's IFTT
  and the United Kingdom's stamp duty. Each one with its **rate over time**, so that a
  backtest pays the rate in force on each day (none before the tax existed), and its law or
  official list as the source.
* **Carry:** the funding of a perpetual, from its published rates (:func:`funding_per_bar`),
  and the borrow of a short share, assumed at 0.50 % a year.

**Who pays a tax.** These taxes follow the issuer, not the venue: a Dutch company listed in
Madrid does not pay the ITF. With an ISIN, its country decides; without one, a share listed
on the tax's home exchange is *presumed* in scope, which overcharges the small companies
below the threshold (``taxable=False`` says otherwise). ETFs and funds are out of scope.

What a profile does not model is listed with it (:attr:`CostProfile.unmodelled`): Belgium's
stock exchange tax depends on the investor's residence; Hong Kong's stamp duty charges both
sides; the SEC's fee on US sales is a fifth of a basis point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from investinglab.analytics.backtest import BPS, CostModel
from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import EXCHANGES, AssetClass

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from investinglab.domain.rate_series import RateSeries
    from investinglab.domain.series import PriceSeries

__all__ = [
    "ASSUMED_BORROW_BPS",
    "ASSUMED_COMMISSION_BPS",
    "ASSUMED_SLIPPAGE_BPS",
    "COST_PROFILES",
    "TRANSACTION_TAXES",
    "CostProfile",
    "MarketCosts",
    "Product",
    "TaxRate",
    "TransactionTax",
    "cost_profile",
    "default_profile",
    "funding_per_bar",
    "market_costs",
]

ASSUMED_COMMISSION_BPS: Final = 10.0
"""An online broker's commission on a stock exchange, assumed: 0.10 % of each order."""

ASSUMED_SLIPPAGE_BPS: Final = 5.0
"""Half the spread plus the impact of an order, assumed: 0.05 % (a liquid instrument)."""

ASSUMED_BORROW_BPS: Final = 50.0
"""Yearly fee to borrow a share to short it, assumed: 0.50 % (an easy-to-borrow one)."""

DAYS_PER_YEAR: Final = 365.0
"""Borrow accrues by calendar day."""


@dataclass(frozen=True, slots=True)
class TaxRate:
    """A tax's rate from a date on (until the next one), in basis points."""

    since: date
    bps: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.bps) and 0 <= self.bps < BPS):
            raise DomainError(f"A tax rate must be from 0 to 10,000 bps, got {self.bps}")


@dataclass(frozen=True, slots=True)
class TransactionTax:
    """A tax on purchases of shares, charged by the issuer's country, with its rates over time.

    Attributes:
        code: Its usual name (``ITF``, ``TTF``...).
        country: ISO 3166 code of the issuers it taxes: the first two letters of their ISINs.
        rates: Its rates, oldest first; before the first, it did not exist.
        scope: What it taxes, as the law says.
        sources: The law and the official list of the companies in scope.

    Raises:
        DomainError: No rates, or rates not in order.
    """

    code: str
    country: str
    rates: tuple[TaxRate, ...]
    scope: str
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        days = [rate.since for rate in self.rates]
        if not days or days != sorted(set(days)):
            raise DomainError(f"{self.code}: its rates must be given oldest first, once a day")

    def rate_on(self, day: date) -> float:
        """The rate in force on ``day``, in basis points (0 before the tax existed)."""
        found = 0.0
        for rate in self.rates:
            if rate.since <= day:
                found = rate.bps
        return found

    def rates_on(self, days: Sequence[date]) -> np.ndarray:
        """The rate in force on each day, as a decimal of the amount bought."""
        return np.array([self.rate_on(day) / BPS for day in days], dtype=np.float64)


TRANSACTION_TAXES: Final[Mapping[str, TransactionTax]] = MappingProxyType(
    {
        "ES": TransactionTax(
            "ITF",
            "ES",
            (TaxRate(date(2021, 1, 16), 20.0),),
            "Purchases of shares of Spanish companies with a market capitalisation above "
            "€1,000 million on 1 December of the year before (the AEAT's yearly list).",
            (
                "https://www.boe.es/boe/dias/2020/10/16/pdfs/BOE-A-2020-12356.pdf",
                "https://sede.agenciatributaria.gob.es/Sede/declaraciones-informativas-otros-impuestos-tasas/impuesto-sobre-transacciones-financieras.html",
            ),
        ),
        "FR": TransactionTax(
            "TTF",
            "FR",
            (
                TaxRate(date(2012, 8, 1), 20.0),
                TaxRate(date(2017, 1, 1), 30.0),
                TaxRate(date(2025, 4, 1), 40.0),
            ),
            "Purchases of shares of French companies with a market capitalisation above "
            "€1,000 million on 1 December of the year before (the BOFiP's yearly list).",
            (
                "https://bofip.impots.gouv.fr/doctrine/BOI-ANNX-000467",
                "https://www.legifiscal.fr/actualites-fiscales/4078-hausse-taxe-transactions-financieres-1ier-avril-2025.html",
            ),
        ),
        "IT": TransactionTax(
            "IFTT",
            "IT",
            (TaxRate(date(2014, 1, 1), 10.0), TaxRate(date(2026, 1, 1), 20.0)),
            "Purchases on a regulated market of shares of Italian companies, but for those "
            "whose average market capitalisation in November of the year before was below "
            "€500 million (Consob's yearly list). Off a regulated market, twice the rate.",
            (
                "https://www.clearygottlieb.com/~/media/organize-archive/cgsh/files/publication-pdfs/italy-introduces-a-financial-transaction-tax-as-of-2013.pdf",
                "https://luxcsd.com/luxcsd-en/products-and-services/assetservices/l26002-4893492",
            ),
        ),
        "GB": TransactionTax(
            "SDRT",
            "GB",
            (TaxRate(date(1986, 10, 27), 50.0),),
            "Purchases of shares of UK companies, but for those admitted to AIM and, for "
            "three years from 27 November 2025, new listings on a UK regulated market.",
            (
                "https://www.gov.uk/tax-buy-shares/buying-shares-electronically",
                "https://www.londonstockexchange.com/equities-trading/stamp-duty-exemption",
            ),
        ),
    }
)
"""The transaction taxes on purchases of shares, by the issuers' country."""

_HOME_TAX: Final = {"XMAD": "ES", "XPAR": "FR", "XMIL": "IT", "XLON": "GB"}
"""The exchange whose listings are presumed issued in the tax's country, without an ISIN."""

_TAXED: Final = frozenset({AssetClass.EQUITY})
"""What the taxes tax: shares (ETFs and funds are out of their scope)."""


class Product(StrEnum):
    """What is bought: the thing itself, or a perpetual swap on it."""

    CASH = "cash"
    """Shares, or spot crypto: bought with cash and held. A short borrows the units."""
    PERPETUAL = "perpetual"
    """A perpetual swap: no units change hands, and both sides pay or earn the funding."""


@dataclass(frozen=True, slots=True)
class CostProfile:
    """What trading costs on one market or venue.

    Attributes:
        key: How it is chosen (``XMAD``, ``binance-spot``...).
        name: What it is.
        as_of: When its fees were read from their sources.
        commission_bps: Commission (or the venue's taker fee) on each order.
        slippage_bps: Half the spread plus the impact of each order.
        minimum_commission: Least commission an order pays, in the instrument's currency.
        tax: The tax on purchases of the shares listed there, if any.
        product: What is bought.
        shortable: Whether it can be sold short (a spot crypto market cannot).
        borrow_bps: Yearly fee to borrow what a short sells (cash products).
        venue: The crypto venue it is the fees of (its funding comes from there too).
        sources: Where its fees come from.
        assumed: Which of its figures are assumptions, not published fees.
        unmodelled: Costs of this market a backtest leaves out, and why.
    """

    key: str
    name: str
    as_of: date
    commission_bps: float
    slippage_bps: float = ASSUMED_SLIPPAGE_BPS
    minimum_commission: float = 0.0
    tax: TransactionTax | None = None
    product: Product = Product.CASH
    shortable: bool = True
    borrow_bps: float = 0.0
    venue: str | None = None
    sources: tuple[str, ...] = ()
    assumed: tuple[str, ...] = ()
    unmodelled: tuple[str, ...] = ()


_AS_OF: Final = date(2026, 11, 24)
_SEC_FEE: Final = (
    "The SEC's fee on sales (Section 31: $20.60 per million since 4 April 2026, "
    "a fifth of a basis point)."
)
_UNMODELLED: Final[Mapping[str, tuple[str, ...]]] = {
    "XNYS": (_SEC_FEE,),
    "XNAS": (_SEC_FEE,),
    "ARCX": (_SEC_FEE,),
    "XBRU": ("Belgium's stock exchange tax (TOB): it depends on the investor's residence.",),
    "XHKG": ("Hong Kong's stamp duty (0.10 % of each side): the engine taxes purchases only.",),
    "XSWX": ("The Swiss securities transfer stamp duty: it depends on the dealer.",),
    "XMIL": ("The IFTT from March to December 2013: its first rates are not recorded here.",),
}
_EQUITY_ASSUMED: Final = ("commission_bps", "slippage_bps", "borrow_bps")


def _equity(mic: str) -> CostProfile:
    exchange = EXCHANGES[mic]
    tax = TRANSACTION_TAXES[_HOME_TAX[mic]] if mic in _HOME_TAX else None
    return CostProfile(
        key=mic,
        name=f"{exchange.name}, through an online broker",
        as_of=_AS_OF,
        commission_bps=ASSUMED_COMMISSION_BPS,
        tax=tax,
        borrow_bps=ASSUMED_BORROW_BPS,
        sources=() if tax is None else tax.sources,
        assumed=_EQUITY_ASSUMED,
        unmodelled=_UNMODELLED.get(mic, ()),
    )


_CRYPTO: Final = (
    CostProfile(
        key="binance-spot",
        venue="binance",
        name="Binance spot, regular tier (taker, without the BNB discount)",
        as_of=_AS_OF,
        commission_bps=10.0,
        shortable=False,
        sources=("https://www.binance.com/en/fee/schedule",),
        assumed=("slippage_bps",),
    ),
    CostProfile(
        key="binance-usdm",
        venue="binance",
        name="Binance USDⓈ-M perpetuals, regular tier (taker)",
        as_of=_AS_OF,
        commission_bps=5.0,
        product=Product.PERPETUAL,
        sources=("https://www.binance.com/en/support/faq/360033544231",),
        assumed=("slippage_bps",),
        unmodelled=("The basis: it is traded at the spot pair's prices.",),
    ),
    CostProfile(
        key="kraken-spot",
        venue="kraken",
        name="Kraken Pro spot, tier 1 (taker, since 9 July 2026)",
        as_of=_AS_OF,
        commission_bps=80.0,
        shortable=False,
        sources=("https://blog.kraken.com/product/pro/new-kraken-pro-fee-tiers",),
        assumed=("slippage_bps",),
    ),
    CostProfile(
        key="coinbase-spot",
        venue="coinbase",
        name="Coinbase Advanced spot, entry tier in the EU and UK (taker, since 16 Sep 2026)",
        as_of=_AS_OF,
        commission_bps=50.0,
        shortable=False,
        sources=(
            "https://help.coinbase.com/en/coinbase/trading-and-funding/advanced-trade/advanced-trade-fees",
        ),
        assumed=("slippage_bps",),
    ),
)

COST_PROFILES: Final[Mapping[str, CostProfile]] = MappingProxyType(
    {
        **{mic: _equity(mic) for mic in EXCHANGES if mic not in {"CRYPTO", "FX"}},
        **{profile.key: profile for profile in _CRYPTO},
    }
)
"""Every profile by key: one per stock exchange (its MIC) and one per crypto venue product."""


def cost_profile(key: str) -> CostProfile:
    """The profile called ``key``.

    Raises:
        DomainError: An unknown key.
    """
    found = COST_PROFILES.get(key)
    if found is None:
        raise DomainError(f"Unknown cost profile {key!r}; known: {sorted(COST_PROFILES)}")
    return found


def default_profile(series: PriceSeries) -> CostProfile | None:
    """The profile of where ``series`` trades: its exchange, or its crypto venue's spot.

    ``None`` for what has no profile: an index (it cannot be bought), a currency pair, or a
    venue without one.
    """
    instrument = series.instrument
    if instrument.asset_class is AssetClass.CRYPTO:
        venue = series.source.provider
        spot = [p for p in _CRYPTO if p.venue == venue and p.product is Product.CASH]
        return spot[0] if spot else None
    if instrument.asset_class in {AssetClass.INDEX, AssetClass.FX}:
        return None
    exchange = instrument.exchange
    return None if exchange is None else COST_PROFILES.get(exchange.code)


@dataclass(frozen=True, slots=True)
class MarketCosts:
    """What trading one series costs under a profile.

    Attributes:
        profile: The profile.
        costs: Commission, minimum and slippage of each order.
        taxable: Whether the purchases pay the profile's tax.
        tax_presumed: Whether that was presumed (no ISIN said the issuer's country).
        tax: The tax rate in force at each bar (a decimal of the amount bought), if taxable.
        borrow: The borrow fee of each bar for a short (a decimal of its value).
    """

    profile: CostProfile
    costs: CostModel
    taxable: bool = False
    tax_presumed: bool = False
    tax: pd.Series | None = field(default=None, repr=False)
    borrow: pd.Series | None = field(default=None, repr=False)

    @property
    def perpetual(self) -> bool:
        """Whether a perpetual is traded: the funding must be given."""
        return self.profile.product is Product.PERPETUAL

    def on(self, index: pd.Index) -> MarketCosts:
        """The same costs on some of the bars (a backtest that trades from a later date)."""
        return replace(
            self,
            tax=None if self.tax is None else self.tax.loc[index],
            borrow=None if self.borrow is None else self.borrow.loc[index],
        )


def _issued_in(series: PriceSeries, tax: TransactionTax) -> tuple[bool, bool]:
    """Whether ``series`` pays ``tax``, and whether that is presumed."""
    instrument = series.instrument
    if instrument.asset_class not in _TAXED:
        return False, False
    isin = instrument.identifiers.isin
    if isin is not None:
        return isin[:2] == tax.country, False
    return True, True


def _session_days(series: PriceSeries) -> list[date]:
    index = series.bars.index
    assert isinstance(index, pd.DatetimeIndex)  # noqa: S101 - validated by PriceSeries
    if series.frequency.is_intraday:
        index = index.tz_convert(series.timezone).tz_localize(None)
    return [stamp.date() for stamp in index]


def _borrow(series: PriceSeries, bps: float) -> pd.Series:
    """The borrow fee of each bar: the yearly fee over the calendar days to the next bar."""
    index = series.bars.index
    days = np.diff(index.to_numpy()).astype("timedelta64[s]").astype(np.float64) / 86_400.0
    fee = np.append(days, 0.0) * (bps / BPS) / DAYS_PER_YEAR
    return pd.Series(fee, index=index, name="borrow")


def market_costs(
    series: PriceSeries,
    profile: CostProfile | str | None = None,
    *,
    taxable: bool | None = None,
    commission_bps: float | None = None,
    minimum_commission: float | None = None,
    slippage_bps: float | None = None,
) -> MarketCosts:
    """What trading ``series`` costs under ``profile`` (where it trades by default).

    Args:
        series: What is traded.
        profile: A profile or its key; the one of its exchange or crypto venue by default.
        taxable: Whether its purchases pay the profile's tax, overriding the presumption
            (a company below the threshold does not).
        commission_bps: Your broker's commission, instead of the profile's.
        minimum_commission: Your broker's minimum per order.
        slippage_bps: Your estimate of half the spread plus the impact.

    Raises:
        DomainError: No profile for where it trades, or an unknown one.
    """
    if isinstance(profile, str):
        profile = cost_profile(profile)
    chosen = profile or default_profile(series)
    if chosen is None:
        raise DomainError(
            f"No cost profile for {series.instrument.symbol}: choose one of "
            f"{sorted(COST_PROFILES)} or give its costs"
        )
    costs = CostModel(
        commission_bps=chosen.commission_bps if commission_bps is None else commission_bps,
        minimum_commission=chosen.minimum_commission
        if minimum_commission is None
        else minimum_commission,
        slippage_bps=chosen.slippage_bps if slippage_bps is None else slippage_bps,
    )
    pays, presumed = (False, False) if chosen.tax is None else _issued_in(series, chosen.tax)
    if taxable is not None:
        pays, presumed = taxable and chosen.tax is not None, False
    tax = None
    if pays and chosen.tax is not None:
        rates = chosen.tax.rates_on(_session_days(series))
        tax = pd.Series(rates, index=series.bars.index, name="tax")
    borrow = None
    if chosen.product is Product.CASH and chosen.shortable and chosen.borrow_bps > 0:
        borrow = _borrow(series, chosen.borrow_bps)
    return MarketCosts(
        profile=chosen,
        costs=costs,
        taxable=pays,
        tax_presumed=presumed,
        tax=tax,
        borrow=borrow,
    )


def _bar_spans(series: PriceSeries) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """When each bar starts and ends, in UTC."""
    index = series.bars.index
    assert isinstance(index, pd.DatetimeIndex)  # noqa: S101 - validated by PriceSeries
    if series.frequency.is_intraday:
        starts = index
        ends = index + pd.Timedelta(minutes=series.frequency.minutes or 0)
    else:
        local = index.tz_localize(series.timezone)
        starts = local.tz_convert("UTC")
        ends = (local + pd.Timedelta(days=1)).tz_convert("UTC")
        if len(index) > 1:  # a weekly or monthly bar ends where the next starts
            ends = pd.DatetimeIndex([*starts[1:], ends[-1]])
    return starts, ends


def funding_per_bar(rates: RateSeries, series: PriceSeries) -> pd.Series:
    """The funding paid over each bar: the rates settled after its start, up to its end.

    A position open at a bar's close pays (or earns) every settlement of that bar, the one
    at its very end included. A bar the rates do not cover (before the first settlement or
    after the last) is ``NaN``: unknown, never zero.
    """
    starts, ends = _bar_spans(series)
    settled = rates.rates
    stamps = settled.index
    values = settled.to_numpy(dtype=np.float64)
    interval = rates.interval or pd.Timedelta(hours=8)
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    upto_end = stamps.searchsorted(ends, side="right")
    upto_start = stamps.searchsorted(starts, side="right")
    paid = cumulative[upto_end] - cumulative[upto_start]
    covered = (starts >= stamps[0] - interval) & (ends < stamps[-1] + interval)
    return pd.Series(np.where(covered, paid, np.nan), index=series.bars.index, name="funding")
