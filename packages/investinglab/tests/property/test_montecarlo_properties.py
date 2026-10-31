"""Property-based tests of the Monte Carlo kernels and results (synthetic data only)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from investinglab.analytics import ledoit_wolf
from investinglab.analytics.montecarlo import (
    path_max_drawdowns,
    rebalanced_values,
    stationary_bootstrap_indices,
)
from investinglab.domain import SimulationConfig
from support.factories import business_days, gbm_prices, make_series


@st.composite
def returns_and_weights(draw: st.DrawFn) -> tuple[np.ndarray, np.ndarray]:
    """Simple returns ``(paths, horizon, assets)`` above -100 % and long-only weights."""
    n_paths = draw(st.integers(1, 6))
    horizon = draw(st.integers(1, 12))
    assets = draw(st.integers(1, 4))
    returns = draw(
        arrays(
            np.float64,
            (n_paths, horizon, assets),
            elements=st.floats(-0.9, 1.0, allow_nan=False, allow_infinity=False),
        )
    )
    raw = draw(arrays(np.float64, assets, elements=st.floats(0.01, 1.0, allow_nan=False)))
    return returns, raw / raw.sum()


rebalancing_rules = st.sampled_from(
    [{}, {"rebalance_every": 1}, {"rebalance_every": 3}, {"band": 0.05}]
)


@given(case=returns_and_weights(), rule=rebalancing_rules)
def test_long_only_values_stay_positive(
    case: tuple[np.ndarray, np.ndarray], rule: dict[str, float]
) -> None:
    returns, weights = case

    values = rebalanced_values(returns, weights, initial_value=100.0, **rule)  # type: ignore[arg-type]

    assert values.shape == (returns.shape[0], returns.shape[1] + 1)
    assert (values > 0).all()
    assert (values[:, 0] == 100.0).all()


@given(case=returns_and_weights())
def test_buy_and_hold_is_the_weighted_growth_of_each_asset(
    case: tuple[np.ndarray, np.ndarray],
) -> None:
    returns, weights = case

    values = rebalanced_values(returns, weights)

    growth = np.prod(1.0 + returns, axis=1)
    assert values[:, -1] == pytest.approx(growth @ weights, rel=1e-9)


@given(case=returns_and_weights())
def test_constant_mix_compounds_the_weighted_return(case: tuple[np.ndarray, np.ndarray]) -> None:
    returns, weights = case

    values = rebalanced_values(returns, weights, rebalance_every=1)

    expected = np.prod(1.0 + returns @ weights, axis=1)
    assert values[:, -1] == pytest.approx(expected, rel=1e-9)


@given(case=returns_and_weights(), rule=rebalancing_rules)
def test_flat_markets_keep_any_portfolio_flat(
    case: tuple[np.ndarray, np.ndarray], rule: dict[str, float]
) -> None:
    returns, weights = case

    values = rebalanced_values(np.zeros_like(returns), weights, initial_value=7.0, **rule)  # type: ignore[arg-type]

    assert np.allclose(values, 7.0)


@given(
    values=arrays(
        np.float64,
        st.tuples(st.integers(1, 5), st.integers(1, 30)),
        elements=st.floats(0.0, 1e6, allow_nan=False),
    ).map(lambda v: np.concatenate([np.ones((v.shape[0], 1)), v], axis=1)),
)
def test_max_drawdowns_are_between_minus_one_and_zero(values: np.ndarray) -> None:
    drawdowns = path_max_drawdowns(values)

    assert ((drawdowns >= -1.0) & (drawdowns <= 0.0)).all()


@given(
    n_observations=st.integers(1, 50),
    horizon=st.integers(1, 40),
    mean_block=st.floats(1.0, 100.0),
    seed=st.integers(0, 2**32 - 1),
)
def test_bootstrap_indices_are_valid_rows(
    n_observations: int, horizon: int, mean_block: float, seed: int
) -> None:
    indices = stationary_bootstrap_indices(
        n_observations,
        horizon=horizon,
        n_paths=3,
        mean_block=mean_block,
        rng=np.random.default_rng(seed),
    )

    assert indices.shape == (3, horizon)
    assert ((indices >= 0) & (indices < n_observations)).all()


@given(
    observations=arrays(
        np.float64,
        st.tuples(st.integers(2, 40), st.integers(1, 6)),
        elements=st.floats(-0.2, 0.2, allow_nan=False),
    )
)
def test_ledoit_wolf_is_psd_and_keeps_the_trace(observations: np.ndarray) -> None:
    shrunk, shrinkage = ledoit_wolf(observations)

    centred = observations - observations.mean(axis=0)
    sample = centred.T @ centred / len(observations)
    assert 0.0 <= shrinkage <= 1.0
    assert np.trace(shrunk) == pytest.approx(np.trace(sample), rel=1e-9, abs=1e-15)
    assert np.linalg.eigvalsh(shrunk).min() >= -1e-12


SERIES = make_series(gbm_prices(120, seed=5), symbol="A", index=business_days(120))


@settings(max_examples=20, deadline=None)
@given(
    initial_value=st.floats(1.0, 1e7),
    seed=st.integers(0, 10_000),
    level=st.floats(0.80, 0.995),
)
def test_risk_fractions_do_not_depend_on_the_amount_invested(
    initial_value: float, seed: int, level: float
) -> None:
    reference = SERIES.monte_carlo(SimulationConfig(n_paths=200, horizon=10, seed=seed))
    scaled = SERIES.monte_carlo(
        SimulationConfig(n_paths=200, horizon=10, seed=seed, initial_value=initial_value)
    )

    assert scaled.value_at_risk(level).value == pytest.approx(
        reference.value_at_risk(level).value, abs=1e-9
    )
    assert scaled.conditional_value_at_risk(level).value >= scaled.value_at_risk(level).value
    assert scaled.terminal_values == pytest.approx(
        reference.terminal_values * initial_value / 10_000.0, rel=1e-9
    )
