"""Run the API and the web app together (``just dev`` and ``just preview``).

The same launcher works in bash, zsh and PowerShell (``just`` runs its recipes with
PowerShell on Windows). Each server runs in a process group of its own: Ctrl+C stops both,
together with every process they started (uvicorn's reloader, Next.js workers), and when one
of them stops on its own the other one is stopped too.

Usage::

    uv run python scripts/dev.py            # API and web app, both with live reload
    uv run python scripts/dev.py --preview  # API and the production build of the web app
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import FrameType

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
ADDRESSES = "API: http://127.0.0.1:8000/docs | web: http://localhost:3000 | Ctrl+C stops both"
POLL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class Server:
    """A server to run: its name in messages, its command and its working directory."""

    name: str
    command: Sequence[str]
    cwd: Path


class _StopRequest:
    """Signal handler that only takes note: the servers are then stopped, never cut short."""

    def __init__(self) -> None:
        self.requested = False

    def __call__(self, signum: int, frame: FrameType | None) -> None:
        self.requested = True


def pnpm() -> list[str]:
    """The command that runs pnpm: pnpm itself or, failing that, Node.js's corepack."""
    if executable := shutil.which("pnpm"):
        return [executable]
    if corepack := shutil.which("corepack"):
        return [corepack, "pnpm"]
    raise SystemExit("pnpm not found: install Node.js 22 or later and run `corepack enable pnpm`.")


def start(server: Server) -> subprocess.Popen[bytes]:
    """Start a server in a process group of its own, so that its whole tree can be stopped."""
    if sys.platform == "win32":
        return subprocess.Popen(  # noqa: S603 - our own commands, without a shell
            server.command,
            cwd=server.cwd,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(  # noqa: S603 - our own commands, without a shell
        server.command, cwd=server.cwd, stdin=subprocess.DEVNULL, start_new_session=True
    )


def stop(process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
    """Stop a server and every process it started, forcing them after ``timeout`` seconds."""
    if sys.platform == "win32":
        if process.poll() is None:
            # pnpm is a .cmd shim on Windows: only a tree kill reaches the node process behind it.
            taskkill = shutil.which("taskkill") or "taskkill"
            subprocess.run(  # noqa: S603 - fixed arguments
                [taskkill, "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout)
    else:
        group = process.pid  # start_new_session: the server leads its own process group

        def alive() -> bool:
            process.poll()  # reap the server once it exits, so that it no longer counts
            try:
                os.killpg(group, 0)
            except (ProcessLookupError, PermissionError):
                return False
            return True

        with contextlib.suppress(ProcessLookupError):
            os.killpg(group, signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while alive():
            if time.monotonic() >= deadline:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)  # what ignored SIGTERM or outlived the server
                break
            time.sleep(0.05)
        process.wait()


def _termination_signals() -> list[signal.Signals]:
    if sys.platform == "win32":
        return [signal.SIGINT, signal.SIGTERM]
    return [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]  # SIGHUP: the terminal was closed


def run(servers: Sequence[Server]) -> int:
    """Run the servers until Ctrl+C or until one of them stops, then stop all of them.

    Returns:
        0 after Ctrl+C, or the exit code of the server that stopped on its own (128 + N
        when signal N ended it, as shells report it).
    """
    request = _StopRequest()
    previous = {number: signal.signal(number, request) for number in _termination_signals()}
    processes: list[tuple[Server, subprocess.Popen[bytes]]] = []
    try:
        for server in servers:
            # one by one: if a server fails to start, the ones already running are stopped
            processes.append((server, start(server)))  # noqa: PERF401
        while not request.requested:
            for server, process in processes:
                if (code := process.poll()) is not None:
                    message = f"{server.name} stopped with exit code {code}: stopping the rest."
                    print(message, file=sys.stderr, flush=True)  # noqa: T201
                    return code if code >= 0 else 128 - code
            time.sleep(POLL_SECONDS)
        return 0
    finally:
        for _, process in processes:
            stop(process)
        for number, handler in previous.items():
            if handler is not None:
                signal.signal(number, handler)


def main(argv: Sequence[str] | None = None) -> int:
    """Install the web app's dependencies when missing, then run the API and the web app."""
    parser = argparse.ArgumentParser(prog="dev", description="Run the API and the web app.")
    parser.add_argument(
        "--preview", action="store_true", help="serve the production build (no live reload)"
    )
    arguments = parser.parse_args(argv)
    node = pnpm()
    steps = [] if (WEB / "node_modules").is_dir() else [[*node, "install"]]
    if arguments.preview:
        steps.append([*node, "build"])
    try:
        for step in steps:
            if (code := subprocess.run(step, cwd=WEB, check=False).returncode) != 0:  # noqa: S603
                return code
    except KeyboardInterrupt:
        return 130
    api = [sys.executable, "-m", "investinglab_api", *([] if arguments.preview else ["--reload"])]
    web = [*node, "start" if arguments.preview else "dev"]
    print(ADDRESSES, flush=True)  # noqa: T201
    return run([Server("API", api, ROOT), Server("web", web, WEB)])


if __name__ == "__main__":
    sys.exit(main())
