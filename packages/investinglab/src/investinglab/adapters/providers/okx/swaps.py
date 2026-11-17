"""OKX's perpetual swaps: their identifiers, instruments and error codes (ADR-0032).

Shared by every statistic read from OKX (funding, positioning): ``BTC/USDT:USDT`` is the
linear swap settled in USDT (``BTC-USDT-SWAP``) and ``BTC/USD:BTC`` the inverse one settled
in bitcoin (``BTC-USD-SWAP``).
"""

from __future__ import annotations

import re
from typing import Final

from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import EXCHANGES, AssetClass, Instrument
from investinglab.domain.money import Currency
from investinglab.ports.errors import (
    ProviderError,
    RateLimitedError,
    SymbolNotFoundError,
    UnsupportedRequestError,
)

__all__ = [
    "INSTRUMENT_NOT_FOUND",
    "NAME",
    "OK",
    "PERPETUAL",
    "RATE_LIMITED",
    "known_error",
    "swap_id",
    "swap_instrument",
]

NAME: Final = "okx"

PERPETUAL: Final = r"[A-Z0-9]{2,15}/[A-Z0-9]{2,10}:[A-Z0-9]{2,10}"
"""A perpetual swap: ``BASE/QUOTE:SETTLE`` (``BTC/USDT:USDT``)."""

OK: Final = "0"
INSTRUMENT_NOT_FOUND: Final = "51001"
RATE_LIMITED: Final = "50011"

_PERPETUAL = re.compile(PERPETUAL)
_INVERSE_QUOTE: Final = "USD"
"""OKX settles its swaps quoted in US dollars in the base asset (inverse swaps)."""


def swap_id(symbol: str) -> str:
    """OKX's identifier of the perpetual swap ``symbol`` (``BTC/USDT:USDT`` → ``BTC-USDT-SWAP``).

    Raises:
        UnsupportedRequestError: If the symbol is not a perpetual swap or OKX does not settle
            that pair in that currency.
    """
    if not _PERPETUAL.fullmatch(symbol):
        raise UnsupportedRequestError(
            NAME,
            f"{symbol!r} is not a perpetual swap written BASE/QUOTE:SETTLE in capitals "
            "(e.g. BTC/USDT:USDT)",
        )
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    expected = base if quote == _INVERSE_QUOTE else quote
    if settle != expected:
        raise UnsupportedRequestError(
            NAME, f"{symbol}: OKX settles its {base}/{quote} swap in {expected}, not {settle}"
        )
    return f"{base}-{quote}-SWAP"


def known_error(code: str, message: str, where: str) -> ProviderError | None:
    """The error an OKX error code means, if it is a known one."""
    if code == INSTRUMENT_NOT_FOUND:
        return SymbolNotFoundError(NAME, f"{where}: {message}")
    if code == RATE_LIMITED:
        return RateLimitedError(NAME, f"{where}: {message}")
    return None


def swap_instrument(symbol: str) -> Instrument:
    """The instrument of an OKX perpetual swap, priced in its quote asset."""
    swap = swap_id(symbol)
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    try:
        currency = Currency(quote)
    except DomainError as error:
        raise UnsupportedRequestError(
            NAME, f"{symbol}: prices quoted in {quote} cannot be represented ({error})"
        ) from error
    return Instrument(
        symbol=symbol,
        name=f"{base}/{quote} perpetual swap settled in {settle} (OKX {swap})",
        asset_class=AssetClass.CRYPTO,
        currency=currency,
        exchange=EXCHANGES["CRYPTO"],
    )
