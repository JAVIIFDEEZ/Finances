"""Tradable instruments, the venues they trade on and their security identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from investinglab.domain.errors import DomainError, InvalidIdentifierError
from investinglab.domain.time import (
    CRYPTO_SCHEDULE,
    EQUITY_SCHEDULE,
    FX_SCHEDULE,
    MarketSchedule,
)

if TYPE_CHECKING:
    from investinglab.domain.money import Currency

__all__ = [
    "EXCHANGES",
    "AssetClass",
    "Exchange",
    "Identifiers",
    "Instrument",
    "is_valid_isin",
    "is_valid_lei",
]


class AssetClass(StrEnum):
    """Broad asset class of an instrument."""

    EQUITY = "equity"
    ETF = "etf"
    FUND = "fund"
    INDEX = "index"
    BOND = "bond"
    FX = "fx"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    FUTURE = "future"

    @property
    def default_schedule(self) -> MarketSchedule:
        """Schedule assumed when the instrument's venue is unknown."""
        if self is AssetClass.CRYPTO:
            return CRYPTO_SCHEDULE
        if self is AssetClass.FX:
            return FX_SCHEDULE
        return EQUITY_SCHEDULE


# ──────────────────────────────────────────────────────────────────────
# Venues
# ──────────────────────────────────────────────────────────────────────

_VENUE_CODE = re.compile(r"^[A-Z0-9]{2,10}$")


@dataclass(frozen=True, slots=True)
class Exchange:
    """A trading venue.

    Attributes:
        code: ISO 10383 MIC when the venue has one (``XNYS``, ``XMAD``), otherwise a
            reserved pseudo-code (``CRYPTO``, ``FX``).
        name: Human-readable name.
        timezone: IANA timezone of the venue; daily session labels are dates in this zone.
        schedule: Schedule used to annualise statistics.
    """

    code: str
    name: str
    timezone: str
    schedule: MarketSchedule = EQUITY_SCHEDULE

    def __post_init__(self) -> None:
        if not _VENUE_CODE.fullmatch(self.code):
            raise DomainError(f"Invalid venue code {self.code!r}")
        if not self.name.strip():
            raise DomainError("Exchange name must not be empty")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise DomainError(f"Unknown IANA timezone {self.timezone!r}") from error

    @property
    def tz(self) -> ZoneInfo:
        """The venue timezone as a :class:`zoneinfo.ZoneInfo`."""
        return ZoneInfo(self.timezone)


def _venue(code: str, name: str, timezone: str, hours: float) -> Exchange:
    return Exchange(code, name, timezone, MarketSchedule(252, hours))


EXCHANGES: MappingProxyType[str, Exchange] = MappingProxyType(
    {
        venue.code: venue
        for venue in (
            _venue("XNYS", "New York Stock Exchange", "America/New_York", 6.5),
            _venue("XNAS", "Nasdaq", "America/New_York", 6.5),
            _venue("ARCX", "NYSE Arca", "America/New_York", 6.5),
            _venue("XTSE", "Toronto Stock Exchange", "America/Toronto", 6.5),
            _venue("XMAD", "Bolsa de Madrid (BME)", "Europe/Madrid", 8.5),
            _venue("XETR", "Xetra", "Europe/Berlin", 8.5),
            _venue("XPAR", "Euronext Paris", "Europe/Paris", 8.5),
            _venue("XAMS", "Euronext Amsterdam", "Europe/Amsterdam", 8.5),
            _venue("XBRU", "Euronext Brussels", "Europe/Brussels", 8.5),
            _venue("XLIS", "Euronext Lisbon", "Europe/Lisbon", 8.5),
            _venue("XMIL", "Borsa Italiana", "Europe/Rome", 8.5),
            _venue("XLON", "London Stock Exchange", "Europe/London", 8.5),
            _venue("XSWX", "SIX Swiss Exchange", "Europe/Zurich", 8.5),
            _venue("XSTO", "Nasdaq Stockholm", "Europe/Stockholm", 8.5),
            _venue("XTKS", "Tokyo Stock Exchange", "Asia/Tokyo", 5.5),
            _venue("XHKG", "Hong Kong Exchanges", "Asia/Hong_Kong", 5.5),
            _venue("XASX", "Australian Securities Exchange", "Australia/Sydney", 6.0),
            Exchange("CRYPTO", "Crypto-asset markets (24/7)", "UTC", CRYPTO_SCHEDULE),
            Exchange("FX", "Spot foreign exchange (24/5)", "UTC", FX_SCHEDULE),
        )
    }
)
"""Known venues by code. Providers map their own symbols onto these."""


