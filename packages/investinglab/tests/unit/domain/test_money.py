from __future__ import annotations

import dataclasses

import pytest

from investinglab.domain import (
    EUR,
    GBP,
    USD,
    Currency,
    CurrencyKind,
    CurrencyPair,
    DomainError,
    QuoteUnit,
    UnknownCurrencyError,
    parse_quote_currency,
)


@pytest.mark.parametrize(
    ("code", "kind"),
    [("EUR", CurrencyKind.FIAT), ("XAU", CurrencyKind.METAL), ("USDT", CurrencyKind.DIGITAL)],
)
def test_known_codes_are_accepted(code: str, kind: CurrencyKind) -> None:
    currency = Currency(code)

    assert currency.kind is kind
    assert str(currency) == code


@pytest.mark.parametrize("code", ["eur", "GBp", "XXX", "EURO", ""])
def test_unknown_or_badly_cased_codes_are_rejected(code: str) -> None:
    with pytest.raises(UnknownCurrencyError):
        Currency(code)


def test_currencies_are_immutable_and_comparable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        EUR.code = "USD"  # type: ignore[misc]
    assert Currency("EUR") == EUR
    assert sorted([USD, EUR]) == [EUR, USD]


@pytest.mark.parametrize(
    ("raw", "currency", "scale"),
    [
        ("GBp", GBP, 0.01),
        ("GBX", GBP, 0.01),
        ("ZAc", Currency("ZAR"), 0.01),
        ("ILA", Currency("ILS"), 0.01),
        ("KWF", Currency("KWD"), 0.001),
        ("usd", USD, 1.0),
        (" EUR ", EUR, 1.0),
    ],
)
def test_quote_currency_resolves_minor_units(raw: str, currency: Currency, scale: float) -> None:
    assert parse_quote_currency(raw) == QuoteUnit(currency, scale)


def test_quote_unit_scale_must_be_positive() -> None:
    with pytest.raises(DomainError):
        QuoteUnit(EUR, 0.0)


def test_currency_pair() -> None:
    pair = CurrencyPair(EUR, USD)

    assert pair.symbol == "EURUSD"
    assert str(pair) == "EURUSD"
    assert pair.inverse() == CurrencyPair(USD, EUR)


@pytest.mark.parametrize("text", ["EURUSD", "eur/usd", "EUR-USD"])
def test_currency_pair_parsing(text: str) -> None:
    assert CurrencyPair.parse(text) == CurrencyPair(EUR, USD)


@pytest.mark.parametrize("text", ["EURUS", "EUR/EUR"])
def test_invalid_currency_pairs(text: str) -> None:
    with pytest.raises(DomainError):
        CurrencyPair.parse(text)
