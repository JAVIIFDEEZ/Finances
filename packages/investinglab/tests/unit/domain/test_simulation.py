from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from investinglab.domain import (
    CovarianceEstimator,
    DomainError,
    DriftAssumption,
    Frequency,
    Portfolio,
    PriceSeries,
    RebalancePolicy,
    SimulationConfig,
    SimulationModel,
    VolatilityAssumption,
)
from investinglab.domain.simulation import (
    SimulationInputs,
    _bootstrap_rows,
    calibrate,
    simulate,
)
from support.factories import business_days, gbm_prices, make_series

N = 504
INDEX = business_days(N)


def _asset(symbol: str = "A", *, seed: int = 1, sigma: float = 0.2) -> PriceSeries:
    return make_series(gbm_prices(N, seed=seed, sigma=sigma), symbol=symbol, index=INDEX)


def _portfolio(policy: RebalancePolicy | None = None) -> Portfolio:
    assets = [_asset("A", seed=1, sigma=0.15), _asset("B", seed=2, sigma=0.30)]
    return Portfolio.from_weights("Synthetic", assets, [0.6, 0.4], rebalance=policy)


def _inputs(prices: pd.DataFrame, weights: tuple[float, ...] = (1.0,)) -> SimulationInputs:
    return SimulationInputs(
        prices=prices,
        weights=np.array(weights),
        periods_per_year=252.0,
        rebalance_every=None,
        band=None,
        start=pd.Timestamp(prices.index[-1]),
    )


def _log_history(prices: pd.DataFrame) -> pd.DataFrame:
    ratios = (prices / prices.shift(1)).dropna()
    return pd.DataFrame(np.log(ratios.to_numpy()), index=ratios.index, columns=ratios.columns)


ASSUMED_GBM = SimulationConfig(
    n_paths=20_000,
    horizon=252,
    drift=DriftAssumption.ASSUMED,
    expected_returns=0.08,
    volatility=VolatilityAssumption.ASSUMED,
    volatilities=0.2,
)


# ── Configuration ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"n_paths": 10}, "n_paths must be between"),
        ({"horizon": 0}, "horizon must be at least"),
        ({"n_paths": 1_000_000, "horizon": 100}, "must not exceed"),
        ({"drift": DriftAssumption.ASSUMED}, "needs expected_returns"),
        ({"volatility": VolatilityAssumption.ASSUMED}, "needs volatilities"),
        ({"degrees_of_freedom": 2.0}, "greater than 2"),
        ({"block_length": 0.5}, "block_length"),
        ({"lookback": 1}, "lookback"),
        ({"model": SimulationModel.BOOTSTRAP, "antithetic": True}, "parametric models"),
        ({"initial_value": 0.0}, "initial_value"),
        ({"confidence_levels": (0.95, 1.0)}, "confidence_levels"),
        ({"confidence_levels": ()}, "confidence_levels"),
        ({"chunk_size": 10}, "chunk_size"),
    ],
)
def test_invalid_configuration_is_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(DomainError, match=message):
        SimulationConfig(**changes)  # type: ignore[arg-type]


def test_every_configuration_problem_is_reported_at_once() -> None:
    with pytest.raises(DomainError) as caught:
        SimulationConfig(n_paths=1, horizon=0, initial_value=-1.0)

    assert "n_paths" in str(caught.value)
    assert "horizon" in str(caught.value)
    assert "initial_value" in str(caught.value)


# ── Calibration ──────────────────────────────────────────────────────


def test_historical_calibration_uses_per_period_log_returns() -> None:
    portfolio = _portfolio()

    result = portfolio.monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    calibration = result.calibration
    history = _log_history(portfolio.aligned().prices)
    assert calibration.symbols == ("A", "B")
    assert calibration.weights.tolist() == [0.6, 0.4]
    assert np.allclose(calibration.mean_log_return, history.mean())
    assert np.allclose(calibration.covariance, history.cov())
    assert calibration.observations == N - 1
    assert calibration.shrinkage is None
    assert calibration.periods_per_year == 252.0


