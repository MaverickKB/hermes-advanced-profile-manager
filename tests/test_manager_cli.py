from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "webui" / "manager_cli.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cli(iso, *args) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["HERMES_HOME"] = str(iso["home"])
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, timeout=40, env=env, cwd=str(ROOT))


def test_lifecycle_start_status_stop(iso, monkeypatch, tmp_path):
    port = _free_port()
    # state dir is monkeypatched in-process only; the CLI subprocess uses the
    # repo state dir — point pid/log at a temp state via env HERMES_HOME and
    # accept the default STATE (it is project-local and isolated per checkout).
    start = _cli(iso, "start", "--port", str(port), "--no-open")
    try:
        assert start.returncode == 0, start.stderr
        assert "running in the background" in start.stdout.lower()

        status = _cli(iso, "status", "--port", str(port))
        assert status.returncode == 0
        assert "Running" in status.stdout

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3) as resp:
            assert resp.status == 200

        # idempotent start reports the existing instance
        again = _cli(iso, "start", "--port", str(port), "--no-open")
        assert "Already running" in again.stdout
    finally:
        stop = _cli(iso, "stop", "--port", str(port))
    assert stop.returncode == 0
    time.sleep(0.5)
    status = _cli(iso, "status", "--port", str(port))
    assert status.returncode == 3
    assert "Not running" in status.stdout


def test_http_shutdown_endpoint(iso):
    port = _free_port()
    start = _cli(iso, "start", "--port", str(port), "--no-open")
    assert start.returncode == 0, start.stderr
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown",
        data=json.dumps({"confirm": True}).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert json.loads(resp.read())["ok"] is True
    deadline = time.time() + 8
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                break
        time.sleep(0.3)
    else:
        _cli(iso, "stop", "--port", str(port))
        raise AssertionError("server did not exit after /api/shutdown")


def test_shutdown_requires_confirm(iso):
    port = _free_port()
    start = _cli(iso, "start", "--port", str(port), "--no-open")
    assert start.returncode == 0, start.stderr
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/shutdown",
            data=b"{}", method="POST", headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        # still alive
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3) as resp:
            assert resp.status == 200
    finally:
        _cli(iso, "stop", "--port", str(port))


def test_install_skill(iso):
    result = _cli(iso, "install-skill")
    assert result.returncode == 0, result.stderr
    skill_dir = iso["home"] / "skills" / "profile-manager"
    assert (skill_dir / "SKILL.md").exists()
    wrapper = skill_dir / "scripts" / "launch-profile-manager"
    assert wrapper.exists()
    env_pin = (skill_dir / "scripts" / "profile-manager.env").read_text()
    assert f"PROFILE_MANAGER_HOME={ROOT}" in env_pin
