"""Command line: serve the API, run its worker or migrate its database.

``uv run investinglab-api [--reload]`` serves it; ``uv run investinglab-api worker`` runs the
background jobs; ``uv run investinglab-api db upgrade`` brings the database of
``INVESTINGLAB_API_DATABASE_URL`` to the schema this version needs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import uvicorn

from investinglab_api.settings import get_api_settings

__all__ = ["main"]


def _unreachable(url: str, error: Exception) -> str:
    """Why the database did not answer and what to do, without its password."""
    from sqlalchemy.engine import make_url  # noqa: PLC0415 - only for this command

    parts = make_url(url)
    where = f"{parts.host or 'localhost'}:{parts.port or 5432}/{parts.database or ''}"
    reason = str(getattr(error, "orig", None) or error).strip().splitlines()[0]
    return (
        f"Could not reach the database at {where}: {reason}\n"
        "Is PostgreSQL running? Locally: `uv run just db-up`. To run without a database, "
        "remove INVESTINGLAB_API_DATABASE_URL from .env.\n"
    )


def _database(argv: list[str]) -> int:
    """``db upgrade``, ``db current`` and (for development) ``db revision -m "what changes"``."""
    from sqlalchemy.exc import OperationalError  # noqa: PLC0415 - only for this command

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
    if action == "revision" and not arguments.message:
        parser.error("revision needs -m with what it changes")
    secret = url.get_secret_value()
    try:
        if action == "revision":
            migrate.revision(secret, arguments.message)
        if action == "upgrade":
            migrate.upgrade(secret)
        current = migrate.current_revision(secret)
    except OperationalError as error:
        sys.stderr.write(_unreachable(secret, error))
        return 1
    sys.stdout.write(
        f"Database at revision {current} (this version needs {migrate.head_revision()})\n"
    )
    return 0


def _worker() -> int:
    """Run background jobs until Ctrl+C."""
    from investinglab.config import get_settings  # noqa: PLC0415 - only for this command
    from investinglab_api.worker import WorkerNotReadyError, serve  # noqa: PLC0415 - idem

    try:
        asyncio.run(serve(get_api_settings(), get_settings()))
    except WorkerNotReadyError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


def main(argv: list[str] | None = None) -> int:
    """Serve the API, write its OpenAPI document (``--openapi PATH``), run the worker or migrate."""
    arguments_in = sys.argv[1:] if argv is None else argv
    if arguments_in[:1] == ["worker"]:
        return _worker()
    if arguments_in[:1] == ["db"]:
        try:
            return _database(arguments_in[1:])
        except KeyboardInterrupt:
            # Ctrl+C: a migration runs in one transaction, so nothing is left half done.
            sys.stderr.write("Interrupted: the database was left as it was.\n")
            return 130
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
