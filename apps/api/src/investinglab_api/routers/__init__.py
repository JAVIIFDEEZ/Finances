"""HTTP routers: validate the request, call a use case, map the result (no logic here)."""

from __future__ import annotations

from typing import Any, Final

from investinglab_api.problems import PROBLEM_JSON
from investinglab_api.schemas.common import Problem

__all__ = ["problems"]

_DESCRIPTIONS: Final = {
    404: "No provider has the requested data.",
    422: "The request breaks the schema, a limit or a domain rule.",
    503: "Every provider able to serve the data failed; retry later.",
    504: "The request took too long.",
}


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI documentation of the Problem Details an endpoint may answer."""
    return {
        status: {
            "model": Problem,
            "description": _DESCRIPTIONS[status],
            "content": {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status in statuses
    }
