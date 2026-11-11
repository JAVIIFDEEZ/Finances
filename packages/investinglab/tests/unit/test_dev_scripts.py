"""Development scripts: the launcher behind ``just dev``/``just preview`` and ``just clean``.

The process tests run real (tiny) Python processes and check them through ``/proc``, so
they only run on Linux, like the CI; Windows takes the ``taskkill`` branch instead.
"""

from __future__ import annotations

import importlib.util
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
        command: list[str], *, cwd: Path, env: dict[str, str], check: bool
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
    assert (app.name, app.command, app.cwd) == ("web", ["pnpm", "dev"], web)


def test_preview_builds_and_serves_without_reload(launcher: dict[str, list[Any]]) -> None:
    (dev.WEB / "node_modules").mkdir()

    assert dev.main(["--preview"]) == 0

    assert launcher["steps"] == [(["pnpm", "build"], dev.WEB, False)]
    api, app = launcher["servers"]
    assert api.command == [sys.executable, "-m", "investinglab_api"]
    assert app.command == ["pnpm", "start"]


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

    assert dev.main([]) == 1

    error = capsys.readouterr().err
    assert f"Port {busy}" in error
    assert advice in error
    assert launcher["steps"] == []
    assert launcher["servers"] == []


def test_listening_tells_whether_a_program_holds_a_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert dev.listening(port)
    assert not dev.listening(port)


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
