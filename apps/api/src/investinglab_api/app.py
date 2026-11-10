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

from investinglab.config import configure_logging, get_settings
from investinglab.toolkit import AsyncToolkit
from investinglab_api import __version__
from investinglab_api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from investinglab_api.problems import install_problem_handlers
from investinglab_api.routers import market, portfolios, system
from investinglab_api.settings import ApiSettings, get_api_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from investinglab.config import Settings

__all__ = ["create_app"]

DESCRIPTION: Final = """
REST API of **InvestingLab**: market data from several providers, portfolio analytics,
Monte Carlo simulation, portfolio optimisation and savings plans.

* Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details
  (`application/problem+json`) with a documented `type`.
* Every response carries an `X-Request-ID` (send your own to correlate logs).
* Dates are ISO 8601: session dates for daily and coarser data, UTC instants intraday.
* Undefined figures are `null`: no value is ever invented.
"""

TAGS: Final = [
    {"name": "market", "description": "Bars, comparisons, data quality and risk-free rates."},
    {"name": "portfolios", "description": "Validation, analytics and reports of portfolios."},
    {"name": "analysis", "description": "Monte Carlo, optimisation and savings plans."},
    {"name": "system", "description": "Providers and modules of the master."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


def create_app(
    settings: ApiSettings | None = None,
    *,
    core_settings: Settings | None = None,
    toolkit: AsyncToolkit | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: API settings; ``INVESTINGLAB_API_*`` variables by default.
        core_settings: Core settings; ``INVESTINGLAB_*`` variables by default.
        toolkit: Toolkit to serve (it is not closed at shutdown); one is built from
            ``core_settings`` by default.
    """
    api = settings or get_api_settings()
    core = core_settings or get_settings()
    configure_logging(core.log_level, core.effective_log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = toolkit is None
        app.state.toolkit = toolkit or AsyncToolkit.from_settings(core)
        try:
            yield
        finally:
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
    install_problem_handlers(app)
    app.add_middleware(GZipMiddleware, minimum_size=1_024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(api.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    for router in (system.router, market.router, portfolios.router):
        app.include_router(router)
    return app
