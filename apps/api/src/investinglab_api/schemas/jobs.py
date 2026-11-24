"""Background jobs over HTTP: submitted with ``202 Accepted``, then read until they finish."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from investinglab.ports import JobStatus
from investinglab_api.schemas.analysis import SimulationIn, SimulationOut
from investinglab_api.schemas.backtest import BacktestIn, BacktestOut
from investinglab_api.schemas.common import ApiModel

__all__ = ["BacktestJobOut", "JobDetailOut", "JobErrorOut", "JobOut", "JobPage", "SimulationJobOut"]


class JobErrorOut(ApiModel):
    """Why a job failed, shaped like the API's Problem Details."""

    type: str = Field(description="URI of the kind of problem, documented in the API guide.")
    title: str
    detail: str


class JobOut(ApiModel):
    """A background job: where it is and, once finished, how it ended."""

    id: UUID
    kind: str = Field(
        description="What it runs (`simulation`, `backtest`); says what its result is."
    )
    status: JobStatus
    progress: float | None = Field(description="Fraction done, from 0 to 1, when known.")
    stage: str | None = Field(
        description="What it is doing now (`loading`, `simulating`, `backtesting`, `summarising`)."
    )
    cancel_requested: bool = Field(description="Its owner asked to stop it while it ran.")
    attempts: int = Field(description="Times a worker started it (more after a lost worker).")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: JobErrorOut | None = Field(description="Why it failed, once failed.")


class SimulationJobOut(JobOut):
    """A Monte Carlo simulation run in the background."""

    kind: Literal["simulation"]
    parameters: SimulationIn = Field(description="The simulation as it was submitted.")
    result: SimulationOut | None = Field(
        description="What `POST /api/v1/simulations` would answer, once succeeded."
    )


class BacktestJobOut(JobOut):
    """A backtest run in the background."""

    kind: Literal["backtest"]
    parameters: BacktestIn = Field(description="The backtest as it was submitted.")
    result: BacktestOut | None = Field(description="What trading the strategy did, once succeeded.")


JobDetailOut = Annotated[SimulationJobOut | BacktestJobOut, Field(discriminator="kind")]
"""A job with its parameters and result: their shape follows its kind."""


class JobPage(ApiModel):
    """A page of jobs, most recently submitted first (without their parameters or results)."""

    items: list[JobOut]
    next_cursor: str | None = Field(
        description="Send it as `cursor` to get the next page; null on the last one."
    )