def test_calibration_reports_annual_figures() -> None:
    result = _asset().monte_carlo(ASSUMED_GBM)

    assert result.calibration.annual_volatility["A"] == pytest.approx(0.2)
    assert result.calibration.annual_expected_return["A"] == pytest.approx(0.08)


def test_assumed_volatilities_keep_historical_correlations() -> None:
    portfolio = _portfolio()
    config = SimulationConfig(
        n_paths=100,
        horizon=5,
        volatility=VolatilityAssumption.ASSUMED,
        volatilities={"A": 0.10, "B": 0.25},
    )

    historical = portfolio.monte_carlo(SimulationConfig(n_paths=100, horizon=5)).calibration
    assumed = portfolio.monte_carlo(config).calibration

    assert assumed.annual_volatility.tolist() == pytest.approx([0.10, 0.25])
    assert np.allclose(assumed.correlation, historical.correlation)


def test_assumed_volatility_applies_to_assets_that_never_moved() -> None:
    prices = pd.DataFrame({"FLAT": np.full(30, 100.0)}, index=business_days(30))
    config = SimulationConfig(
        n_paths=100,
        horizon=5,
        drift=DriftAssumption.ZERO,
        volatility=VolatilityAssumption.ASSUMED,
        volatilities=0.1,
    )

    calibration, _ = calibrate(_inputs(prices), config)

    assert calibration.annual_volatility["FLAT"] == pytest.approx(0.1)


def test_per_asset_assumptions_must_name_every_asset() -> None:
    config = SimulationConfig(
        n_paths=100, horizon=5, drift=DriftAssumption.ASSUMED, expected_returns={"A": 0.05}
    )

    with pytest.raises(DomainError, match=r"expected_returns missing for \['B'\]"):
        _portfolio().monte_carlo(config)


def test_zero_drift_makes_prices_martingales() -> None:
    result = _asset().monte_carlo(
        SimulationConfig(n_paths=20_000, horizon=252, drift=DriftAssumption.ZERO)
    )

    estimate = result.expected_value_estimate()
    assert abs(estimate.value - 10_000.0) < 4 * estimate.standard_error
    assert result.calibration.annual_expected_return["A"] == pytest.approx(0.0, abs=1e-12)


def test_risk_free_drift_grows_every_asset_at_the_rate() -> None:
    config = SimulationConfig(
        n_paths=100, horizon=5, drift=DriftAssumption.RISK_FREE, risk_free_rate=0.03
    )

    calibration = _portfolio().monte_carlo(config).calibration

    assert calibration.annual_expected_return.tolist() == pytest.approx([0.03, 0.03])


def test_ledoit_wolf_calibration_reports_its_shrinkage() -> None:
    config = SimulationConfig(n_paths=100, horizon=5, covariance=CovarianceEstimator.LEDOIT_WOLF)

    calibration = _portfolio().monte_carlo(config).calibration

    assert calibration.shrinkage is not None
    assert 0.0 <= calibration.shrinkage <= 1.0
    assert np.trace(calibration.covariance) == pytest.approx(
        np.trace(_log_history(_portfolio().aligned().prices).cov()), rel=0.01
    )


def test_lookback_limits_the_calibration_window() -> None:
    result = _asset().monte_carlo(SimulationConfig(n_paths=100, horizon=5, lookback=60))

    assert result.calibration.observations == 60


def test_simulation_needs_two_complete_periods() -> None:
    prices = pd.DataFrame({"A": [100.0, 101.0]}, index=business_days(2))

    with pytest.raises(DomainError, match="two complete historical periods"):
        simulate(_inputs(prices), SimulationConfig(n_paths=100, horizon=5))


def test_correlation_of_a_constant_asset_is_left_undefined_off_the_diagonal() -> None:
    prices = pd.DataFrame(
        {"FLAT": np.full(30, 100.0), "A": gbm_prices(30)}, index=business_days(30)
    )

    calibration, _ = calibrate(_inputs(prices, (0.5, 0.5)), SimulationConfig(n_paths=100))

    correlation = calibration.correlation
    assert np.diag(correlation).tolist() == [1.0, 1.0]
    assert math.isnan(correlation["A"]["FLAT"])


