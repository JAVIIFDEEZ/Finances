from __future__ import annotations

import math

import pandas as pd
import pytest

from investinglab.domain import DomainError, Frequency
from investinglab.reporting.i18n import Language
from investinglab.reporting.options import ReportOptions
from support.factories import gbm_prices, make_series


def test_defaults() -> None:
    options = ReportOptions()

    assert options.language is Language.ES
    assert options.confidence_levels == (0.95, 0.99)
    assert options.top_drawdowns == 5
    assert options.uses_constant_zero_rate
    assert options.translator.language is Language.ES


def test_values_are_normalised() -> None:
    options = ReportOptions(language="en", confidence_levels=[0.9], correlation_frequency="1w")

    assert options.language is Language.EN
    assert options.confidence_levels == (0.9,)
    assert options.correlation_frequency is Frequency.WEEK_1


def test_every_invalid_option_is_reported_at_once() -> None:
    with pytest.raises(DomainError) as caught:
        ReportOptions(
            language="fr",
            title=" ",
            risk_free_rate=3.0,
            confidence_levels=(0.95, 1.2),
            top_drawdowns=0,
            correlation_frequency="2d",
            rolling_window=2,
        )

    message = str(caught.value)
    for fragment in (
        "language",
        "title",
        "annual decimal",
        "confidence_levels",
        "top_drawdowns",
        "correlation_frequency",
        "rolling_window",
    ):
        assert fragment in message


def test_risk_free_series_need_dates_and_decimal_values() -> None:
    dates = pd.bdate_range("2024-01-01", periods=3)

    ReportOptions(risk_free_rate=pd.Series([0.03, math.nan, 0.031], index=dates))
    with pytest.raises(DomainError, match="DatetimeIndex"):
        ReportOptions(risk_free_rate=pd.Series([0.03, 0.03]))
    with pytest.raises(DomainError, match="annual decimal"):
        ReportOptions(risk_free_rate=pd.Series([3.0, 3.1, 3.2], index=dates))
    with pytest.raises(DomainError, match="finite"):
        ReportOptions(risk_free_rate=math.inf)


def test_quality_must_be_reports() -> None:
    with pytest.raises(DomainError, match="quality"):
        ReportOptions(quality="not a report")  # type: ignore[arg-type]


def test_resolve_applies_keyword_settings_over_options() -> None:
    base = ReportOptions(language="en", top_drawdowns=3)

    resolved = ReportOptions.resolve(base, {"top_drawdowns": 7})

    assert resolved.language is Language.EN
    assert resolved.top_drawdowns == 7
    assert ReportOptions.resolve(base, {}) is base
    assert ReportOptions.resolve(None, {}).language is Language.ES


def test_zero_rate_detection() -> None:
    assert not ReportOptions(risk_free_rate=0.02).uses_constant_zero_rate
    dates = pd.bdate_range("2024-01-01", periods=2)
    assert not ReportOptions(
        risk_free_rate=pd.Series([0.0, 0.0], index=dates)
    ).uses_constant_zero_rate


def test_quality_lookup_by_symbol() -> None:
    first = make_series(gbm_prices(30), symbol="A").quality()
    second = make_series(gbm_prices(30, seed=2), symbol="B").quality()

    single = ReportOptions(quality=first)
    mapping = ReportOptions(quality={"B": second})

    assert single.quality_for("A") is first
    assert single.quality_for("B") is None
    assert mapping.quality_for("B") is second
    assert mapping.quality_for("A") is None
    assert ReportOptions().quality_for("A") is None
