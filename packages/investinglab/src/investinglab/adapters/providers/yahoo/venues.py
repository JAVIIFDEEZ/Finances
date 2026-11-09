"""Translation of Yahoo's venue codes and instrument types to the domain's vocabulary.

Yahoo identifies venues with its own short codes (``MCE`` for Madrid, ``NMS`` for the Nasdaq
Global Select Market...). They are mapped onto the ISO 10383 MICs of
:data:`~investinglab.domain.instruments.EXCHANGES`; a venue missing from the table is left
unknown (the instrument then uses its asset class's default schedule) rather than guessed.
"""

from __future__ import annotations

from types import MappingProxyType

from investinglab.domain.instruments import EXCHANGES, AssetClass, Exchange

__all__ = ["ASSET_CLASSES", "VENUES", "asset_class_of", "exchange_of"]

VENUES: MappingProxyType[str, str] = MappingProxyType(
    {
        # United States and Canada
        "NMS": "XNAS",  # Nasdaq Global Select Market
        "NGM": "XNAS",  # Nasdaq Global Market
        "NCM": "XNAS",  # Nasdaq Capital Market
        "NAS": "XNAS",
        "NIM": "XNAS",  # Nasdaq indices, computed over Nasdaq sessions
        "NYQ": "XNYS",
        "NYS": "XNYS",
        "SNP": "XNYS",  # S&P Dow Jones indices, computed over NYSE sessions
        "DJI": "XNYS",
        "PCX": "ARCX",  # NYSE Arca (most US-listed ETFs)
        "TOR": "XTSE",
        # Europe
        "MCE": "XMAD",
        "GER": "XETR",
        "PAR": "XPAR",
        "AMS": "XAMS",
        "BRU": "XBRU",
        "LIS": "XLIS",
        "MIL": "XMIL",
        "LSE": "XLON",
        "IOB": "XLON",  # London International Order Book
        "EBS": "XSWX",
        "VTX": "XSWX",
        "STO": "XSTO",
        # Asia-Pacific
        "JPX": "XTKS",
        "TYO": "XTKS",
        "HKG": "XHKG",
        "ASX": "XASX",
        # Markets without a MIC
        "CCY": "FX",
        "CCC": "CRYPTO",
    }
)
"""Yahoo venue code → code of a known :class:`~investinglab.domain.instruments.Exchange`."""

ASSET_CLASSES: MappingProxyType[str, AssetClass] = MappingProxyType(
    {
        "EQUITY": AssetClass.EQUITY,
        "ETF": AssetClass.ETF,
        "MUTUALFUND": AssetClass.FUND,
        "INDEX": AssetClass.INDEX,
        "CURRENCY": AssetClass.FX,
        "CRYPTOCURRENCY": AssetClass.CRYPTO,
        "FUTURE": AssetClass.FUTURE,
    }
)
"""Yahoo ``instrumentType`` → asset class."""


def exchange_of(venue: str | None) -> Exchange | None:
    """Known exchange behind a Yahoo venue code, or ``None`` when it is not mapped."""
    code = VENUES.get(venue or "")
    return None if code is None else EXCHANGES[code]


def asset_class_of(instrument_type: str | None) -> AssetClass | None:
    """Asset class of a Yahoo instrument type, or ``None`` when it is not supported."""
    return ASSET_CLASSES.get((instrument_type or "").upper())
