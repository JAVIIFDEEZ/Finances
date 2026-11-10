"""Command line: serve the API (``uv run investinglab-api [--reload]``)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from investinglab_api.settings import get_api_settings

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Serve the API, or write its OpenAPI document with ``--openapi PATH``."""
    parser = argparse.ArgumentParser(prog="investinglab-api", description=__doc__)
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    parser.add_argument("--openapi", type=Path, help="write the OpenAPI document and exit")
    arguments = parser.parse_args(argv)
    if arguments.openapi is not None:
        from investinglab_api.app import create_app  # noqa: PLC0415 - only for this command

        document = create_app().openapi()
        arguments.openapi.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return 0
    settings = get_api_settings()
    uvicorn.run(
        "investinglab_api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=arguments.reload,
        log_config=None,  # structlog configures the logging
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
