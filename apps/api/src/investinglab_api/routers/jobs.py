"""Background jobs: submitted with ``202 Accepted`` and a ``Location`` to read until finished.

Work too long for a request (a large Monte Carlo, a backtest) is submitted here
and run by a worker (``investinglab-api worker``). Reading the job shows its progress, and
its result once it succeeds.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from investinglab.domain.costs import cost_profile
from investinglab.ports import JobStatus
from investinglab_api.dependencies import JobsDep, OwnerDep, SettingsDep, at_most
from investinglab_api.jobs import BACKTEST, SIMULATION
from investinglab_api.mappers import (
    backtest_job_out,
    job_detail_out,
    job_page,
    simulation_job_out,
)
from investinglab_api.routers import problems
from investinglab_api.schemas.analysis import SimulationIn
from investinglab_api.schemas.backtest import BacktestIn
from investinglab_api.schemas.jobs import BacktestJobOut, JobDetailOut, JobPage, SimulationJobOut

__all__ = ["router"]

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

NO_DATABASE: Final = "The API runs without a database, or the database is not answering."
NOT_FOUND: Final = "The owner has no such job."
POLL_SECONDS: Final = "1"
"""``Retry-After`` of a job that has not finished: when reading it again is worth it."""


def _poll_hint(response: Response, status: JobStatus) -> None:
    if not status.finished:
        response.headers["Retry-After"] = POLL_SECONDS


@router.post(
    "/simulations",
    summary="Run a Monte Carlo simulation in the background",
    status_code=202,
    response_model=SimulationJobOut,
    responses=problems(422, s503=NO_DATABASE),
)
async def submit_simulation(  # noqa: PLR0917 - FastAPI injects them by name
    body: SimulationIn,
    request: Request,
    response: Response,
    owner: OwnerDep,
    jobs: JobsDep,
    settings: SettingsDep,
) -> SimulationJobOut:
    """Queue a simulation that may be larger than `POST /api/v1/simulations` allows.

    The answer is the job, queued; read its `Location` until `status` is `succeeded`
    (its `result` is then what the synchronous endpoint answers) or `failed` (its `error`).
    """
    at_most(body.portfolio.holdings, settings.max_symbols, "holdings")
    at_most(body.n_paths, settings.max_job_paths, "paths")
    at_most(body.horizon, settings.max_horizon, "periods of horizon")
    body.to_config()  # the domain's rules (memory bound...) fail now, not in the worker
    job = await jobs.submit(owner.owner_id, SIMULATION, body.model_dump(mode="json"))
    response.headers["Location"] = str(request.url_for("read_job", job_id=job.id))
    _poll_hint(response, job.status)
    return simulation_job_out(job)


@router.post(
    "/backtests",
    summary="Backtest a strategy in the background",
    status_code=202,
    response_model=BacktestJobOut,
    responses=problems(422, s503=NO_DATABASE),
)
async def submit_backtest(
    body: BacktestIn, request: Request, response: Response, owner: OwnerDep, jobs: JobsDep
) -> BacktestJobOut:
    """Queue a backtest of a strategy on one symbol, with the costs of its market (ADR-0051).

    The strategy and the cost profile are checked now: an invalid one answers `422` before
    anything is queued. Read its `Location` until `status` is `succeeded` (its `result` is
    what trading the strategy did) or `failed` (its `error`: no data, a market it cannot
    trade...).
    """
    body.to_strategy()  # the core's rules fail now, not in the worker
    if body.profile is not None:
        cost_profile(body.profile)
    job = await jobs.submit(owner.owner_id, BACKTEST, body.model_dump(mode="json"))
    response.headers["Location"] = str(request.url_for("read_job", job_id=job.id))
    _poll_hint(response, job.status)
    return backtest_job_out(job)


@router.get(
    "",
    summary="List jobs",
    response_model=JobPage,
    responses=problems(422, s503=NO_DATABASE),
)
async def list_jobs(
    owner: OwnerDep,
    jobs: JobsDep,
    limit: Annotated[int, Query(ge=1, le=200, description="Most jobs in a page.")] = 50,
    cursor: Annotated[str | None, Query(description="`next_cursor` of the page before.")] = None,
) -> JobPage:
    """The owner's jobs, most recently submitted first, without parameters or results."""
    return job_page(await jobs.list(owner.owner_id, limit=limit, cursor=cursor))


@router.get(
    "/{job_id}",
    name="read_job",
    summary="Read a job",
    response_model=JobDetailOut,
    responses=problems(422, s404=NOT_FOUND, s503=NO_DATABASE),
)
async def read_job(
    job_id: UUID, response: Response, owner: OwnerDep, jobs: JobsDep
) -> SimulationJobOut | BacktestJobOut:
    """Where the job is; its result once it succeeded. `Retry-After` while it runs."""
    job = await jobs.get(owner.owner_id, job_id)
    _poll_hint(response, job.status)
    return job_detail_out(job)


@router.post(
    "/{job_id}/cancel",
    summary="Cancel a job",
    response_model=JobDetailOut,
    responses=problems(
        422,
        s404=NOT_FOUND,
        s409="The job has already finished.",
        s503=NO_DATABASE,
    ),
)
async def cancel_job(
    job_id: UUID, response: Response, owner: OwnerDep, jobs: JobsDep
) -> SimulationJobOut | BacktestJobOut:
    """Stop a job: a queued one at once, a running one at its next progress report.

    A running job answers with `cancel_requested: true` and `status: running`; read it
    until `status` is `cancelled`.
    """
    job = await jobs.cancel(owner.owner_id, job_id)
    _poll_hint(response, job.status)
    return job_detail_out(job)


@router.delete(
    "/{job_id}",
    summary="Delete a finished job",
    status_code=204,
    responses=problems(
        422,
        s404=NOT_FOUND,
        s409="The job has not finished: cancel it first.",
        s503=NO_DATABASE,
    ),
)
async def delete_job(job_id: UUID, owner: OwnerDep, jobs: JobsDep) -> None:
    """Delete a job that has finished, with its result."""
    await jobs.remove(owner.owner_id, job_id)