# ── Simulation ───────────────────────────────────────────────────────


def test_same_seed_and_configuration_give_the_same_paths() -> None:
    config = SimulationConfig(n_paths=500, horizon=20, seed=11)

    first = _portfolio().monte_carlo(config)
    second = _portfolio().monte_carlo(config)
    other = _portfolio().monte_carlo(SimulationConfig(n_paths=500, horizon=20, seed=12))

    assert np.array_equal(first.values(), second.values())
    assert not np.array_equal(first.values(), other.values())


def test_chunking_does_not_change_gaussian_paths() -> None:
    whole = _asset().monte_carlo(SimulationConfig(n_paths=1_000, horizon=10, chunk_size=1_000))
    chunked = _asset().monte_carlo(SimulationConfig(n_paths=1_000, horizon=10, chunk_size=300))

    assert np.allclose(whole.values(), chunked.values())


def test_paths_without_volatility_or_drift_stay_flat() -> None:
    config = SimulationConfig(
        n_paths=100,
        horizon=30,
        drift=DriftAssumption.ZERO,
        volatility=VolatilityAssumption.ASSUMED,
        volatilities=0.0,
    )

    result = _portfolio().monte_carlo(config)

    assert np.allclose(result.values(), 10_000.0)
    assert result.probability_of_loss == 0.0
    assert result.max_drawdowns.tolist() == pytest.approx([0.0] * 100)


def test_gbm_terminal_log_returns_match_theory() -> None:
    result = _asset().monte_carlo(ASSUMED_GBM)

    log_terminal = np.log(result.terminal_values / 10_000.0)
    sigma = 0.2
    mu = math.log(1.08) - sigma**2 / 2
    assert log_terminal.mean() == pytest.approx(mu, abs=4 * sigma / math.sqrt(20_000))
    assert log_terminal.std() == pytest.approx(sigma, rel=0.02)
    estimate = result.expected_value_estimate()
    assert abs(estimate.value - 10_800.0) < 4 * estimate.standard_error


def test_value_at_risk_interval_covers_the_theoretical_quantile() -> None:
    result = _asset().monte_carlo(ASSUMED_GBM)
    sigma = 0.2
    mu = math.log(1.08) - sigma**2 / 2
    quantile = mu + sigma * NormalDist().inv_cdf(0.05)
    true_var = -math.expm1(quantile)

    var = result.value_at_risk(0.95)

    assert var.lower <= true_var <= var.upper
    assert var.lower <= var.value <= var.upper
    assert var.standard_error > 0


def test_expected_shortfall_matches_the_lognormal_formula() -> None:
    result = _asset().monte_carlo(ASSUMED_GBM)
    sigma = 0.2
    mu = math.log(1.08) - sigma**2 / 2
    normal = NormalDist()
    quantile = mu + sigma * normal.inv_cdf(0.05)
    tail_mean = math.exp(mu + sigma**2 / 2) * normal.cdf((quantile - mu - sigma**2) / sigma)
    true_cvar = 1.0 - tail_mean / 0.05

    cvar = result.conditional_value_at_risk(0.95)

    assert abs(cvar.value - true_cvar) < 4 * cvar.standard_error
    assert cvar.value >= result.value_at_risk(0.95).value


def test_student_t_has_fatter_tails_than_gbm() -> None:
    base = {"n_paths": 100_000, "horizon": 1, "drift": DriftAssumption.ZERO}

    gaussian = _asset().monte_carlo(SimulationConfig(**base))  # type: ignore[arg-type]
    fat = _asset().monte_carlo(
        SimulationConfig(**base, model=SimulationModel.STUDENT_T, degrees_of_freedom=4.5)  # type: ignore[arg-type]
    )

    assert fat.value_at_risk(0.999).value > 1.2 * gaussian.value_at_risk(0.999).value
    assert np.std(fat.terminal_returns) == pytest.approx(
        np.std(gaussian.terminal_returns), rel=0.05
    )


