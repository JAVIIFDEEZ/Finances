"""Start the local PostgreSQL with Docker (``just db-up``), tolerating flaky downloads.

The first ``docker compose up`` downloads the PostgreSQL image, and a connection that drops
halfway (``EOF``, ``TLS handshake timeout``, ``connection reset``) stops it. This script
checks Docker first, downloads the image with a few retries (Docker keeps the layers it
finished, so each retry has less left to download) and only then starts the service and
waits until it accepts connections. An image already downloaded is not asked for again.
When the download keeps failing, it says what usually causes that and how to go on.

The same launcher works in bash, zsh and PowerShell (``just`` runs its recipes with
PowerShell on Windows).

Usage::

    uv run python scripts/db.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

ROOT: Final = Path(__file__).resolve().parents[1]
SERVICE: Final = "postgres"
ATTEMPTS: Final = 4
FIRST_WAIT: Final = 5.0
"""Seconds before the first retry; each later one waits twice as long."""

NO_DOCKER: Final = """\
Docker is not installed (no `docker` command). Either install Docker Desktop, or install
PostgreSQL 16 yourself (on Windows: winget install PostgreSQL.PostgreSQL.16) and point
INVESTINGLAB_API_DATABASE_URL at it (docs/guide/persistence.md).
Everything but saved portfolios works without a database."""

NO_DAEMON: Final = """\
Docker is installed but not running. Start Docker Desktop, wait until it says it is
running, and run `uv run just db-up` again."""

NO_DOWNLOAD: Final = """\
Could not download the PostgreSQL image: the connection to Docker Hub kept dropping
({attempts} attempts). This is the network, not the project. What usually fixes it:
  - Run `uv run just db-up` again later, or from another network: university and office
    networks, VPNs and antivirus programs that inspect HTTPS often cut long downloads
    (a phone hotspot is a quick test).
  - Restart Docker Desktop (whale icon > Restart) and try again.
  - Behind a proxy, set it in Docker Desktop > Settings > Resources > Proxies.
Without Docker: install PostgreSQL 16 (on Windows: winget install PostgreSQL.PostgreSQL.16)
and point INVESTINGLAB_API_DATABASE_URL at it (docs/guide/persistence.md).
Everything but saved portfolios works without a database."""

type Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a Docker command in the project folder, showing its output as it comes."""
    return subprocess.run(command, cwd=ROOT, check=False, text=True)  # noqa: S603 - our commands


def _quiet(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a Docker command in the project folder and capture its output."""
    return subprocess.run(  # noqa: S603 - our commands
        command, cwd=ROOT, check=False, text=True, capture_output=True
    )


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)  # noqa: T201 - a command-line launcher


def image_present(docker: str, quiet: Runner = _quiet) -> bool:
    """Whether the service's image is already on this machine (no download needed)."""
    images = quiet([docker, "compose", "config", "--images", SERVICE])
    names = images.stdout.split() if images.returncode == 0 else []
    return bool(names) and all(
        quiet([docker, "image", "inspect", name]).returncode == 0 for name in names
    )


def pull(
    docker: str,
    run: Runner = _run,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = ATTEMPTS,
) -> bool:
    """Download the service's image, retrying a dropped connection; whether it succeeded."""
    wait = FIRST_WAIT
    for attempt in range(1, attempts + 1):
        if run([docker, "compose", "pull", SERVICE]).returncode == 0:
            return True
        if attempt < attempts:
            _say(f"Download interrupted (attempt {attempt}/{attempts}); retrying in {wait:.0f} s.")
            sleep(wait)
            wait *= 2
    return False


def main(
    run: Runner = _run,
    quiet: Runner = _quiet,
    sleep: Callable[[float], None] = time.sleep,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    """Check Docker, download the image if needed, start PostgreSQL and wait for it."""
    docker = which("docker")
    if docker is None:
        _say(NO_DOCKER)
        return 1
    if quiet([docker, "info"]).returncode != 0:
        _say(NO_DAEMON)
        return 1
    if not image_present(docker, quiet) and not pull(docker, run, sleep):
        _say(NO_DOWNLOAD.format(attempts=ATTEMPTS))
        return 1
    return run([docker, "compose", "up", "--detach", "--wait", SERVICE]).returncode


if __name__ == "__main__":
    sys.exit(main())
