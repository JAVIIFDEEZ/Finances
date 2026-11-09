"""Goal-based planning: savings plans simulated with Monte Carlo (ADR-0024).

A savings plan invests an initial capital, adds (or withdraws) an amount at the end of every
month and aims at a goal expressed in today's money. The asset or portfolio is simulated
month by month as a whole: its monthly returns are calibrated on the history of its value,
so the rebalancing policy and the co-movements of the holdings are already inside them.
Every simulated path then compounds the cash flows:

    W_t = max(W_{t-1} · (1 + R_t) + c_t, 0)

A path that runs out of money stays at zero (only possible with withdrawals). Results are
reported in today's money, deflated by the assumed inflation.

With non-negative contributions the terminal wealth is linear in the contribution,
``W_T = A + C·B`` on every path, so the contribution that reaches the goal with a given
probability is computed exactly from the simulated paths, without re-simulating.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from investinglab.domain.errors import DomainError
from investinglab.domain.simulation import (
    SimulationConfig,
    SimulationInputs,
    SimulationResult,
    simulate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from matplotlib.figure import Figure

__all__ = ["MONTHS_PER_YEAR", "PlanResult", "SavingsPlan", "month_end_values", "simulate_plan"]

MONTHS_PER_YEAR = 12
_MAX_YEARS = 100


@dataclass(frozen=True, slots=True)
class SavingsPlan:
    """A savings (or withdrawal) plan simulated month by month.

    Attributes:
        years: Horizon of the plan (rounded to whole months).
        initial: Capital invested at the start.
        contribution: Amount added at the end of every month; negative to withdraw.
        contribution_growth: Annual growth of the contribution (``0.02`` keeps a 2 %
            indexation), applied month by month.
        goal: Wealth wanted at the horizon, in today's money; ``None`` for no goal.
        inflation: Annual inflation used to express the results in today's money.
    """

    years: float
    initial: float = 0.0
    contribution: float = 0.0
    contribution_growth: float = 0.0
    goal: float | None = None
    inflation: float = 0.0

    def __post_init__(self) -> None:
        problems: list[str] = []
        if not 0 < self.years <= _MAX_YEARS or round(self.years * MONTHS_PER_YEAR) < 1:
            problems.append(f"years must be between one month and {_MAX_YEARS} years")
        if not (math.isfinite(self.initial) and self.initial >= 0):
            problems.append("initial must be a non-negative amount")
        if not math.isfinite(self.contribution):
            problems.append("contribution must be finite")
        if self.initial <= 0 and self.contribution <= 0:
            problems.append("the plan invests nothing: set initial or a positive contribution")
        if not (math.isfinite(self.contribution_growth) and self.contribution_growth > -1):
            problems.append("contribution_growth must be above -100 %")
        if not (math.isfinite(self.inflation) and self.inflation > -1):
            problems.append("inflation must be above -100 %")
        if self.goal is not None and not (math.isfinite(self.goal) and self.goal > 0):
            problems.append("goal must be a positive amount")
        if problems:
            raise DomainError("Invalid savings plan: " + "; ".join(problems))

    @property
    def months(self) -> int:
        """Number of monthly steps."""
        return round(self.years * MONTHS_PER_YEAR)

    def contributions(self) -> np.ndarray:
        """Nominal cash flow at the end of each month, ``(months,)``."""
        months = np.arange(self.months)
        growth = (1.0 + self.contribution_growth) ** (months / MONTHS_PER_YEAR)
        return np.asarray(self.contribution * growth, dtype="float64")

    def deflator(self) -> np.ndarray:
        """Price level relative to today at every month, ``(months + 1,)``."""
        months = np.arange(self.months + 1)
        return np.asarray((1.0 + self.inflation) ** (months / MONTHS_PER_YEAR), dtype="float64")


def month_end_values(values: pd.Series) -> pd.Series:
    """Last observed value of every calendar month, with its real date (nothing invented)."""
    index = pd.DatetimeIndex(values.index)
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    months = index.to_period("M")
    last = ~pd.Series(months).duplicated(keep="last").to_numpy()
    return values[last]


@dataclass(frozen=True, slots=True, eq=False)
class PlanResult:
    """Simulated wealth of a savings plan and its odds of reaching the goal.

    Attributes:
        plan: The plan simulated.
        simulation: Monte Carlo of one unit invested in the asset or portfolio (monthly).
        currency: Currency of the amounts.
    """

    plan: SavingsPlan
    simulation: SimulationResult = field(repr=False)
    currency: str
    _wealth: np.ndarray = field(repr=False)
    _base: np.ndarray = field(repr=False)
    _per_contribution: np.ndarray = field(repr=False)

    @property
    def n_paths(self) -> int:
        """Number of simulated paths."""
        return int(self._wealth.shape[0])

    @property
    def months(self) -> int:
        """Number of monthly steps."""
        return self.plan.months

    def wealth(self, *, real: bool = True) -> np.ndarray:
        """Wealth of every path at every month, ``(n_paths, months + 1)`` (a copy)."""
        if not real:
            return self._wealth.copy()
        return np.asarray(self._wealth / self.plan.deflator(), dtype="float64")

    def terminal_wealth(self, *, real: bool = True) -> np.ndarray:
        """Wealth of every path at the horizon."""
        return self.wealth(real=real)[:, -1]

    def percentile_paths(
        self, percentiles: Sequence[float] = (5, 25, 50, 75, 95), *, real: bool = True
    ) -> pd.DataFrame:
        """Wealth percentiles at every month (the fan chart), indexed by month 0..months."""
        bands = np.percentile(self.wealth(real=real), list(percentiles), axis=0)
        return pd.DataFrame(
            bands.T,
            index=pd.RangeIndex(self.months + 1, name="month"),
            columns=[f"p{p:g}" for p in percentiles],
        )

    def contributed(self, *, real: bool = True) -> np.ndarray:
        """Money put in (initial plus contributions) up to every month, ``(months + 1,)``."""
        flows = np.concatenate([[self.plan.initial], self.plan.contributions()])
        if real:
            flows = flows / self.plan.deflator()
        return np.asarray(np.cumsum(flows), dtype="float64")

    @property
    def median_terminal_wealth(self) -> float:
        """Median wealth at the horizon, in today's money."""
        return float(np.median(self.terminal_wealth()))

    @property
    def probability_of_success(self) -> float | None:
        """Share of paths that end at or above the goal (``None`` without a goal)."""
        if self.plan.goal is None:
            return None
        return float((self.terminal_wealth() >= self.plan.goal).mean())

    @property
    def expected_shortfall(self) -> float | None:
        """Average gap to the goal on the paths that miss it, in today's money."""
        if self.plan.goal is None:
            return None
        gap = self.plan.goal - self.terminal_wealth()
        missed = gap[gap > 0]
        return float(missed.mean()) if missed.size else 0.0

    @property
    def probability_of_ruin(self) -> float:
        """Share of paths that run out of money before the horizon (withdrawal plans)."""
        return float((self._wealth[:, 1:] <= 0).any(axis=1).mean())

    def required_contribution(self, probability: float = 0.9) -> float:
        """First monthly contribution that reaches the goal on ``probability`` of the paths.

        It grows at the plan's ``contribution_growth`` like the original one. Computed exactly
        from the simulated paths (terminal wealth is linear in the contribution); zero when
        the initial capital alone already reaches the goal that often.

        Raises:
            DomainError: Without a goal, or if ``probability`` is not in ``(0, 1)``.
        """
        if self.plan.goal is None:
            raise DomainError("The plan has no goal")
        if not 0 < probability < 1:
            raise DomainError(f"probability must be in (0, 1), got {probability}")
        target = self.plan.goal * float(self.plan.deflator()[-1])
        needed = (target - self._base) / self._per_contribution
        return max(0.0, float(np.quantile(needed, probability, method="higher")))

    def summary(self) -> pd.DataFrame:
        """Key figures in one table (metric → value), amounts in today's money."""
        terminal = self.terminal_wealth()
        rows: dict[str, float] = {
            "years": self.plan.years,
            "contributed": float(self.contributed(real=False)[-1]),
            "contributed_real": float(self.contributed()[-1]),
            "median_terminal_wealth": self.median_terminal_wealth,
            "terminal_wealth_p5": float(np.percentile(terminal, 5)),
            "terminal_wealth_p95": float(np.percentile(terminal, 95)),
            "probability_of_ruin": self.probability_of_ruin,
        }
        if self.plan.goal is not None:
            rows["goal"] = self.plan.goal
            rows["probability_of_success"] = float(self.probability_of_success or 0.0)
            rows["expected_shortfall"] = float(self.expected_shortfall or 0.0)
            rows["required_contribution_90"] = self.required_contribution(0.9)
        return pd.DataFrame({"value": rows})

    def plot(self, **options: Any) -> Figure:  # noqa: ANN401
        """Fan chart of the wealth in today's money, the money put in and the goal.

        Requires the ``plots`` extra (matplotlib). See
        :func:`investinglab.reporting.planning.plan_figure` for the options (``title`` and
        ``language``).
        """
        # Lazy, documented exception to the layering (ADR-0017, ADR-0024).
        from investinglab.reporting.entrypoints import plan_plot  # noqa: PLC0415

        return plan_plot(self, **options)


