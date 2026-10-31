from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from investinglab.domain import (
    CRYPTO_SCHEDULE,
    EQUITY_SCHEDULE,
    EUR,
    EXCHANGES,
    FX_SCHEDULE,
    USD,
    AssetClass,
    DomainError,
    Exchange,
    Identifiers,
    Instrument,
    InvalidIdentifierError,
)
from investinglab.domain.instruments import is_valid_isin, is_valid_lei


@pytest.mark.parametrize(
    "isin",
    [
        "US0378331005",  # Apple
        "ES0113900J37",  # Banco Santander
        "ES0148396007",  # Inditex
        "DE0007164600",  # SAP
    ],
)
def test_real_isins_pass_the_checksum(isin: str) -> None:
    assert is_valid_isin(isin)


@pytest.mark.parametrize("isin", ["US0378331006", "us0378331005", "US037833100", "1S0378331005"])
def test_invalid_isins(isin: str) -> None:
    assert not is_valid_isin(isin)


def test_lei_checksum() -> None:
    assert is_valid_lei("HWUPKR0MPOU8FGXBT394")  # Apple Inc.
    assert not is_valid_lei("HWUPKR0MPOU8FGXBT395")
    assert not is_valid_lei("SHORT")


def test_identifiers_are_validated_and_normalised() -> None:
    identifiers = Identifiers(
        isin="US0378331005", figi="BBG000B9XRY4", cik="320193", lei="HWUPKR0MPOU8FGXBT394"
    )

    assert identifiers.cik == "0000320193"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"isin": "US0378331006"},
        {"figi": "BBG000B9XRY"},
        {"figi": "GBG000B9XRY4"},  # forbidden prefix
        {"figi": "BAG000B9XRY4"},  # vowel
        {"cik": "12345678901"},
        {"cik": "ABC"},
        {"lei": "HWUPKR0MPOU8FGXBT395"},
    ],
)
def test_invalid_identifiers_are_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(InvalidIdentifierError):
        Identifiers(**kwargs)


def test_exchange_registry() -> None:
    madrid = EXCHANGES["XMAD"]

    assert madrid.timezone == "Europe/Madrid"
    assert madrid.tz == ZoneInfo("Europe/Madrid")
    assert EXCHANGES["CRYPTO"].schedule is CRYPTO_SCHEDULE


@pytest.mark.parametrize(
    ("code", "name", "timezone"),
    [("x", "Name", "UTC"), ("XNYS", " ", "UTC"), ("XNYS", "Name", "Mars/Olympus")],
)
def test_invalid_exchanges(code: str, name: str, timezone: str) -> None:
    with pytest.raises(DomainError):
        Exchange(code, name, timezone)


def test_instrument_defaults_and_derived_properties() -> None:
    santander = Instrument("SAN.MC", "Banco Santander", AssetClass.EQUITY, EUR, EXCHANGES["XMAD"])
    bitcoin = Instrument("BTC-USD", "Bitcoin", AssetClass.CRYPTO, USD)
    eurusd = Instrument("EURUSD=X", "EUR/USD", AssetClass.FX, USD)

    assert santander.timezone == "Europe/Madrid"
    assert santander.schedule.sessions_per_year == 252
    assert santander.identifiers == Identifiers()
    assert bitcoin.schedule is CRYPTO_SCHEDULE
    assert bitcoin.timezone == "UTC"
    assert eurusd.schedule is FX_SCHEDULE
    assert Instrument("^GSPC", "S&P 500", AssetClass.INDEX, USD).schedule is EQUITY_SCHEDULE


@pytest.mark.parametrize(("symbol", "name"), [("", "x"), ("BAD SYMBOL", "x"), ("OK", " ")])
def test_invalid_instruments(symbol: str, name: str) -> None:
    with pytest.raises(DomainError):
        Instrument(symbol, name, AssetClass.EQUITY, EUR)
