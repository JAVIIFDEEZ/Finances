"""Property-based tests of drawdown episodes, number formatting and report robustness."""

from __future__ import annotations

import re

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from investinglab.analytics import drawdown_episodes, max_drawdown
from investinglab.reporting.i18n import Translator
from support.strategies import positive_prices, price_series

ES = Translator("es")
EN = Translator("en")


@given(prices=positive_prices)
def test_drawdown_episodes_are_consistent(prices: list[float]) -> None:
    series = pd.Series(prices, index=pd.bdate_range("2020-01-01", periods=len(prices)))

    episodes = drawdown_episodes(series)

    if episodes.empty:
        assert max_drawdown(series) == 0.0
        return
    assert episodes["depth"].iloc[0] == pytest.approx(max_drawdown(series))
    assert episodes["depth"].is_monotonic_increasing
    assert ((episodes["depth"] < 0) & (episodes["depth"] >= -1)).all()
    assert (episodes["peak"] < episodes["trough"]).all()
    recovered = episodes["recovery"].notna()
    assert (episodes.loc[recovered, "recovery"] > episodes.loc[recovered, "trough"]).all()
    assert (~recovered).sum() <= 1  # only the last episode can still be open
    assert (episodes["duration_periods"] >= episodes["decline_periods"]).all()


def _parse(text: str, translator: Translator) -> float:
    thousands, decimal = (".", ",") if translator is ES else (",", ".")
    return float(text.replace(thousands, "").replace(decimal, "."))


@given(
    value=st.floats(min_value=-1e12, max_value=1e12, allow_nan=False),
    decimals=st.integers(0, 4),
)
def test_formatted_numbers_parse_back(value: float, decimals: int) -> None:
    for translator in (ES, EN):
        text = translator.number(value, decimals)
        assert _parse(text, translator) == pytest.approx(round(value, decimals), abs=10**-decimals)


@settings(max_examples=25, deadline=None)
@given(series=price_series(), language=st.sampled_from(["es", "en"]))
def test_a_report_can_always_be_written(series: object, language: str) -> None:
    report = series.report(language=language)  # type: ignore[attr-defined]

    assert report.startswith("# ")
    assert report.count("\n## ") == 7
    assert not re.search(r"\bnan\b", report, flags=re.IGNORECASE)
    assert not re.search(
        r"\b1 (?:activos|observaciones|retornos|periodos|assets|periods)\b", report
    )
