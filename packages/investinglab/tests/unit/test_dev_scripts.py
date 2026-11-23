"""Development scripts: the launcher behind ``just dev``/``just preview`` and ``just clean``.

The process tests run real (tiny) Python processes and check them through ``/proc``, so
they only run on Linux, like the CI; Windows takes the ``taskkill`` branch instead.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="checks processes in /proc")


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their annotations through it
    spec.loader.exec_module(module)
    return module


dev = _load("dev")
clean = _load("clean")


def _alive(pid: int) -> bool:
    """Whether the process runs (a zombie has finished: only its parent has not reaped it)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _wait_for(path: Path) -> str:
    deadline = time.monotonic() + 15
    while not path.exists() or not path.read_text(encoding="utf-8"):
        assert time.monotonic() < deadline, f"{path.name} was never written"
        time.sleep(0.05)
    return path.read_text(encoding="utf-8")


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _sleeper(pid_file: Path) -> list[str]:
    """A process that writes its pid once it is ready and then sleeps."""
    return _python(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )


# ── pnpm and the steps before the servers ──────────────────────────────────


def test_pnpm_is_run_directly_or_through_corepack(monkeypatch: pytest.MonkeyPatch) -> None:
    found: dict[str, str | None] = {"pnpm": "/bin/pnpm", "corepack": "/bin/corepack"}
    monkeypatch.setattr(dev.shutil, "which", found.get)

    assert dev.pnpm() == ["/bin/pnpm"]
    found["pnpm"] = None
    assert dev.pnpm() == ["/bin/corepack", "pnpm"]
    found["corepack"] = None
    with pytest.raises(SystemExit, match="corepack enable pnpm"):
        dev.pnpm()


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, list[Any]]:
    """The launcher with pnpm, the steps and the servers recorded instead of run."""
    recorded: dict[str, list[Any]] = {"steps": [], "servers": [], "codes": [], "envs": []}

    def step(
        command: list[str], *, cwd: Path, check: bool, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        recorded["steps"].append((command, cwd, check))
        recorded["envs"].append(env)
        code = recorded["codes"].pop(0) if recorded["codes"] else 0
        return subprocess.CompletedProcess(command, code)

    for variable in ("INVESTINGLAB_API_PORT", "INVESTINGLAB_API_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(dev, "WEB", tmp_path)
    monkeypatch.setattr(dev, "pnpm", lambda: ["pnpm"])
    monkeypatch.setattr(dev, "listening", lambda port, host="127.0.0.1": False)
    monkeypatch.setattr(dev, "database_configured", lambda: False)
    monkeypatch.setattr(dev, "bind_to_launcher", lambda: False)
    monkeypatch.setattr(subprocess, "run", step)

    def run(servers: list[Any]) -> int:
        recorded["servers"].extend(servers)
        return 0

    monkeypatch.setattr(dev, "run", run)
    return recorded


def test_dev_installs_missing_dependencies_and_reloads(launcher: dict[str, list[Any]]) -> None:
    assert dev.main([]) == 0

    web = dev.WEB
    assert launcher["steps"] == [(["pnpm", "install"], web, False)]
    api, app = launcher["servers"]
    assert (api.name, api.command, api.cwd) == (
        "API",
        [sys.executable, "-m", "investinglab_api", "--reload"],
        dev.ROOT,
    )
    assert (app.name, app.cwd) == ("web", web)
    assert app.command == ["pnpm", "dev", "--hostname", "127.0.0.1"]  # this machine only


def test_preview_builds_and_serves_without_reload(launcher: dict[str, list[Any]]) -> None:
    (dev.WEB / "node_modules").mkdir()

    assert dev.main(["--preview"]) == 0

    assert launcher["steps"] == [(["pnpm", "build"], dev.WEB, False)]
    api, app = launcher["servers"]
    assert api.command == [sys.executable, "-m", "investinglab_api"]
    assert app.command == ["pnpm", "start", "--hostname", "127.0.0.1"]


def test_lan_serves_the_web_app_to_the_network_and_says_where(
    launcher: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (dev.WEB / "node_modules").mkdir()
    monkeypatch.setattr(dev, "lan_address", lambda: "192.168.1.74")

    assert dev.main(["--preview", "--lan"]) == 0

    api, app = launcher["servers"]
    assert app.command == ["pnpm", "start", "--hostname", "0.0.0.0"]  # noqa: S104
    assert "--host" not in " ".join(api.command)  # the API never leaves this machine
    output = capsys.readouterr().out
    assert "http://192.168.1.74:3000" in output
    assert "no login" in output

    monkeypatch.setattr(dev, "lan_address", lambda: None)
    assert dev.main(["--preview", "--lan"]) == 0
    assert "port 3000 of this machine" in capsys.readouterr().out


def test_the_lan_address_is_a_network_address_or_nothing() -> None:
    address = dev.lan_address()

    assert address is None or (address.count(".") == 3 and not address.startswith("127."))


def test_the_web_app_follows_the_api_port(
    launcher: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTINGLAB_API_PORT", "8123")

    assert dev.main([]) == 0

    api, app = launcher["servers"]
    assert api.env is None  # the API reads INVESTINGLAB_API_PORT itself
    assert app.env["INVESTINGLAB_API_URL"] == "http://127.0.0.1:8123"
    assert launcher["envs"][0]["INVESTINGLAB_API_URL"] == "http://127.0.0.1:8123"  # install


def test_an_explicit_api_url_wins(
    launcher: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTINGLAB_API_URL", "http://10.0.0.5:9000")

    assert dev.main([]) == 0

    assert launcher["servers"][1].env["INVESTINGLAB_API_URL"] == "http://10.0.0.5:9000"


@pytest.mark.parametrize("port", ["api", "70000", "0"])
def test_the_api_port_must_be_a_port_number(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("INVESTINGLAB_API_PORT", port)

    with pytest.raises(SystemExit, match="INVESTINGLAB_API_PORT must be a port number"):
        dev.api_port()


@pytest.mark.parametrize(
    ("busy", "advice"),
    [(8000, "INVESTINGLAB_API_PORT"), (3000, "another `just dev`")],
    ids=["api", "web"],
)
def test_busy_ports_are_reported_before_anything_starts(
    launcher: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    busy: int,
    advice: str,
) -> None:
    monkeypatch.setattr(dev, "listening", lambda port, host="127.0.0.1": port == busy)
    monkeypatch.setattr(dev, "holder", lambda port: dev.Holder("another program"))

    assert dev.main([]) == 1

    error = capsys.readouterr().err
    assert f"Port {busy}" in error
    assert advice in error
    assert launcher["steps"] == []
    assert launcher["servers"] == []


def test_the_api_port_is_read_like_the_api_reads_it_also_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("INVESTINGLAB_API_PORT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("INVESTINGLAB_API_PORT=8123\n", encoding="utf-8")

    assert dev.api_port() == 8123


def test_a_busy_api_port_says_who_holds_it_and_offers_a_free_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "listening", lambda port, host="127.0.0.1": port in {8000, 8001})
    monkeypatch.setattr(
        dev,
        "holder",
        lambda port: dev.Holder("the Docker container `web_1`", "`docker stop web_1`"),
    )

    (message,) = dev.busy_ports(8000)

    assert message.startswith("Port 8000 (API) is held by the Docker container `web_1`.")
    assert "Stop it with `docker stop web_1`." in message
    assert "INVESTINGLAB_API_PORT=8002 to .env" in message


def test_an_unknown_holder_comes_with_the_command_that_finds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "listening", lambda port, host="127.0.0.1": port == 3000)
    monkeypatch.setattr(dev, "holder", lambda port: dev.Holder("another program"))

    (message,) = dev.busy_ports(8000)

    assert "Port 3000 (web app) is held by another program. To see which one:" in message
    assert "3000" in message.split("To see which one:")[1]


def _holder_with(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ours: bool = False,
    name: str | None = None,
    found: tuple[int, str] | None = None,
) -> Any:
    monkeypatch.setattr(dev, "investinglab_api", lambda port: ours)
    monkeypatch.setattr(dev, "container", lambda port: name)
    monkeypatch.setattr(dev, "process", lambda port: found)
    return dev.holder(8000)


def test_the_holder_is_named_with_the_way_to_free_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kill = "taskkill /PID" if sys.platform == "win32" else "kill"

    ours = _holder_with(monkeypatch, ours=True, found=(4321, "python.exe"))
    assert ours.who.startswith("an InvestingLab API that is still running (PID 4321)")
    tree = " /T /F" if sys.platform == "win32" else ""  # with what the server started
    assert ours.stop == f"Ctrl+C in its terminal, or `{kill} 4321{tree}`"
    assert _holder_with(monkeypatch, ours=True).stop == "Ctrl+C in its terminal"

    backend = _holder_with(
        monkeypatch, name="cryptoworld_backend", found=(99, "com.docker.backend.exe")
    )
    assert backend == dev.Holder(
        "the Docker container `cryptoworld_backend`", "`docker stop cryptoworld_backend`"
    )

    forwarded = _holder_with(monkeypatch, found=(99, "com.docker.backend.exe"))
    assert forwarded.who.startswith("a Docker container (com.docker.backend.exe, PID 99")
    assert forwarded.stop is not None
    assert "docker ps" in forwarded.stop

    other = _holder_with(monkeypatch, found=(77, "node.exe"))
    assert other == dev.Holder("node.exe (PID 77)", f"`{kill} 77{tree}`")
    assert _holder_with(monkeypatch) == dev.Holder("another program")


NETSTAT_ES = """
Conexiones activas

  Proto  Dirección local          Dirección remota        Estado           PID
  TCP    0.0.0.0:135            0.0.0.0:0              ESCUCHANDO       1180
  TCP    127.0.0.1:8000         127.0.0.1:53211        ESTABLECIDO      15872
  TCP    127.0.0.1:53211        127.0.0.1:8000         ESTABLECIDO      9020
  TCP    0.0.0.0:8000           0.0.0.0:0              ESCUCHANDO       15872
  TCP    [::]:8000              [::]:0                 ESCUCHANDO       15872
"""


def test_the_windows_listener_is_found_in_any_language() -> None:
    assert dev.windows_listener(NETSTAT_ES, 8000) == 15872
    assert dev.windows_listener(NETSTAT_ES, 135) == 1180
    assert dev.windows_listener(NETSTAT_ES, 53211) is None  # only a client connection
    english = "  TCP    [::]:3000    [::]:0    LISTENING    4242\n"
    assert dev.windows_listener(english, 3000) == 4242
    assert dev.windows_listener("", 8000) is None


def test_task_and_lsof_outputs_are_read() -> None:
    row = '"com.docker.backend.exe","15872","Console","1","120.512 KB"\n'
    assert dev.windows_task(row) == "com.docker.backend.exe"
    assert dev.windows_task("INFORMACIÓN: no hay tareas ejecutándose con los criterios.\n") is None
    assert dev.lsof_listener("p2024\ncpython3.14\nf7\n") == (2024, "python3.14")
    assert dev.lsof_listener("") is None


def test_diagnostic_commands_that_fail_print_nothing() -> None:
    assert dev._output(["no-such-command-for-investinglab"]) == ""
    assert dev._output(_python("import sys; print('x'); sys.exit(3)")) == ""
    assert dev._output(_python("print('ok')")).strip() == "ok"


def _serve(body: bytes) -> tuple[Any, int]:
    import http.server  # noqa: PLC0415
    import threading  # noqa: PLC0415

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            del format, args

    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_an_investinglab_api_is_told_from_another_server() -> None:
    ours, ours_port = _serve(b'{"status": "ok", "version": "0.1.0", "core_version": "0.1.0"}')
    other, other_port = _serve(b'{"detail": "Not Found"}')
    try:
        assert dev.investinglab_api(ours_port)
        assert not dev.investinglab_api(other_port)
    finally:
        for server in (ours, other):
            server.shutdown()
            server.server_close()
    assert not dev.investinglab_api(ours_port)  # nothing answers any more


def test_the_web_app_is_told_by_its_manifest() -> None:
    ours, ours_port = _serve(b'{"name": "InvestingLab", "short_name": "InvestingLab"}')
    other, other_port = _serve(b'{"name": "CryptoWorld"}')
    try:
        assert dev.investinglab_web(ours_port)
        assert not dev.investinglab_web(other_port)
    finally:
        for server in (ours, other):
            server.shutdown()
            server.server_close()
    assert not dev.investinglab_web(ours_port)


# ── Servers an earlier run left behind ─────────────────────────────────────


def _leftover(
    monkeypatch: pytest.MonkeyPatch,
    *,
    held: bool = True,
    ours: bool = True,
    pid: int | None = 4321,
    orphan: bool = True,
    stops: bool = True,
    port: int = 8001,
    role: str = "API",
) -> tuple[str | None, list[int]]:
    ended: list[int] = []
    monkeypatch.setattr(dev, "listening", lambda port, host="127.0.0.1": held and not ended)
    if not stops:
        monkeypatch.setattr(dev, "listening", lambda port, host="127.0.0.1": held)
    # Each server is told by its own check: the other one says no.
    monkeypatch.setattr(dev, "investinglab_api", lambda port: ours and role == "API")
    monkeypatch.setattr(dev, "investinglab_web", lambda port: ours and role == "web app")
    monkeypatch.setattr(dev, "process", lambda port: None if pid is None else (pid, "python.exe"))
    monkeypatch.setattr(dev, "orphaned", lambda found: orphan)
    monkeypatch.setattr(dev, "end_tree", ended.append)
    return dev.stop_leftover(port, role, timeout=0.3), ended


def test_an_api_whose_launcher_is_gone_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    said, ended = _leftover(monkeypatch)

    assert ended == [4321]
    assert said == "Stopped the InvestingLab API an earlier run left on port 8001 (PID 4321)."


@pytest.mark.parametrize(
    ("case", "kwargs"),
    [
        ("the port is free", {"held": False}),
        ("another program holds it", {"ours": False}),
        ("the system does not say which process", {"pid": None}),
        ("its launcher still runs (`just api` elsewhere)", {"orphan": False}),
    ],
)
def test_anything_else_on_the_port_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, case: str, kwargs: dict[str, Any]
) -> None:
    said, ended = _leftover(monkeypatch, **kwargs)

    assert (said, ended) == (None, []), case


def test_a_leftover_that_will_not_stop_is_reported_as_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    said, ended = _leftover(monkeypatch, stops=False)

    assert ended == [4321]
    assert said is None  # busy_ports then says how to stop it by hand


def test_the_web_app_left_behind_is_told_by_its_own_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    said, ended = _leftover(monkeypatch, port=3000, role="web app")

    assert ended == [4321]
    assert said == "Stopped the InvestingLab web app an earlier run left on port 3000 (PID 4321)."


def _table(*rows: tuple[int, int, str] | tuple[int, int, str, str]) -> dict[int, Any]:
    return {row[0]: dev.Process(*row) for row in rows}


# A `just dev` on Windows: just → uv → the venv's python.exe (a launcher) → the real python
# running dev.py → the API's launcher python.exe → uvicorn's reloader, listening on the port.
LIVE_WINDOWS = _table(
    (100, 4, "explorer.exe", "20261116080000"),
    (200, 100, "WindowsTerminal.exe", "20261116090000"),
    (300, 200, "pwsh.exe", "20261116090001"),
    (400, 300, "just.exe", "20261116100000"),
    (500, 400, "uv.exe", "20261116100001"),
    (600, 500, "python.exe", "20261116100002"),
    (700, 600, "python.exe", "20261116100003"),
    (800, 700, "python.exe", "20261116100004"),
    (900, 800, "python.exe", "20261116100005"),
)


def test_a_server_whose_launcher_still_runs_is_not_a_leftover() -> None:
    assert not dev.orphaned(900, LIVE_WINDOWS)  # it climbs to just.exe, which still runs


def test_a_server_whose_launcher_ended_is_a_leftover() -> None:
    gone = {pid: row for pid, row in LIVE_WINDOWS.items() if pid not in {400, 500, 600, 700}}

    assert dev.orphaned(900, gone)  # its python.exe launcher waits for it; dev.py is gone
    reused = {**gone, 700: dev.Process(700, 1, "chrome.exe", "20261116120000")}
    assert dev.orphaned(900, reused)  # PID 700 now belongs to a younger, unrelated process


def test_an_orphan_is_told_by_who_adopted_it() -> None:
    adopted = _table((1, 0, "process_api"), (650, 1, "uv"), (654, 650, "investinglab-ap"))
    by_systemd = _table((1, 0, "systemd"), (40, 1, "systemd"), (654, 40, "python3.14"))
    in_a_shell = _table(
        (1, 0, "process_api"), (20, 1, "bash"), (650, 20, "uv"), (654, 650, "python3")
    )
    first = _table((1, 0, "python3"), (654, 1, "python3"))  # `just dev` is the container's PID 1

    assert dev.orphaned(654, adopted)
    assert dev.orphaned(654, by_systemd)
    assert not dev.orphaned(654, in_a_shell)  # someone's `uv run investinglab-api` in a terminal
    assert not dev.orphaned(654, first)


def test_in_doubt_a_server_is_not_a_leftover() -> None:
    looped = _table((5, 6, "python"), (6, 5, "python"))

    assert not dev.orphaned(42, LIVE_WINDOWS)  # not in the table
    assert not dev.orphaned(5, looped)
    assert not dev.orphaned(100, LIVE_WINDOWS)  # explorer.exe lost its parent at logon: no server


def test_process_listings_are_read() -> None:
    ps = "    1     0 /sbin/init\n  654   650 investinglab-ap\n  700   654 /usr/bin/python3.14\n"
    cim = (
        '"ProcessId","ParentProcessId","Name","Started"\r\n'
        '"4","0","System",""\r\n'
        '"35196","9000","python.exe","20261116100005"\r\n'
    )

    assert dev.ps_processes(ps)[700] == dev.Process(700, 654, "/usr/bin/python3.14")
    assert set(dev.ps_processes(ps)) == {1, 654, 700}
    assert dev.cim_processes(cim)[35196] == dev.Process(35196, 9000, "python.exe", "20261116100005")
    assert dev.cim_processes(cim)[4].started == ""
    assert dev.ps_processes("") == {}
    assert dev.cim_processes("") == {}


@linux_only
def test_the_processes_of_this_machine_are_listed(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    child = subprocess.Popen(_sleeper(pid_file))  # noqa: S603
    try:
        _wait_for(pid_file)
        table = dev.processes()
        assert table[child.pid].parent == os.getpid()
        assert not dev.orphaned(child.pid, table)  # pytest started it and still runs
    finally:
        child.kill()
        child.wait()


@linux_only
def test_a_leftover_is_ended_with_what_it_started(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild"
    tree = _python(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    leader = dev.start(dev.Server("leftover", tree, tmp_path))  # leads its group, as servers do
    grandchild = int(_wait_for(pid_file))

    dev.end_tree(leader.pid)
    leader.wait(timeout=5)

    deadline = time.monotonic() + 5
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(grandchild)
    dev.end_tree(leader.pid)  # already gone: nothing to do, no error


def test_the_launcher_joins_a_job_only_on_windows() -> None:
    if sys.platform != "win32":
        assert dev.bind_to_launcher() is False


def test_dev_stops_what_an_earlier_run_left_and_goes_on(
    launcher: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    said = {8000: "Stopped the InvestingLab API an earlier run left on port 8000 (PID 1)."}
    monkeypatch.setattr(dev, "stop_leftover", lambda port, role: said.get(port))

    assert dev.main([]) == 0

    assert said[8000] in capsys.readouterr().out
    assert [server.name for server in launcher["servers"]] == ["API", "web"]


def test_listening_tells_whether_a_program_holds_a_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert dev.listening(port)
    assert not dev.listening(port)


def test_the_schema_is_migrated_first_when_a_database_is_configured(
    launcher: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(dev, "database_configured", lambda: True)
    migrate = [sys.executable, "-m", "investinglab_api", "db", "upgrade"]

    assert dev.main([]) == 0
    assert launcher["steps"][0] == (migrate, dev.ROOT, False)
    assert [server.name for server in launcher["servers"]] == ["API", "web", "worker"]
    worker = launcher["servers"][2]
    assert (worker.command, worker.cwd) == (
        [sys.executable, "-m", "investinglab_api", "worker"],
        dev.ROOT,
    )
    output = capsys.readouterr().out
    assert dev.MIGRATING in output  # never a silent wait
    assert "worker running" in output

    launcher["steps"].clear()
    launcher["servers"].clear()
    launcher["codes"].append(1)  # the database is down, or a migration fails

    assert dev.main([]) == 1
    assert [command for command, _, _ in launcher["steps"]] == [migrate]
    assert launcher["servers"] == []
    assert dev.NOT_STARTED in capsys.readouterr().err


def test_ctrl_c_while_migrating_starts_nothing(
    launcher: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupted(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise KeyboardInterrupt

    monkeypatch.setattr(dev, "database_configured", lambda: True)
    monkeypatch.setattr(subprocess, "run", interrupted)

    assert dev.main([]) == 130
    assert launcher["servers"] == []
    assert dev.NOT_STARTED in capsys.readouterr().err


def test_the_launcher_reads_the_database_from_the_api_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("INVESTINGLAB_API_DATABASE_URL", raising=False)
    assert not dev.database_configured()

    monkeypatch.setenv("INVESTINGLAB_API_DATABASE_URL", "postgresql+psycopg://localhost/x")
    assert dev.database_configured()


def test_a_failed_step_stops_before_the_servers(launcher: dict[str, list[Any]]) -> None:
    launcher["codes"].append(2)  # pnpm install fails

    assert dev.main(["--preview"]) == 2

    assert [command for command, _, _ in launcher["steps"]] == [["pnpm", "install"]]
    assert launcher["servers"] == []


# ── Running and stopping the servers ───────────────────────────────────────


@linux_only
@pytest.mark.parametrize(
    ("ending", "code"),
    [
        ("raise SystemExit(3)", 3),
        ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", 137),  # 128 + 9, like a shell
    ],
    ids=["exit-code", "killed"],
)
def test_when_a_server_stops_the_others_are_stopped(tmp_path: Path, ending: str, code: int) -> None:
    pid_file = tmp_path / "pid"
    failing = _python(f"import time; time.sleep(1); {ending}")
    servers = [
        dev.Server("sleeper", _sleeper(pid_file), tmp_path),
        dev.Server("failing", failing, tmp_path),
    ]

    assert dev.run(servers) == code

    assert not _alive(int(_wait_for(pid_file)))


@linux_only
def test_a_stop_request_stops_every_server(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    requester = _python(
        "import os, signal, time\n"
        "time.sleep(1)\n"
        "os.kill(os.getppid(), signal.SIGINT)\n"  # what Ctrl+C sends
    )
    servers = [
        dev.Server("sleeper", _sleeper(pid_file), tmp_path),
        dev.Server("ctrl+c", requester, tmp_path),
    ]

    assert dev.run(servers) == 0  # Ctrl+C is how a dev session ends: not an error

    assert not _alive(int(_wait_for(pid_file)))


@linux_only
def test_stop_ends_the_whole_process_tree(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild"
    tree = _python(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = dev.start(dev.Server("tree", tree, tmp_path))
    grandchild = int(_wait_for(pid_file))

    dev.stop(process, timeout=3)

    assert process.returncode is not None
    assert not _alive(grandchild)


@linux_only
def test_stop_forces_a_server_that_ignores_the_request(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    stubborn = _python(
        "import pathlib, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"pathlib.Path({str(ready)!r}).write_text('ready')\n"
        "time.sleep(60)\n"
    )
    process = dev.start(dev.Server("stubborn", stubborn, tmp_path))
    _wait_for(ready)

    dev.stop(process, timeout=0.5)

    assert process.returncode == -9  # SIGKILL


# ── just clean ─────────────────────────────────────────────────────────────


def test_clean_removes_artefacts_and_caches_but_not_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folders = (".ruff_cache", "pkg/__pycache__", "node_modules/x/__pycache__", ".venv/__pycache__")
    for folder in folders:
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / ".coverage").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "module.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(clean, "ROOT", tmp_path)

    assert clean.main() == 0

    assert not (tmp_path / ".ruff_cache").exists()
    assert not (tmp_path / ".coverage").exists()
    assert not (tmp_path / "pkg" / "__pycache__").exists()
    assert (tmp_path / "pkg" / "module.py").exists()
    assert (tmp_path / "node_modules" / "x" / "__pycache__").exists()
    assert (tmp_path / ".venv" / "__pycache__").exists()
    assert "Removed 3" in capsys.readouterr().out
