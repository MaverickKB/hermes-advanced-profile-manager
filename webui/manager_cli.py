#!/usr/bin/env python3
"""Profile Manager lifecycle CLI.

Beginner-simple, power-user-friendly control of the WebUI server:

    profile-manager start     launch detached in the background, print the URL
    profile-manager stop      shut the background server down
    profile-manager status    is it running? where?
    profile-manager restart   stop + start
    profile-manager run       run in the foreground (logs to the terminal)
    profile-manager open      open the running UI in a browser
    profile-manager install-skill   install the agent-launchable Hermes skill

The detached server never occupies a terminal: it daemonizes with a pidfile
and log under .profile-manager/, works on macOS/Linux (POSIX sessions) and
Windows (detached process group), and can also be shut down from the UI
power button or a plain `kill`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

WEBUI_DIR = Path(__file__).resolve().parent
ROOT = WEBUI_DIR.parent
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

import hermes_paths  # noqa: E402

DEFAULT_PORT = 5194
DEFAULT_HOST = "127.0.0.1"


def pidfile(port: int) -> Path:
    # Port-keyed: parallel instances (and test runs) never collide.
    return hermes_paths.STATE / f"server-{port}.pid"


def logfile(port: int) -> Path:
    return hermes_paths.STATE / f"server-{port}.log"


def read_pidfile(port: int) -> dict | None:
    pf = pidfile(port)
    if not pf.exists():
        return None
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def health(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/state", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def current_status(ns=None) -> dict:
    host = getattr(ns, "host", DEFAULT_HOST) if ns else DEFAULT_HOST
    port = getattr(ns, "port", DEFAULT_PORT) if ns else DEFAULT_PORT
    info = read_pidfile(port) or {}
    pid = info.get("pid")
    running = bool(pid and pid_alive(int(pid)))
    if not running and port_in_use(host, port):
        # server exists but wasn't started by this CLI (e.g. `run` mode)
        return {"running": True, "pid": None, "host": host, "port": port,
                "url": f"http://{host}:{port}/", "managed": False,
                "healthy": health(host, port)}
    return {
        "running": running,
        "pid": int(pid) if pid else None,
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/",
        "managed": True,
        "healthy": health(host, port) if running else False,
        "log": str(logfile(port)),
    }


def server_args(ns) -> list[str]:
    args = [sys.executable, str(WEBUI_DIR / "server.py"),
            "--host", ns.host, "--port", str(ns.port), "--no-open"]
    if getattr(ns, "hermes_home", ""):
        args += ["--hermes-home", ns.hermes_home]
    return args


def cmd_start(ns) -> int:
    status = current_status(ns)
    if status["running"]:
        print(f"Already running: {status['url']}")
        if not ns.no_open:
            webbrowser.open(status["url"])
        return 0
    if port_in_use(ns.host, ns.port):
        print(f"Port {ns.port} is busy with something else. Pick another: profile-manager start --port <n>", file=sys.stderr)
        return 1
    hermes_paths.STATE.mkdir(parents=True, exist_ok=True)
    log = open(logfile(ns.port), "a", encoding="utf-8")
    kwargs: dict = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL, "cwd": str(ROOT)}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:  # Windows
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    proc = subprocess.Popen(server_args(ns), **kwargs)
    pidfile(ns.port).write_text(json.dumps({
        "pid": proc.pid, "host": ns.host, "port": ns.port, "started_at": time.time(),
    }), encoding="utf-8")
    # wait for health (bounded)
    for _ in range(40):
        if health(ns.host, ns.port, timeout=1.0):
            break
        if proc.poll() is not None:
            print(f"Server exited at startup. See log: {logfile(ns.port)}", file=sys.stderr)
            pidfile(ns.port).unlink(missing_ok=True)
            return 1
        time.sleep(0.25)
    url = f"http://{ns.host}:{ns.port}/"
    print(f"Profile Manager running in the background: {url}")
    print(f"  stop:   profile-manager stop")
    print(f"  status: profile-manager status")
    print(f"  log:    {logfile(ns.port)}")
    if not ns.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return 0


def cmd_stop(ns) -> int:
    status = current_status(ns)
    if not status["running"]:
        print("Not running.")
        pidfile(ns.port).unlink(missing_ok=True)
        return 0
    pid = status.get("pid")
    if not pid:
        # unmanaged (foreground `run` in another terminal, or external launch):
        # ask it to shut down over HTTP rather than guessing at processes.
        try:
            req = urllib.request.Request(
                f"http://{status['host']}:{status['port']}/api/shutdown",
                data=json.dumps({"confirm": True}).encode(), method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3):
                pass
            print("Asked the server to shut down over HTTP.")
            return 0
        except Exception as exc:
            print(f"Server on port {status['port']} was not started by this CLI and HTTP shutdown failed ({exc}).", file=sys.stderr)
            return 1
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not pid_alive(pid):
            break
        time.sleep(0.2)
    if pid_alive(pid):
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    pidfile(ns.port).unlink(missing_ok=True)
    print("Stopped.")
    return 0


def cmd_status(ns) -> int:
    status = current_status(ns)
    if status["running"]:
        mode = "managed background" if status.get("managed") and status.get("pid") else "external/foreground"
        healthstr = "healthy" if status.get("healthy") else "starting or unhealthy"
        print(f"Running ({mode}, {healthstr}): {status['url']}" + (f"  pid {status['pid']}" if status.get("pid") else ""))
        return 0
    print("Not running. Start with: profile-manager start")
    return 3


def cmd_restart(ns) -> int:
    cmd_stop(ns)
    time.sleep(0.4)
    return cmd_start(ns)


def cmd_run(ns) -> int:
    """Foreground mode for power users; Ctrl-C to stop."""
    os.execv(sys.executable, server_args(ns))


def cmd_open(ns) -> int:
    status = current_status(ns)
    if not status["running"]:
        print("Not running. Start with: profile-manager start", file=sys.stderr)
        return 3
    webbrowser.open(status["url"])
    print(status["url"])
    return 0


def cmd_install_skill(ns) -> int:
    """Install the agent-launchable skill into a Hermes home (or profile)."""
    home = Path(ns.hermes_home).expanduser() if ns.hermes_home else hermes_paths.hermes_home()
    skills_dir = home / "skills" / "profile-manager"
    src = ROOT / "skills" / "profile-manager"
    if not src.exists():
        print(f"Skill source missing: {src}", file=sys.stderr)
        return 1
    skills_dir.parent.mkdir(parents=True, exist_ok=True)
    if skills_dir.exists():
        shutil.rmtree(skills_dir)
    shutil.copytree(src, skills_dir)
    # Personalize the installed copy (the source stays generic): pin the checkout.
    env_file = skills_dir / "scripts" / "profile-manager.env"
    env_file.write_text(f"PROFILE_MANAGER_HOME={ROOT}\n", encoding="utf-8")
    wrapper = skills_dir / "scripts" / "launch-profile-manager"
    if wrapper.exists():
        os.chmod(wrapper, 0o755)
    print(f"Installed skill to {skills_dir}")
    print("Agents can now run: scripts/launch-profile-manager start")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="profile-manager",
        description="Hermes Advanced Profile Manager — start/stop the WebUI without occupying a terminal.",
    )
    ap.add_argument("command", nargs="?", default="start",
                    choices=["start", "stop", "status", "restart", "run", "open", "install-skill"],
                    help="lifecycle command (default: start)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--hermes-home", default="", help="explicit Hermes installation root")
    ns = ap.parse_args(argv)
    if ns.hermes_home:
        os.environ["PROFILE_MANAGER_HERMES_HOME"] = str(Path(ns.hermes_home).expanduser())
    handler = {
        "start": cmd_start, "stop": cmd_stop, "status": cmd_status,
        "restart": cmd_restart, "run": cmd_run, "open": cmd_open,
        "install-skill": cmd_install_skill,
    }[ns.command]
    return handler(ns)


if __name__ == "__main__":
    raise SystemExit(main())