def test_antithetic_paths_mirror_each_other() -> None:
    config = SimulationConfig(n_paths=1_000, horizon=1, drift=DriftAssumption.ZERO, antithetic=True)

    result = _asset().monte_carlo(config)

    shocks = np.log(result.terminal_values / 10_000.0) - result.calibration.mean_log_return[0]
    assert np.allclose(shocks[:500], -shocks[500:])


def test_bootstrap_only_replays_rescaled_historical_periods() -> None:
    config = SimulationConfig(n_paths=1_000, horizon=1, model=SimulationModel.BOOTSTRAP)
    series = _asset()

    result = series.monte_carlo(config)
    calibration, complete = calibrate(_inputs(series.prices.to_frame()), config)
    rows = _bootstrap_rows(complete, calibration)

    simulated = np.log(result.terminal_values / 10_000.0)
    assert np.isin(np.round(simulated, 12), np.round(rows[:, 0], 12)).all()


def test_bootstrap_rows_are_recentred_and_rescaled_to_the_calibration() -> None:
    config = SimulationConfig(
        n_paths=100,
        horizon=5,
        model=SimulationModel.BOOTSTRAP,
        drift=DriftAssumption.ASSUMED,
        expected_returns={"A": 0.05, "B": 0.10},
        volatility=VolatilityAssumption.ASSUMED,
        volatilities={"A": 0.10, "B": 0.40},
    )
    prices = _portfolio().aligned().prices

    calibration, complete = calibrate(_inputs(prices, (0.6, 0.4)), config)
    rows = _bootstrap_rows(complete, calibration)

    assert np.allclose(rows.mean(axis=0), calibration.mean_log_return)
    assert np.allclose(rows.std(axis=0, ddof=1), np.sqrt(np.diag(calibration.covariance)))
    assert np.allclose(np.corrcoef(rows, rowvar=False), np.corrcoef(complete, rowvar=False))


def test_bootstrap_keeps_constant_assets_constant() -> None:
    prices = pd.DataFrame(
        {"FLAT": np.full(30, 100.0), "A": gbm_prices(30)}, index=business_days(30)
    )
    config = SimulationConfig(n_paths=100, horizon=5, model=SimulationModel.BOOTSTRAP)

    calibration, complete = calibrate(_inputs(prices, (0.5, 0.5)), config)

    assert np.allclose(_bootstrap_rows(complete, calibration)[:, 0], 0.0)


# ── Results ──────────────────────────────────────────────────────────


def test_result_accessors() -> None:
    result = _portfolio().monte_carlo(SimulationConfig(n_paths=1_000, horizon=21))

    assert result.n_paths == 1_000
    assert result.horizon == 21
    assert result.start == INDEX[-1]
    assert result.values().shape == (1_000, 22)
    assert (result.values()[:, 0] == 10_000.0).all()
    assert result.terminal_values.shape == (1_000,)
    assert result.terminal_returns == pytest.approx(result.terminal_values / 10_000.0 - 1.0)
    assert result.median_terminal_value == pytest.approx(np.median(result.terminal_values))
    assert 0.0 <= result.probability_of_loss <= 1.0
    assert (result.max_drawdowns <= 0.0).all()
    assert result.drawdown_at_risk(0.99) <= result.drawdown_at_risk(0.95) <= 0.0


def test_accessors_return_copies() -> None:
    result = _asset().monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    result.values()[:] = 0.0
    result.terminal_values[:] = 0.0
    result.max_drawdowns[:] = 0.0

    assert (result.values() > 0).all()
    assert (result.max_drawdowns <= 0).all()


def test_percentile_paths_form_a_fan() -> None:
    result = _asset().monte_carlo(SimulationConfig(n_paths=2_000, horizon=30))

    fan = result.percentile_paths((5, 50, 95))

    assert list(fan.columns) == ["p5", "p50", "p95"]
    assert fan.index.name == "period"
    assert len(fan) == 31
    assert (fan["p5"] <= fan["p50"]).all()
    assert (fan["p50"] <= fan["p95"]).all()
    assert fan.iloc[0].tolist() == [10_000.0] * 3


