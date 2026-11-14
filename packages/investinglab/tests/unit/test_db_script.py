"""The launcher behind ``just db-up``: Docker checks and a download that survives drops."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

    import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


db = _load("db")
IMAGE = "postgres:16"


GCR = "mirror.gcr.io/library/postgres:16"
ECR = "public.ecr.aws/docker/library/postgres:16"


class FakeDocker:
    """Answers Docker commands like a machine with or without the image and a network.

    ``failures`` is how many downloads fail on each source (``"hub"`` or a mirror's image).
    """

    def __init__(
        self, *, running: bool = True, image: bool = False, failures: dict[str, int] | None = None
    ) -> None:
        self.running = running
        self.images = {IMAGE} if image else set()
        self.failures = dict(failures or {})
        self.commands: list[list[str]] = []

    def _download(self, source: str, image: str) -> int:
        if self.failures.get(source, 0) > 0:
            self.failures[source] -= 1
            return 1
        self.images.add(image)
        return 0

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        args = list(command)[1:]
        self.commands.append(args)
        code, out = 0, ""
        if args == ["info"]:
            code = 0 if self.running else 1
        elif args[:3] == ["compose", "config", "--images"]:
            out = f"{IMAGE}\n"
        elif args[:2] == ["image", "inspect"]:
            code = 0 if args[2] in self.images else 1
        elif args[:2] == ["compose", "pull"]:
            code = self._download("hub", IMAGE)
        elif args[0] == "pull":
            code = self._download(args[1], args[1])
        elif args[0] == "tag":
            code = 0 if args[1] in self.images else 1
            if code == 0:
                self.images.add(args[2])
        return subprocess.CompletedProcess(command, code, out, "")


def _main(docker: FakeDocker, waits: list[float], found: str | None = "/usr/bin/docker") -> int:
    exit_code: int = db.main(
        run=docker, quiet=docker, sleep=waits.append, which=lambda _name: found
    )
    return exit_code


UP = ["compose", "up", "--detach", "--wait", "postgres"]


def test_the_first_start_downloads_the_image_and_waits_for_postgres() -> None:
    docker = FakeDocker()
    waits: list[float] = []

    assert _main(docker, waits) == 0
    assert ["compose", "pull", "postgres"] in docker.commands
    assert docker.commands[-1] == UP
    assert waits == []


def test_an_image_already_downloaded_is_not_asked_for_again() -> None:
    docker = FakeDocker(image=True)
    waits: list[float] = []

    assert _main(docker, waits) == 0
    assert not any("pull" in command for command in docker.commands)
    assert docker.commands[-1] == UP


def test_a_dropped_download_is_retried(capsys: pytest.CaptureFixture[str]) -> None:
    docker = FakeDocker(failures={"hub": 1})
    waits: list[float] = []

    assert _main(docker, waits) == 0
    assert waits == [5.0]
    assert docker.commands[-1] == UP
    assert not any(command[0] == "pull" for command in docker.commands)
    err = capsys.readouterr().err
    assert "Download from Docker Hub interrupted (attempt 1/2); retrying in 5 s." in err


def test_when_docker_hub_keeps_failing_the_same_image_comes_from_a_mirror(
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker = FakeDocker(failures={"hub": 10})
    waits: list[float] = []

    assert _main(docker, waits) == 0
    assert ["pull", GCR] in docker.commands
    assert ["tag", GCR, IMAGE] in docker.commands
    assert IMAGE in docker.images
    assert docker.commands[-1] == UP
    err = capsys.readouterr().err
    assert "Trying mirror.gcr.io (Google's copy of Docker Hub)" in err
    assert "Downloaded postgres:16 from mirror.gcr.io." in err


def test_the_next_mirror_is_tried_when_one_fails_too() -> None:
    docker = FakeDocker(failures={"hub": 10, GCR: 10})
    waits: list[float] = []

    assert _main(docker, waits) == 0
    assert waits == [5.0, 5.0]
    assert ["tag", ECR, IMAGE] in docker.commands
    assert ["tag", GCR, IMAGE] not in docker.commands
    assert docker.commands[-1] == UP


def test_a_download_that_fails_everywhere_says_what_to_do(
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker = FakeDocker(failures={"hub": 10, GCR: 10, ECR: 10})
    waits: list[float] = []

    assert _main(docker, waits) == 1
    assert waits == [5.0, 5.0, 5.0]
    assert UP not in docker.commands
    message = capsys.readouterr().err
    assert "(Docker Hub, mirror.gcr.io, public.ecr.aws; 2 attempts each)" in message
    assert "Use containerd for pulling and storing images" in message
    assert "winget install PostgreSQL.PostgreSQL.16" in message


def test_docker_stopped_or_missing_is_explained(capsys: pytest.CaptureFixture[str]) -> None:
    stopped = FakeDocker(running=False)

    assert _main(stopped, []) == 1
    assert "not running" in capsys.readouterr().err
    assert stopped.commands == [["info"]]
    assert _main(FakeDocker(), [], found=None) == 1
    assert "Docker is not installed" in capsys.readouterr().err


def test_an_unreadable_compose_file_means_downloading_without_mirrors() -> None:
    broken = lambda command: subprocess.CompletedProcess(command, 1, "", "")  # noqa: E731

    assert db.compose_image("docker", broken) is None
    assert not db.image_present("docker", None, broken)
    assert db.compose_image("docker", FakeDocker()) == IMAGE
    assert not db.pull("docker", None, run=broken, sleep=lambda _s: None)


def test_only_official_images_have_mirrors() -> None:
    copies = [copy for copy, _ in db.mirrors("postgres:16")]

    assert copies == [GCR, ECR]
    assert db.mirrors("docker.io/library/postgres:16") == db.mirrors("postgres:16")
    assert db.mirrors("library/postgres:16") == db.mirrors("postgres:16")
    assert db.mirrors("bitnami/postgresql:16") == []
    assert db.mirrors("ghcr.io/acme/postgres:16") == []
    assert db.mirrors(None) == []
