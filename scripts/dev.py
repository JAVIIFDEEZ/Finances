"""Run the API and the web app together (``just dev`` and ``just preview``).

The same launcher works in bash, zsh and PowerShell (``just`` runs its recipes with
PowerShell on Windows). Each server runs in a process group of its own: Ctrl+C stops both,
together with every process they started (uvicorn's reloader, Next.js workers), and when one
of them stops on its own the other one is stopped too.

When a database is configured (``INVESTINGLAB_API_DATABASE_URL``), its schema is brought up to
date first. Before starting, it checks that no other program holds the ports (the API's, 8000 unless
``INVESTINGLAB_API_PORT`` says otherwise in the environment or in ``.env``, and the web app's
3000) and points the web app at the API's port, so running both elsewhere takes a single
variable. When a port is taken it says who holds it (an InvestingLab API still running, a
Docker container such as another project's backend, or a program by name and PID) and how to
free it.

By default both listen on this machine only. ``--lan`` serves the web app to the local
network as well, to open it from a phone on the same Wi-Fi: the API stays on this machine (the
web app proxies to it), but there is no login yet, so anyone on that network can use it.

Usage::

    uv run python scripts/dev.py            # API and web app, both with live reload
    uv run python scripts/dev.py --preview  # API and the production build of the web app
    uv run python scripts/dev.py --preview --lan   # ...also reachable from the local network
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import FrameType

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
LOCALHOST = "127.0.0.1"
WEB_PORT = 3000
POLL_SECONDS = 0.2
DOCKER_FORWARDERS = ("com.docker", "wslrelay", "vpnkit", "docker-proxy")
"""Processes that hold the published ports of Docker containers."""


@dataclass(frozen=True, slots=True)
class Server:
    """A server to run: its name in messages, its command and its working directory."""

    name: str
    command: Sequence[str]
    cwd: Path
    env: Mapping[str, str] | None = None


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


def api_port() -> int:
    """The API's port as the API reads it: ``INVESTINGLAB_API_PORT`` (environment or ``.env``).

    Raises:
        SystemExit: If the port, or another API setting, is not valid.
    """
    from pydantic import ValidationError  # noqa: PLC0415 - only the launcher needs it

    from investinglab_api.settings import ApiSettings  # noqa: PLC0415

    try:
        return ApiSettings().port
    except ValidationError as error:
        for problem in error.errors():
            if problem["loc"] == ("port",):
                raise SystemExit(
                    f"INVESTINGLAB_API_PORT must be a port number, not {problem['input']!r}."
                ) from None
        raise SystemExit(f"The API settings are not valid: {error}") from None


def listening(port: int, host: str = LOCALHOST) -> bool:
    """Whether some program already accepts connections on ``host:port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) == 0


@dataclass(frozen=True, slots=True)
class Holder:
    """Who holds a port and, when it is known, the command that frees it."""

    who: str
    stop: str | None = None


def _output(command: Sequence[str]) -> str:
    """What a diagnostic command prints; empty when it is missing, fails or hangs."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed diagnostic commands
            command, check=False, text=True, capture_output=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def investinglab_api(port: int) -> bool:
    """Whether InvestingLab's own API answers there (its liveness has ``core_version``)."""
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    try:
        with direct.open(f"http://{LOCALHOST}:{port}/health/live", timeout=1.0) as response:
            body = json.load(response)
    except (OSError, ValueError):
        return False
    return isinstance(body, dict) and "core_version" in body


def container(port: int) -> str | None:
    """The Docker container that publishes ``port``, if Docker runs one."""
    docker = shutil.which("docker")
    if docker is None:
        return None
    names = _output([docker, "ps", "--filter", f"publish={port}", "--format", "{{.Names}}"])
    return next(iter(names.split()), None)


def windows_listener(netstat: str, port: int) -> int | None:
    """The PID listening on ``port`` in ``netstat -ano -p TCP`` (any Windows language).

    The state column is translated (LISTENING, ESCUCHANDO...), so a listener is told by its
    remote address instead: port 0.
    """
    for line in netstat.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() != "TCP" or not parts[-1].isdigit():  # noqa: PLR2004
            continue
        local, remote = parts[1], parts[2]
        if local.rsplit(":", 1)[-1] == str(port) and remote.rsplit(":", 1)[-1] == "0":
            return int(parts[-1])
    return None


def windows_task(tasklist: str) -> str | None:
    """The image name in ``tasklist /FO CSV /NH`` output (``None`` if no task matched)."""
    for row in csv.reader(tasklist.splitlines()):
        if len(row) >= 2 and row[1].strip().isdigit():  # noqa: PLR2004 - name, PID, ...
            return row[0]
    return None


def lsof_listener(lsof: str) -> tuple[int, str] | None:
    """The PID and command in ``lsof -Fpc`` output."""
    pid = command = None
    for line in lsof.splitlines():
        if line.startswith("p") and line[1:].isdigit() and pid is None:
            pid = int(line[1:])
        elif line.startswith("c") and command is None:
            command = line[1:]
    return (pid, command or "?") if pid is not None else None


