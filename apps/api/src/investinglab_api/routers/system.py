"""Health checks, providers and the modules of the master."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from investinglab.config import get_logger
from investinglab.modules import REGISTRY
from investinglab_api.dependencies import ToolkitDep
from investinglab_api.mappers import health_out, module_out, provider_out
from investinglab_api.schemas.meta import HealthOut, ModuleOut, ProviderOut

__all__ = ["router"]

router = APIRouter()
log = get_logger(__name__)

Language = Annotated[Literal["es", "en"], Query(description="Language of the texts.")]


def _offline(request: Request) -> bool:
    return bool(request.app.state.core_settings.offline)


@router.get("/health/live", tags=["health"], summary="Liveness", response_model=HealthOut)
async def live(request: Request, toolkit: ToolkitDep) -> HealthOut:
    """The process is up."""
    return health_out(toolkit.providers, offline=_offline(request))


@router.get("/health/ready", tags=["health"], summary="Readiness", response_model=HealthOut)
async def ready(request: Request, toolkit: ToolkitDep) -> HealthOut:
    """The service can answer: the toolkit is wired, and the database (if any) is reported.

    The endpoints that need no stored state keep working without a database, so its state is
    information here, not a failure.
    """
    database = getattr(request.app.state, "database", None)
    state = "not_configured" if database is None else str(await database.status())
    if state not in {"not_configured", "ok"}:
        log.warning("database_not_ready", state=state)
    return health_out(toolkit.providers, offline=_offline(request), database=state)


@router.get(
    "/api/v1/providers",
    tags=["system"],
    summary="Data providers",
    response_model=list[ProviderOut],
)
async def providers(toolkit: ToolkitDep) -> list[ProviderOut]:
    """Registered providers, in order of preference, and what each can serve."""
    return [
        provider_out(name, capabilities)
        for name, capabilities in toolkit.provider_capabilities().items()
    ]


@router.get(
    "/api/v1/modules",
    tags=["system"],
    summary="Modules of the master",
    response_model=list[ModuleOut],
)
async def modules(language: Language = "es") -> list[ModuleOut]:
    """Every registered module with its requirement → code → test traceability."""
    return [module_out(module, language) for module in REGISTRY]


@router.get(
    "/api/v1/modules/{slug}",
    tags=["system"],
    summary="One module of the master",
    response_model=ModuleOut,
    responses={404: {"description": "No module has that slug."}},
)
async def module(slug: str, language: Language = "es") -> ModuleOut:
    """A module and its traceability."""
    try:
        found = REGISTRY.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No module {slug!r}") from None
    return module_out(found, language)
