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


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@test", "-c", "user.name=t", *args],
                   cwd=str(cwd), check=True, capture_output=True)


def _update_ns():
    import types
    return types.SimpleNamespace(port=_free_port(), host="127.0.0.1", no_open=True, hermes_home="")


def test_update_outside_git_checkout_explains_reinstall(monkeypatch, tmp_path, capsys):
    sys.path.insert(0, "webui")
    import manager_cli
    monkeypatch.setattr(manager_cli, "ROOT", tmp_path)
    rc = manager_cli.cmd_update(_update_ns())
    assert rc == 1
    err = capsys.readouterr().err
    assert "git clone" in err


def test_update_already_current(monkeypatch, tmp_path, capsys):
    sys.path.insert(0, "webui")
    import manager_cli
    src = tmp_path / "checkout"
    src.mkdir()
    _git("init", "-q", cwd=src)
    (src / "f.txt").write_text("1", encoding="utf-8")
    _git("add", ".", cwd=src)
    _git("commit", "-qm", "c1", cwd=src)
    _git("remote", "add", "origin", str(src), cwd=src)
    _git("fetch", "-q", "origin", cwd=src)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(src),
                            capture_output=True, text=True, check=True).stdout.strip()
    _git("branch", "-q", f"--set-upstream-to=origin/{branch}", cwd=src)
    monkeypatch.setattr(manager_cli, "ROOT", src)
    rc = manager_cli.cmd_update(_update_ns())
    assert rc == 0
    assert "Already up to date" in capsys.readouterr().out