def process(port: int) -> tuple[int, str] | None:
    """The PID and name of the program listening on ``port``, if the system tells."""
    if sys.platform == "win32":
        pid = windows_listener(_output(["netstat", "-ano", "-p", "TCP"]), port)
        if pid is None:
            return None
        name = windows_task(_output(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]))
        return pid, name or "?"
    return lsof_listener(_output(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"]))


def _kill(pid: int) -> str:
    return f"Stop-Process -Id {pid}" if sys.platform == "win32" else f"kill {pid}"


def holder(port: int) -> Holder:
    """Who holds ``port``: an InvestingLab API, a Docker container or a program."""
    found = process(port)
    if investinglab_api(port):
        where, stop = "", "Ctrl+C in its terminal"
        if found:
            where, stop = f" (PID {found[0]})", f"{stop}, or `{_kill(found[0])}`"
        return Holder(
            f"an InvestingLab API that is still running{where}: an earlier `just dev`, "
            "`just preview` or `just api`",
            stop,
        )
    if name := container(port):
        return Holder(f"the Docker container `{name}`", f"`docker stop {name}`")
    if found is None:
        return Holder("another program")
    pid, name = found
    if name.lower().startswith(DOCKER_FORWARDERS):
        return Holder(
            f"a Docker container ({name}, PID {pid}, forwards its port)",
            "`docker stop <name>` (`docker ps` lists the containers and their ports)",
        )
    return Holder(f"{name} (PID {pid})", f"`{_kill(pid)}`")


def _find(port: int) -> str:
    if sys.platform == "win32":
        listener = f"(Get-NetTCPConnection -LocalPort {port} -State Listen)"
        return f"Get-Process -Id {listener}.OwningProcess"
    return f"lsof -nP -iTCP:{port} -sTCP:LISTEN"


def free_port(after: int, tries: int = 20) -> int | None:
    """The first port after ``after`` that nothing listens on."""
    return next((p for p in range(after + 1, after + 1 + tries) if not listening(p)), None)


def _busy(port: int, role: str, found: Holder) -> str:
    stop = f"Stop it with {found.stop}" if found.stop else f"To see which one: {_find(port)}"
    return f"Port {port} ({role}) is held by {found.who}. {stop}."


def busy_ports(api: int) -> list[str]:
    """What to do about each port another program already holds (none: ready to start)."""
    problems = []
    if listening(api):
        message = _busy(api, "API", holder(api))
        spare = free_port(api)
        if spare is not None:
            message += (
                f"\nOr run the API on another port: add INVESTINGLAB_API_PORT={spare} to .env "
                "(the web app follows it)."
            )
        problems.append(message)
    if listening(WEB_PORT):
        problems.append(
            _busy(WEB_PORT, "web app", holder(WEB_PORT))
            + " The web app always uses this port (another `just dev` or `just preview`?)."
        )
    return problems


def database_configured() -> bool:
    """Whether the API will use a database (the environment or ``.env`` name one)."""
    from investinglab_api.settings import ApiSettings  # noqa: PLC0415 - only the launcher needs it

    return ApiSettings().database_url is not None


def lan_address() -> str | None:
    """This machine's address on the local network, if it has one.

    No packet is sent: connecting a UDP socket only asks the system which interface it
    would use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed
        except OSError:
            return None
        address: str = probe.getsockname()[0]
    return None if address.startswith("127.") else address


def start(server: Server) -> subprocess.Popen[bytes]:
    """Start a server in a process group of its own, so that its whole tree can be stopped."""
    if sys.platform == "win32":
        return subprocess.Popen(  # noqa: S603 - our own commands, without a shell
            server.command,
            cwd=server.cwd,
            env=server.env,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(  # noqa: S603 - our own commands, without a shell
        server.command,
        cwd=server.cwd,
        env=server.env,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
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
    parser.add_argument(
        "--lan",
        action="store_true",
        help="serve the web app to the local network too (to open it from a phone)",
    )
    arguments = parser.parse_args(argv)
    port = api_port()
    if problems := busy_ports(port):
        print("\n".join(problems), file=sys.stderr)  # noqa: T201
        return 1
    node = pnpm()
    # The web app proxies to the API (next.config.ts), also when it is built: same variable.
    web_env = {"INVESTINGLAB_API_URL": f"http://{LOCALHOST}:{port}", **os.environ}
    steps = [] if (WEB / "node_modules").is_dir() else [[*node, "install"]]
    if arguments.preview:
        steps.append([*node, "build"])
    try:
        if database_configured():
            migrate = [sys.executable, "-m", "investinglab_api", "db", "upgrade"]
            if (code := subprocess.run(migrate, cwd=ROOT, check=False).returncode) != 0:  # noqa: S603
                return code
        for step in steps:
            done = subprocess.run(step, cwd=WEB, env=web_env, check=False)  # noqa: S603
            if done.returncode != 0:
                return done.returncode
    except KeyboardInterrupt:
        return 130
    api = [sys.executable, "-m", "investinglab_api", *([] if arguments.preview else ["--reload"])]
    host = "0.0.0.0" if arguments.lan else LOCALHOST  # noqa: S104 - asked for with --lan
    web = [*node, "start" if arguments.preview else "dev", "--hostname", host]
    print(  # noqa: T201
        f"API: http://{LOCALHOST}:{port}/docs | web: http://localhost:{WEB_PORT} | "
        "Ctrl+C stops both",
        flush=True,
    )
    if arguments.lan:
        address = lan_address()
        where = f"http://{address}:{WEB_PORT}" if address else f"port {WEB_PORT} of this machine"
        print(  # noqa: T201
            f"From a phone on the same Wi-Fi: {where}\n"
            "There is no login yet: anyone on this network can open it. Use it at home only.",
            flush=True,
        )
    return run([Server("API", api, ROOT), Server("web", web, WEB, web_env)])


if __name__ == "__main__":
    sys.exit(main())