def simulate_plan(
    values: pd.Series,
    plan: SavingsPlan,
    config: SimulationConfig | None = None,
    *,
    currency: str,
) -> PlanResult:
    """Simulate ``plan`` on an asset or portfolio whose value history is ``values``.

    The monthly returns are calibrated on the month-end values (``config`` chooses the model,
    the drift and volatility assumptions and the number of paths; its horizon and initial
    value are set by the plan).

    Raises:
        DomainError: If the history is too short to calibrate monthly returns.
    """
    monthly = month_end_values(values.dropna())
    if len(monthly) < 3:  # noqa: PLR2004
        raise DomainError("A savings plan needs at least three months of history")
    settings = replace(config or SimulationConfig(), horizon=plan.months, initial_value=1.0)
    inputs = SimulationInputs(
        prices=monthly.to_frame("value"),
        weights=np.array([1.0]),
        periods_per_year=float(MONTHS_PER_YEAR),
        rebalance_every=None,
        band=None,
        start=pd.Timestamp(monthly.index[-1]),
    )
    simulation = simulate(inputs, settings)
    unit = simulation.values()
    growth = unit[:, 1:] / unit[:, :-1]
    flows = plan.contributions()

    wealth = np.empty_like(unit)
    wealth[:, 0] = plan.initial
    ruined = np.zeros(simulation.n_paths, dtype=bool)
    for month in range(plan.months):
        step = wealth[:, month] * growth[:, month] + flows[month]
        ruined |= step <= 0
        wealth[:, month + 1] = np.where(ruined, 0.0, step)

    # Growth from the end of each month to the horizon: suffix products of the growth.
    to_horizon = np.ones_like(unit)
    to_horizon[:, :-1] = np.cumprod(growth[:, ::-1], axis=1)[:, ::-1]
    indexation = (1.0 + plan.contribution_growth) ** (np.arange(plan.months) / MONTHS_PER_YEAR)
    return PlanResult(
        plan=plan,
        simulation=simulation,
        currency=currency,
        _wealth=wealth,
        _base=plan.initial * to_horizon[:, 0],
        _per_contribution=to_horizon[:, 1:] @ indexation,
    )
