"""Currencies, currency pairs and quote units.

Currency codes are validated against ISO 4217 (plus precious metals and the digital assets
used as quote currencies). Market-data providers sometimes quote prices in *minor units*
(London stocks in pence, ``GBp``); :func:`parse_quote_currency` turns those codes into the
major currency plus the scale factor needed to normalise the prices, a classic source of
100x errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from investinglab.domain.errors import DomainError, UnknownCurrencyError

__all__ = [
    "CHF",
    "EUR",
    "GBP",
    "JPY",
    "USD",
    "Currency",
    "CurrencyKind",
    "CurrencyPair",
    "QuoteUnit",
    "parse_quote_currency",
]

# Active ISO 4217 codes plus a few recently withdrawn ones still found in historical data
# (HRK until 2023, BGN until 2026, ANG until 2025).
_ISO_4217_FIAT = frozenset(
    [
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HRK",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "UYU",
        "UZS",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XCD",
        "XCG",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWG",
    ]
)
_ISO_4217_METALS = frozenset({"XAU", "XAG", "XPT", "XPD"})
# Digital assets commonly used as the *quote* side of crypto pairs.
_DIGITAL = frozenset({"BTC", "ETH", "BNB", "SOL", "USDT", "USDC", "DAI", "FDUSD", "EURC"})


class CurrencyKind(StrEnum):
    """Nature of a currency."""

    FIAT = "fiat"
    METAL = "metal"
    DIGITAL = "digital"


@dataclass(frozen=True, slots=True, order=True)
class Currency:
    """A currency identified by its upper-case code (``EUR``, ``USD``, ``XAU``, ``USDT``...).

    Raises:
        UnknownCurrencyError: If the code is not a known ISO 4217, metal or supported
            digital-asset code. Codes are case-sensitive on purpose: ``GBp`` (pence) is a
            quote unit, not a currency; see :func:`parse_quote_currency`.
    """

    code: str

    def __post_init__(self) -> None:
        if self.code not in _ISO_4217_FIAT | _ISO_4217_METALS | _DIGITAL:
            raise UnknownCurrencyError(
                f"Unknown currency code {self.code!r}. Expected an upper-case ISO 4217 code "
                "(e.g. 'EUR'); minor-unit quotes such as 'GBp' must go through "
                "parse_quote_currency()."
            )

    @property
    def kind(self) -> CurrencyKind:
        """Whether the currency is fiat, a precious metal or a digital asset."""
        if self.code in _ISO_4217_METALS:
            return CurrencyKind.METAL
        if self.code in _DIGITAL:
            return CurrencyKind.DIGITAL
        return CurrencyKind.FIAT

    def __str__(self) -> str:
        return self.code


EUR = Currency("EUR")
USD = Currency("USD")
GBP = Currency("GBP")
CHF = Currency("CHF")
JPY = Currency("JPY")


@dataclass(frozen=True, slots=True)
class CurrencyPair:
    """An exchange-rate pair: the price of one unit of ``base`` expressed in ``quote``.

    ``CurrencyPair(EUR, USD)`` (``EURUSD``) quoted at 1.08 means 1 EUR = 1.08 USD.
    """

    base: Currency
    quote: Currency

    def __post_init__(self) -> None:
        if self.base == self.quote:
            raise DomainError(f"A currency pair needs two different currencies, got {self.base}")

    @property
    def symbol(self) -> str:
        """Six-letter market convention, e.g. ``EURUSD``."""
        return f"{self.base.code}{self.quote.code}"

    def inverse(self) -> CurrencyPair:
        """The opposite pair (``USDEUR`` for ``EURUSD``)."""
        return CurrencyPair(self.quote, self.base)

    @classmethod
    def parse(cls, text: str) -> CurrencyPair:
        """Parse ``"EURUSD"``, ``"EUR/USD"`` or ``"EUR-USD"`` into a pair."""
        cleaned = text.strip().upper().replace("/", "").replace("-", "")
        if len(cleaned) != 6:  # noqa: PLR2004 - two ISO codes
            raise DomainError(f"Cannot parse currency pair {text!r}")
        return cls(Currency(cleaned[:3]), Currency(cleaned[3:]))

    def __str__(self) -> str:
        return self.symbol


@dataclass(frozen=True, slots=True)
class QuoteUnit:
    """The unit in which a provider quotes prices.

    Attributes:
        currency: The major currency the prices belong to.
        scale: Multiply quoted prices by this factor to express them in ``currency``
            (``0.01`` for prices quoted in pence).
    """

    currency: Currency
    scale: float = 1.0

    def __post_init__(self) -> None:
        if not self.scale > 0:
            raise DomainError(f"Quote scale must be positive, got {self.scale}")


# Provider codes for prices quoted in minor units → (major currency, scale to major units).
_MINOR_UNITS: MappingProxyType[str, tuple[str, float]] = MappingProxyType(
    {
        "GBp": ("GBP", 0.01),
        "GBX": ("GBP", 0.01),
        "ZAc": ("ZAR", 0.01),
        "ZAC": ("ZAR", 0.01),
        "ILA": ("ILS", 0.01),
        "KWF": ("KWD", 0.001),
    }
)


def parse_quote_currency(raw: str) -> QuoteUnit:
    """Interpret a provider's currency string, resolving minor units.

    Examples:
        >>> parse_quote_currency("GBp")
        QuoteUnit(currency=Currency(code='GBP'), scale=0.01)
        >>> parse_quote_currency("usd")
        QuoteUnit(currency=Currency(code='USD'), scale=1.0)
    """
    text = raw.strip()
    minor = _MINOR_UNITS.get(text)
    if minor is not None:
        code, scale = minor
        return QuoteUnit(Currency(code), scale)
    return QuoteUnit(Currency(text.upper()))
