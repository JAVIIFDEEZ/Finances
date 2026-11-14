"""Start the local PostgreSQL with Docker (``just db-up``), tolerating flaky downloads.

The first ``docker compose up`` downloads the PostgreSQL image, and a connection that drops
halfway (``EOF``, ``TLS handshake timeout``, ``connection reset``) stops it. This script
checks Docker first, downloads the image with a retry (Docker keeps the layers it finished,
so a retry has less left to download) and only then starts the service and waits until it
accepts connections. An image already downloaded is not asked for again.

Some networks keep cutting Docker Hub's download servers. An official image is published,
byte for byte (same digest), on Google's copy of Docker Hub (``mirror.gcr.io``) and on
Amazon's (``public.ecr.aws/docker/library``), so when Docker Hub keeps failing the image
comes from those instead, and is tagged with its usual name for Compose. When every source
fails, the script says what usually causes that and how to go on.

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
ATTEMPTS: Final = 2
"""Attempts on each source (Docker Hub, then each mirror)."""
FIRST_WAIT: Final = 5.0
"""Seconds before the first retry; each later one waits twice as long."""
MIRRORS: Final = (
    ("mirror.gcr.io/library/", "Google's copy of Docker Hub"),
    ("public.ecr.aws/docker/library/", "Docker's official images on Amazon"),
)
"""Where else an official image (``postgres:16``) is published, with the same digest."""

NO_DOCKER: Final = """\
Docker is not installed (no `docker` command). Either install Docker Desktop, or install
PostgreSQL 16 yourself (on Windows: winget install PostgreSQL.PostgreSQL.16) and point
INVESTINGLAB_API_DATABASE_URL at it (docs/guide/persistence.md).
Everything but saved portfolios works without a database."""

NO_DAEMON: Final = """\
Docker is installed but not running. Start Docker Desktop, wait until it says it is
running, and run `uv run just db-up` again."""

NO_DOWNLOAD: Final = """\
Could not download the PostgreSQL image: the connection kept dropping
({sources}; {attempts} attempts each).
This is the network, not the project. What usually fixes it:
  - Run `uv run just db-up` again later, or from another network: university and office
    networks, VPNs and antivirus programs that inspect HTTPS often cut downloads
    (a phone hotspot is a quick test).
  - Restart Docker Desktop (whale icon > Restart) and try again.
  - In Docker Desktop > Settings > General, turn off
    "Use containerd for pulling and storing images" and try again: the classic image
    store retries each layer by itself.
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


def compose_image(docker: str, quiet: Runner = _quiet) -> str | None:
    """The service's image as Compose names it (``postgres:16``), if Compose can tell."""
    images = quiet([docker, "compose", "config", "--images", SERVICE])
    names = images.stdout.split() if images.returncode == 0 else []
    return names[0] if len(names) == 1 else None


def image_present(docker: str, image: str | None, quiet: Runner = _quiet) -> bool:
    """Whether the image is already on this machine (no download needed)."""
    return image is not None and quiet([docker, "image", "inspect", image]).returncode == 0


def mirrors(image: str | None) -> list[tuple[str, str]]:
    """The copies of a Docker Hub official image, with what each one is.

    Only official images (``postgres:16``, ``library/postgres:16``) are published there; an
    image of another registry or of a user's namespace has no mirror.
    """
    if image is None:
        return []
    name = image.removeprefix("docker.io/").removeprefix("library/")
    if "/" in name:
        return []
    return [(prefix + name, description) for prefix, description in MIRRORS]


def _attempt(
    command: Sequence[str],
    source: str,
    run: Runner,
    sleep: Callable[[float], None],
    attempts: int,
) -> bool:
    """Run a download, retrying a dropped connection; whether it succeeded."""
    wait = FIRST_WAIT
    for attempt in range(1, attempts + 1):
        if run(command).returncode == 0:
            return True
        if attempt < attempts:
            _say(
                f"Download from {source} interrupted (attempt {attempt}/{attempts}); "
                f"retrying in {wait:.0f} s."
            )
            sleep(wait)
            wait *= 2
    return False


def pull(
    docker: str,
    image: str | None,
    run: Runner = _run,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = ATTEMPTS,
) -> bool:
    """Download the service's image from Docker Hub, else from a mirror; whether it worked.

    A mirror's copy is tagged with the image's usual name, so that Compose finds it.
    """
    if _attempt([docker, "compose", "pull", SERVICE], "Docker Hub", run, sleep, attempts):
        return True
    for copy, description in mirrors(image):
        host = copy.split("/", 1)[0]
        _say(f"Trying {host} ({description}), which publishes the same image.")
        if not _attempt([docker, "pull", copy], host, run, sleep, attempts):
            continue
        if image is not None and run([docker, "tag", copy, image]).returncode == 0:
            _say(f"Downloaded {image} from {host}.")
            return True
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
    image = compose_image(docker, quiet)
    if not image_present(docker, image, quiet) and not pull(docker, image, run, sleep):
        sources = ["Docker Hub", *(copy.split("/", 1)[0] for copy, _ in mirrors(image))]
        _say(NO_DOWNLOAD.format(sources=", ".join(sources), attempts=ATTEMPTS))
        return 1
    return run([docker, "compose", "up", "--detach", "--wait", SERVICE]).returncode


if __name__ == "__main__":
    sys.exit(main())