# ──────────────────────────────────────────────────────────────────────
# Identifiers
# ──────────────────────────────────────────────────────────────────────

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
_FIGI = re.compile(r"^[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]$")
_FIGI_FORBIDDEN_PREFIXES = frozenset({"BS", "BM", "GG", "GB", "GH", "KY", "VG"})
_CIK = re.compile(r"^[0-9]{1,10}$")


def _alnum_to_digits(text: str) -> str:
    """Map ``0-9`` to themselves and ``A-Z`` to ``10-35`` (ISO 6166 / ISO 7064)."""
    return "".join(str(int(char, 36)) for char in text)


def is_valid_isin(isin: str) -> bool:
    """Validate an ISIN (ISO 6166): format plus Luhn check digit on the expanded digits."""
    if not _ISIN.fullmatch(isin):
        return False
    digits = _alnum_to_digits(isin[:-1])
    total = 0
    # Double every second digit starting from the rightmost digit of the payload.
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 0:
            value *= 2
        total += value // 10 + value % 10
    return (10 - total % 10) % 10 == int(isin[-1])


def is_valid_lei(lei: str) -> bool:
    """Validate an LEI (ISO 17442): format plus ISO 7064 MOD 97-10 checksum."""
    return bool(_LEI.fullmatch(lei)) and int(_alnum_to_digits(lei)) % 97 == 1


@dataclass(frozen=True, slots=True)
class Identifiers:
    """Standard security identifiers of an instrument.

    Tickers are *not* stable identifiers: they change with mergers and differ between
    providers, so these are kept alongside the symbol.

    Attributes:
        isin: ISO 6166 International Securities Identification Number (checksum verified).
        figi: Financial Instrument Global Identifier (format verified).
        cik: SEC Central Index Key, normalised to 10 digits.
        lei: ISO 17442 Legal Entity Identifier of the issuer (checksum verified).
    """

    isin: str | None = None
    figi: str | None = None
    cik: str | None = None
    lei: str | None = None

    def __post_init__(self) -> None:
        if self.isin is not None and not is_valid_isin(self.isin):
            raise InvalidIdentifierError(f"Invalid ISIN {self.isin!r}")
        if self.figi is not None and (
            not _FIGI.fullmatch(self.figi) or self.figi[:2] in _FIGI_FORBIDDEN_PREFIXES
        ):
            raise InvalidIdentifierError(f"Invalid FIGI {self.figi!r}")
        if self.cik is not None:
            if not _CIK.fullmatch(self.cik):
                raise InvalidIdentifierError(f"Invalid CIK {self.cik!r}")
            object.__setattr__(self, "cik", self.cik.zfill(10))
        if self.lei is not None and not is_valid_lei(self.lei):
            raise InvalidIdentifierError(f"Invalid LEI {self.lei!r}")


# ──────────────────────────────────────────────────────────────────────
# Instruments
# ──────────────────────────────────────────────────────────────────────

_SYMBOL = re.compile(r"^[A-Za-z0-9.^=\-_/:]{1,32}$")


@dataclass(frozen=True, slots=True)
class Instrument:
    """A tradable (or observable) instrument.

    Attributes:
        symbol: Canonical symbol inside InvestingLab (Yahoo-style by default: ``SAN.MC``,
            ``^GSPC``, ``EURUSD=X``, ``BTC-USD``). Provider-specific symbols are mapped by
            the adapters.
        name: Human-readable name.
        asset_class: Broad asset class.
        currency: Currency the prices are expressed in.
        exchange: Venue whose calendar and timezone apply, if known.
        identifiers: Stable security identifiers, when available.
    """

    symbol: str
    name: str
    asset_class: AssetClass
    currency: Currency
    exchange: Exchange | None = None
    identifiers: Identifiers = field(default_factory=Identifiers)

    def __post_init__(self) -> None:
        if not _SYMBOL.fullmatch(self.symbol):
            raise DomainError(
                f"Invalid symbol {self.symbol!r}: 1-32 characters among letters, digits "
                "and . ^ = - _ / :"
            )
        if not self.name.strip():
            raise DomainError(f"Instrument {self.symbol!r} needs a name")

    @property
    def schedule(self) -> MarketSchedule:
        """Schedule of the venue, or the asset-class default when the venue is unknown."""
        return self.exchange.schedule if self.exchange else self.asset_class.default_schedule

    @property
    def timezone(self) -> str:
        """IANA timezone of the venue (``UTC`` when unknown)."""
        return self.exchange.timezone if self.exchange else "UTC"
