"""The kinds of job the workers run, each with the handler that runs it.

A kind's parameters are the request body of its endpoint, stored as JSON when it is
submitted, and its result is the same document the synchronous endpoint would answer. A
new kind is one handler here and one endpoint in ``routers/jobs.py``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from investinglab_api import use_cases
from investinglab_api.mappers import backtest_out, simulation_out
from investinglab_api.schemas.analysis import SimulationIn
from investinglab_api.schemas.backtest import BacktestIn

if TYPE_CHECKING:
    from collections.abc import Mapping

    from investinglab.ports import JsonValue
    from investinglab_api.jobs.runner import Handler, JobContext

__all__ = ["BACKTEST", "HANDLERS", "SIMULATION", "Stage", "backtest", "simulation"]

SIMULATION: Final = "simulation"
"""A Monte Carlo simulation of a portfolio, larger than a request allows."""

BACKTEST: Final = "backtest"
"""A strategy on one symbol with the costs of its market (ADR-0051)."""


class Stage:
    """Stages a job reports (slugs the web translates)."""

    LOADING: Final = "loading"
    SIMULATING: Final = "simulating"
    BACKTESTING: Final = "backtesting"
    SUMMARISING: Final = "summarising"


async def simulation(context: JobContext) -> JsonValue:
    """Load the portfolio's history, simulate it chunk by chunk and summarise the paths."""
    request = SimulationIn.model_validate(context.parameters)
    context.progress.update(0.0, Stage.LOADING)
    portfolio = await use_cases.build_portfolio(context.toolkit, request.portfolio)
    context.progress.update(0.0, Stage.SIMULATING)

    def report(done: float) -> None:
        context.progress.update(done, Stage.SIMULATING)

    result = await asyncio.to_thread(portfolio.monte_carlo, request.to_config(), progress=report)
    context.progress.update(1.0, Stage.SUMMARISING)
    summary = await asyncio.to_thread(simulation_out, result)
    document: JsonValue = summary.model_dump(mode="json")
    return document


async def backtest(context: JobContext) -> JsonValue:
    """Download the bars (and a perpetual's funding), trade the strategy and summarise it."""
    request = BacktestIn.model_validate(context.parameters)
    context.progress.update(0.0, Stage.BACKTESTING)
    result = await use_cases.backtest(context.toolkit, request)
    context.progress.update(1.0, Stage.SUMMARISING)
    summary = await asyncio.to_thread(backtest_out, result)
    document: JsonValue = summary.model_dump(mode="json")
    return document


HANDLERS: Final[Mapping[str, Handler]] = {SIMULATION: simulation, BACKTEST: backtest}
"""Every kind a worker knows how to run."""
