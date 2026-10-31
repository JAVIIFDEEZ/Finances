from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from investinglab.analytics import annualize_mean, annualize_volatility, cagr, describe_returns


def test_describe_returns_matches_numpy_and_ignores_nan() -> None:
    values = np.array([0.01, -0.02, 0.03, np.nan, 0.005, -0.01])
    clean = values[~np.isnan(values)]

    moments = describe_returns(values)

    assert moments.count == 5
    assert moments.mean == pytest.approx(clean.mean())
    assert moments.std == pytest.approx(clean.std(ddof=1))
    assert moments.minimum == pytest.approx(-0.02)
    assert moments.maximum == pytest.approx(0.03)
    assert moments.skewness == pytest.approx(stats.skew(clean, bias=False))
    assert moments.excess_kurtosis == pytest.approx(stats.kurtosis(clean, bias=False))


@pytest.mark.parametrize(
    ("values", "finite_std", "finite_skew", "finite_kurt"),
    [
        ([], False, False, False),
        ([0.01], False, False, False),
        ([0.01, 0.02], True, False, False),
        ([0.01, 0.02, -0.01], True, True, False),
        ([0.01, 0.02, -0.01, 0.0], True, True, True),
    ],
)
def test_moments_are_nan_when_undefined(
    values: list[float], finite_std: bool, finite_skew: bool, finite_kurt: bool
) -> None:
    moments = describe_returns(np.array(values))

    assert math.isfinite(moments.std) is finite_std
    assert math.isfinite(moments.skewness) is finite_skew
    assert math.isfinite(moments.excess_kurtosis) is finite_kurt


def test_constant_returns_have_no_shape_statistics() -> None:
    moments = describe_returns(np.array([0.01] * 10))

    assert moments.std == 0.0
    assert math.isnan(moments.skewness)
    assert math.isnan(moments.excess_kurtosis)


def test_annualisation_helpers() -> None:
    assert annualize_mean(0.001, 252) == pytest.approx(0.252)
    assert annualize_volatility(0.01, 252) == pytest.approx(0.01 * math.sqrt(252))


def test_cagr() -> None:
    # +21 % over two years is +10 % a year.
    assert cagr(0.21, periods=504, periods_per_year=252) == pytest.approx(0.10)


@pytest.mark.parametrize(
    ("total", "periods", "per_year"), [(0.1, 0, 252), (-1.0, 10, 252), (-1.5, 10, 252), (0.1, 5, 0)]
)
def test_cagr_is_nan_when_undefined(total: float, periods: int, per_year: float) -> None:
    assert math.isnan(cagr(total, periods, per_year))
