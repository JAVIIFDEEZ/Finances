"""HTTP routers: validate the request, call a use case, map the result (no logic here)."""

from __future__ import annotations

from typing import Any, Final

from investinglab_api.problems import PROBLEM_JSON
from investinglab_api.schemas.common import Problem

__all__ = ["problems"]

_DESCRIPTIONS: Final = {
    404: "No provider has the requested data.",
    409: "The owner already has a record with that name.",
    412: "The record changed since the version sent in `If-Match`.",
    422: "The request breaks the schema, a limit or a domain rule.",
    428: "The change needs an `If-Match` header with the version last read.",
    503: "Every provider able to serve the data failed; retry later.",
    504: "The request took too long.",
}


def problems(*statuses: int, **described: str) -> dict[int | str, dict[str, Any]]:
    """OpenAPI documentation of the Problem Details an endpoint may answer.

    Args:
        *statuses: Statuses with their usual meaning.
        **described: Statuses that mean something else here, as ``s404="No such…"``.
    """
    descriptions = {status: _DESCRIPTIONS[status] for status in statuses}
    descriptions.update({int(key[1:]): text for key, text in described.items()})
    return {
        status: {
            "model": Problem,
            "description": descriptions[status],
            "content": {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}},
        }
        for status in sorted(descriptions)
    }