def test_sample_paths_are_a_reproducible_subset() -> None:
    result = _asset().monte_carlo(SimulationConfig(n_paths=200, horizon=10))

    samples = result.sample_paths(5)

    assert samples.shape == (11, 5)
    assert result.sample_paths(5).equals(samples)
    assert result.sample_paths(1_000).shape == (11, 200)


def test_summary_lists_every_confidence_level() -> None:
    config = SimulationConfig(n_paths=1_000, horizon=10, confidence_levels=(0.9, 0.99))

    summary = _asset().monte_carlo(config).summary()["value"]

    assert summary["initial_value"] == 10_000.0
    for label in ("90%", "99%"):
        assert summary[f"var_{label}_ci_low"] <= summary[f"var_{label}"]
        assert summary[f"var_{label}"] <= summary[f"var_{label}_ci_high"]
        assert summary[f"cvar_{label}"] >= summary[f"var_{label}"]
        assert summary[f"drawdown_at_risk_{label}"] <= 0.0


@pytest.mark.parametrize("level", [0.0, 1.0, 1.5])
def test_risk_measures_reject_invalid_levels(level: float) -> None:
    result = _asset().monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    for measure in (
        result.value_at_risk,
        result.conditional_value_at_risk,
        result.drawdown_at_risk,
    ):
        with pytest.raises(DomainError, match="Confidence level"):
            measure(level)


def test_conditional_value_at_risk_of_a_single_tail_path_has_no_error() -> None:
    result = _asset().monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    cvar = result.conditional_value_at_risk(0.995)

    assert cvar.standard_error == 0.0
    assert cvar.value == pytest.approx(-result.terminal_returns.min())


# ── Domain objects ───────────────────────────────────────────────────


def test_price_series_simulates_a_single_position() -> None:
    series = _asset()

    result = series.monte_carlo(SimulationConfig(n_paths=100, horizon=5))

    assert result.calibration.symbols == ("A",)
    assert result.calibration.weights.tolist() == [1.0]
    assert result.start == series.end


def test_default_configuration_is_used_when_none_is_given() -> None:
    result = _asset().monte_carlo()

    assert result.n_paths == 10_000
    assert result.horizon == 252


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (RebalancePolicy.periodic(Frequency.MONTH_1), (21, None)),
        (RebalancePolicy.periodic(Frequency.WEEK_1), (5, None)),
        (RebalancePolicy.periodic(Frequency.DAY_1), (1, None)),
        (RebalancePolicy.threshold(0.05), (None, 0.05)),
        (RebalancePolicy.buy_and_hold(), (None, None)),
    ],
)
def test_portfolio_policy_is_translated_into_simulation_steps(
    policy: RebalancePolicy, expected: tuple[int | None, float | None]
) -> None:
    assert _portfolio(policy)._simulation_rebalancing() == expected


def test_rebalancing_policy_changes_the_simulated_paths() -> None:
    config = SimulationConfig(n_paths=500, horizon=63)

    monthly = _portfolio(RebalancePolicy.periodic(Frequency.MONTH_1)).monte_carlo(config)
    held = _portfolio(RebalancePolicy.buy_and_hold()).monte_carlo(config)

    # Same shocks; the paths coincide until the first rebalance (step 21).
    assert np.allclose(monthly.values()[:, :22], held.values()[:, :22])
    assert not np.allclose(monthly.values()[:, -1], held.values()[:, -1])


def test_portfolio_weights_follow_the_price_columns() -> None:
    assets = [_asset("A", seed=1), _asset("B", seed=2)]
    portfolio = Portfolio.from_weights("Synthetic", assets, {"B": 0.3, "A": 0.7})

    calibration = portfolio.monte_carlo(SimulationConfig(n_paths=100, horizon=5)).calibration

    assert dict(zip(calibration.symbols, calibration.weights, strict=True)) == {"A": 0.7, "B": 0.3}
