"""Application factory: the API's composition root (ADR-0027).

``create_app()`` wires the core's :class:`~investinglab.toolkit.AsyncToolkit` from the
``INVESTINGLAB_*`` settings at start-up and closes it at shutdown. Tests and alternative
deployments pass their own toolkit instead.

Run it locally with::

    uv run investinglab-api              # http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from investinglab.config import configure_logging, get_logger, get_settings
from investinglab.toolkit import AsyncToolkit
from investinglab_api import __version__
from investinglab_api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from investinglab_api.persistence import (
    Database,
    SqlHeartbeatStore,
    SqlJobRepository,
    SqlPortfolioRepository,
    queue_app,
)
from investinglab_api.problems import install_problem_handlers
from investinglab_api.routers import economic, jobs, market, saved_portfolios, system
from investinglab_api.routers import portfolios as portfolio_analysis
from investinglab_api.settings import ApiSettings, get_api_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from investinglab.config import Settings
    from investinglab.ports import HeartbeatStore, JobRepository, PortfolioRepository

__all__ = ["create_app"]

log = get_logger(__name__)
LOOPBACK: Final = frozenset({"127.0.0.1", "::1", "localhost"})

DESCRIPTION: Final = """
REST API of **InvestingLab**: market data from several providers, portfolio analytics,
Monte Carlo simulation, portfolio optimisation and savings plans.

* Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details
  (`application/problem+json`) with a documented `type`.
* Every response carries an `X-Request-ID` (send your own to correlate logs).
* Dates are ISO 8601: session dates for daily and coarser data, UTC instants intraday.
* Undefined figures are `null`: no value is ever invented.
* Saved records carry a version in their `ETag`; a change quotes it in `If-Match`.
* Work too long for a request runs as a background job: `202 Accepted` with a `Location`
  to read until it finishes (`Retry-After` says when to read again).
"""

TAGS: Final = [
    {"name": "market", "description": "Bars, comparisons, data quality and risk-free rates."},
    {"name": "portfolios", "description": "Saved portfolios, validation, analytics and reports."},
    {"name": "analysis", "description": "Monte Carlo, optimisation and savings plans."},
    {"name": "jobs", "description": "Background jobs: long work run by a worker."},
    {"name": "system", "description": "Providers and modules of the master."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


def create_app(
    settings: ApiSettings | None = None,
    *,
    core_settings: Settings | None = None,
    toolkit: AsyncToolkit | None = None,
    portfolios: PortfolioRepository | None = None,
    jobs_repository: JobRepository | None = None,
    heartbeats: HeartbeatStore | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: API settings; ``INVESTINGLAB_API_*`` variables by default.
        core_settings: Core settings; ``INVESTINGLAB_*`` variables by default.
        toolkit: Toolkit to serve (it is not closed at shutdown); one is built from
            ``core_settings`` by default.
        portfolios: Repository of saved portfolios; by default the PostgreSQL one when
            ``settings.database_url`` is set, and none otherwise (those endpoints then answer
            ``persistence-not-configured`` and the rest of the API works as usual).
        jobs_repository: Repository of background jobs, with the same default as
            ``portfolios`` (on PostgreSQL it also queues them for the workers).
        heartbeats: Where the worker keeps the status of each data source, with the same
            default as ``portfolios``.
    """
    api = settings or get_api_settings()
    core = core_settings or get_settings()
    configure_logging(core.log_level, core.effective_log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = toolkit is None
        app.state.toolkit = toolkit or AsyncToolkit.from_settings(core)
        database: Database | None = None
        own_stores = portfolios is None and jobs_repository is None and heartbeats is None
        if own_stores and api.database_url is not None:
            url = api.database_url.get_secret_value()
            database = Database(url, pool_size=api.database_pool_size)
            app.state.portfolios = SqlPortfolioRepository(database)
            app.state.jobs = SqlJobRepository(database, queue_app(url))
            app.state.heartbeats = SqlHeartbeatStore(database)
            if api.host not in LOOPBACK:
                log.warning("unauthenticated_api_exposed", host=api.host)
        app.state.database = database
        try:
            yield
        finally:
            if database is not None:
                await database.dispose()
            if owned:
                await app.state.toolkit.aclose()

    app = FastAPI(
        title="InvestingLab API",
        version=__version__,
        summary="Market data, portfolio analytics and simulation for the InvestingLab web app.",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.settings = api
    app.state.core_settings = core
    app.state.portfolios = portfolios
    app.state.jobs = jobs_repository
    app.state.heartbeats = heartbeats
    app.state.database = None
    install_problem_handlers(app)
    app.add_middleware(GZipMiddleware, minimum_size=1_024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(api.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "If-Match", REQUEST_ID_HEADER],
        expose_headers=["ETag", "Location", "Retry-After", REQUEST_ID_HEADER],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    routers = (
        system.router,
        market.router,
        economic.router,
        saved_portfolios.router,
        portfolio_analysis.router,
        jobs.router,
    )
    for router in routers:
        app.include_router(router)
    return app
