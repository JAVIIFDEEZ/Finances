"""Command line: serve the API or migrate its database.

``uv run investinglab-api [--reload]`` serves it; ``uv run investinglab-api db upgrade`` brings
the database of ``INVESTINGLAB_API_DATABASE_URL`` to the schema this version needs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from investinglab_api.settings import get_api_settings

__all__ = ["main"]


def _database(argv: list[str]) -> int:
    """``db upgrade``, ``db current`` and (for development) ``db revision -m "what changes"``."""
    from investinglab_api.persistence import migrate  # noqa: PLC0415 - only for this command

    parser = argparse.ArgumentParser(prog="investinglab-api db", description=_database.__doc__)
    parser.add_argument("action", choices=["upgrade", "current", "revision"])
    parser.add_argument("-m", "--message", help="what the new revision changes")
    arguments = parser.parse_args(argv)
    action = arguments.action
    url = get_api_settings().database_url
    if url is None:
        sys.stderr.write("Set INVESTINGLAB_API_DATABASE_URL to the database to migrate.\n")
        return 2
    if action == "revision":
        if not arguments.message:
            parser.error("revision needs -m with what it changes")
        migrate.revision(url.get_secret_value(), arguments.message)
    if action == "upgrade":
        migrate.upgrade(url.get_secret_value())
    current = migrate.current_revision(url.get_secret_value())
    sys.stdout.write(
        f"Database at revision {current} (this version needs {migrate.head_revision()})\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Serve the API, write its OpenAPI document (``--openapi PATH``) or migrate (``db``)."""
    arguments_in = sys.argv[1:] if argv is None else argv
    if arguments_in[:1] == ["db"]:
        return _database(arguments_in[1:])
    argv = arguments_in
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
        access_log=False,  # the API logs every request itself, with its request id
        proxy_headers=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
