from __future__ import annotations

import math
import string
from datetime import UTC, datetime

import pandas as pd
import pytest

from investinglab.domain import Frequency
from investinglab.reporting.i18n import MISSING, Language, Translator, catalogue

ES = Translator("es")
EN = Translator(Language.EN)


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("key", sorted(catalogue()))
def test_both_languages_use_the_same_placeholders(key: str) -> None:
    spanish, english = catalogue()[key]

    assert spanish.strip()
    assert english.strip()
    assert _placeholders(spanish) == _placeholders(english)


def test_every_frequency_has_a_name() -> None:
    for frequency in Frequency:
        assert ES.frequency(frequency.value)
        assert EN.frequency(frequency.value)


def test_spanish_is_the_default_language() -> None:
    assert Translator().language is Language.ES
    assert Translator().text("section.data") == "Datos y procedencia"
    assert EN.text("section.data") == "Data and provenance"


def test_unknown_languages_and_keys_fail_loudly() -> None:
    with pytest.raises(ValueError, match="fr"):
        Translator("fr")
    with pytest.raises(KeyError):
        ES.text("does.not.exist")


@pytest.mark.parametrize(
    ("value", "decimals", "signed", "spanish", "english"),
    [
        (1234.567, 2, False, "1.234,57", "1,234.57"),
        (-1234567.891, 1, False, "-1.234.567,9", "-1,234,567.9"),
        (0.5, 0, False, "0", "0"),
        (-0.0004, 2, False, "0,00", "0.00"),
        (0.25, 2, True, "+0,25", "+0.25"),
        (-0.25, 2, True, "-0,25", "-0.25"),
        (0.0, 2, True, "0,00", "0.00"),
    ],
)
def test_numbers_follow_each_language(
    value: float, decimals: int, signed: bool, spanish: str, english: str
) -> None:
    assert ES.number(value, decimals, signed=signed) == spanish
    assert EN.number(value, decimals, signed=signed) == english


def test_percentages_follow_each_language() -> None:
    assert ES.percent(0.1234) == "12,3\u00a0%"
    assert EN.percent(0.1234) == "12.3%"
    assert ES.percent(-0.05, 2, signed=True) == "-5,00\u00a0%"
    assert EN.percent(0.05, 0, signed=True) == "+5%"


@pytest.mark.parametrize("value", [None, math.nan])
def test_missing_values_are_an_em_dash(value: float | None) -> None:
    assert ES.number(value) == MISSING
    assert EN.percent(value) == MISSING
    assert ES.integer(value) == MISSING


def test_infinities_are_symbols() -> None:
    assert EN.number(math.inf) == "∞"
    assert ES.percent(-math.inf) == "-∞\u00a0%"


def test_integers_are_grouped() -> None:
    assert ES.integer(12_345) == "12.345"
    assert EN.integer(12_345) == "12,345"


def test_dates_are_iso_8601() -> None:
    assert ES.date(pd.Timestamp("2024-03-15")) == "2024-03-15"
    assert ES.date(pd.Timestamp("2024-03-15 09:30")) == "2024-03-15 09:30"
    assert EN.date(datetime(2024, 3, 15, 14, 5, tzinfo=UTC)) == "2024-03-15 14:05 UTC"
    madrid = pd.Timestamp("2024-03-15 10:00", tz="Europe/Madrid")
    assert EN.date(madrid) == "2024-03-15 09:00 UTC"
    assert ES.date(None) == MISSING
    assert ES.date(pd.Timestamp("NaT")) == MISSING
