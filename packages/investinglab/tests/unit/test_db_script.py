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


class FakeDocker:
    """Answers Docker commands like a machine with or without the image and a network."""

    def __init__(self, *, running: bool = True, image: bool = False, failed_pulls: int = 0) -> None:
        self.running = running
        self.image = image
        self.failed_pulls = failed_pulls
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        args = list(command)[1:]
        self.commands.append(args)
        code, out = 0, ""
        if args == ["info"]:
            code = 0 if self.running else 1
        elif args[:3] == ["compose", "config", "--images"]:
            out = f"{IMAGE}\n"
        elif args[:2] == ["image", "inspect"]:
            code = 0 if self.image else 1
        elif args[:2] == ["compose", "pull"]:
            if self.failed_pulls:
                self.failed_pulls -= 1
                code = 1
            else:
                self.image = True
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
    assert not any(command[:2] == ["compose", "pull"] for command in docker.commands)
    assert docker.commands[-1] == UP


def test_a_dropped_download_is_retried_with_longer_waits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker = FakeDocker(failed_pulls=2)
    waits: list[float] = []

    assert _main(docker, waits) == 0
    assert waits == [5.0, 10.0]
    assert docker.commands[-1] == UP
    assert "Download interrupted (attempt 2/4); retrying in 10 s." in capsys.readouterr().err


def test_a_download_that_keeps_failing_says_what_to_do(
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker = FakeDocker(failed_pulls=10)
    waits: list[float] = []

    assert _main(docker, waits) == 1
    assert waits == [5.0, 10.0, 20.0]
    assert UP not in docker.commands
    message = capsys.readouterr().err
    assert "connection to Docker Hub kept dropping" in message
    assert "(4 attempts)" in message
    assert "winget install PostgreSQL.PostgreSQL.16" in message


def test_docker_stopped_or_missing_is_explained(capsys: pytest.CaptureFixture[str]) -> None:
    stopped = FakeDocker(running=False)

    assert _main(stopped, []) == 1
    assert "not running" in capsys.readouterr().err
    assert stopped.commands == [["info"]]
    assert _main(FakeDocker(), [], found=None) == 1
    assert "Docker is not installed" in capsys.readouterr().err


def test_an_unreadable_compose_file_means_downloading() -> None:
    docker = FakeDocker(image=True)
    broken = lambda command: subprocess.CompletedProcess(command, 1, "", "")  # noqa: E731

    assert not db.image_present("docker", broken)
    assert db.image_present("docker", docker)
