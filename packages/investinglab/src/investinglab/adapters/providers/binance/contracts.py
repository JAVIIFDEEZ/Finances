"""Binance's perpetual swaps: which futures market and contract a symbol names (ADR-0041).

``BTC/USDT:USDT`` and ``ETH/USDC:USDC`` are linear swaps of USDⓈ-M futures (``BTCUSDT``,
``ETHUSDC``); ``BTC/USD:BTC`` is the inverse swap of COIN-M futures (``BTCUSD_PERP``). The
funding and the positioning of a swap are read from the dumps of that market.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from investinglab.domain.errors import DomainError
from investinglab.domain.instruments import EXCHANGES, AssetClass, Instrument
from investinglab.domain.money import Currency
from investinglab.ports.errors import UnsupportedRequestError

__all__ = ["PERPETUAL", "Market", "contract", "swap_instrument"]

type Market = Literal["um", "cm"]
"""USDⓈ-M (linear) or COIN-M (inverse) futures."""

PERPETUAL: Final = r"[A-Z0-9]{2,15}/[A-Z0-9]{2,10}:[A-Z0-9]{2,10}"
"""A perpetual swap: ``BASE/QUOTE:SETTLE`` (``BTC/USDT:USDT``)."""

_PERPETUAL = re.compile(PERPETUAL)
_LINEAR_SETTLEMENTS: Final = frozenset({"USDT", "USDC"})
_INVERSE_QUOTE: Final = "USD"


def contract(provider: str, symbol: str) -> tuple[Market, str]:
    """The futures market and contract of a perpetual swap.

    Raises:
        UnsupportedRequestError: If the symbol is not a perpetual swap Binance could list.
    """
    if not _PERPETUAL.fullmatch(symbol):
        raise UnsupportedRequestError(
            provider,
            f"{symbol!r} is not a perpetual swap written BASE/QUOTE:SETTLE in capitals "
            "(e.g. BTC/USDT:USDT)",
        )
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    if quote in _LINEAR_SETTLEMENTS and settle == quote:
        return "um", f"{base}{quote}"
    if quote == _INVERSE_QUOTE and settle == base:
        return "cm", f"{base}{quote}_PERP"
    raise UnsupportedRequestError(
        provider,
        f"{symbol}: Binance's perpetual swaps settle in the quote asset (USDT or USDC) or, "
        f"quoted in USD, in the base asset; not {base}/{quote} in {settle}",
    )


def swap_instrument(provider: str, symbol: str) -> Instrument:
    """The instrument of a Binance perpetual swap, priced in its quote asset.

    Raises:
        UnsupportedRequestError: If the symbol is not a swap Binance could list, or its
            quote asset is not a currency the domain knows.
    """
    _, name = contract(provider, symbol)
    pair, settle = symbol.split(":")
    base, quote = pair.split("/")
    try:
        currency = Currency(quote)
    except DomainError as error:
        raise UnsupportedRequestError(
            provider, f"{symbol}: prices quoted in {quote} cannot be represented ({error})"
        ) from error
    return Instrument(
        symbol=symbol,
        name=f"{base}/{quote} perpetual swap settled in {settle} (Binance {name})",
        asset_class=AssetClass.CRYPTO,
        currency=currency,
        exchange=EXCHANGES["CRYPTO"],
    )
