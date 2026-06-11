"""Shared Hermes home/profile path resolution and manager state.

Single source of truth for where the managed Hermes installation lives, how
profile files are located, and where this manager keeps its own state
(backups, audit log, libraries). Imported by server.py and every control
module so path policy lives in exactly one place.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    print("PyYAML is required: python3 -m pip install pyyaml", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".profile-manager"
BACKUPS = STATE / "backups"
AUDIT = STATE / "audit.jsonl"
LIBRARY = STATE / "library"


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _owns_profiles(path: Path) -> bool:
    return (path / "profiles").is_dir()


def hermes_home() -> Path:
    """Resolve the managed Hermes installation root portably.

    Resolution order:
    1. PROFILE_MANAGER_HERMES_HOME — explicit manager override (CLI --hermes-home
       sets this); trusted as-is.
    2. HERMES_HOME, when it actually owns a profiles/ directory.
    3. Walk up from HERMES_HOME: Hermes sessions can expose a profile directory
       (e.g. <home>/profiles/<name>) or a profile-scoped sandbox as HERMES_HOME;
       the nearest ancestor owning profiles/ is the real installation root.
    4. ~/.hermes as the conventional default location.
    """
    override = os.environ.get("PROFILE_MANAGER_HERMES_HOME")
    if override:
        return Path(override).expanduser()
    env = os.environ.get("HERMES_HOME")
    if env:
        candidate = Path(env).expanduser()
        if _owns_profiles(candidate):
            return candidate
        for ancestor in candidate.parents:
            if _owns_profiles(ancestor):
                return ancestor
    return Path.home() / ".hermes"


def profiles_root() -> Path:
    return hermes_home() / "profiles"


def profile_dir(name: str) -> Path:
    safe = Path(name)
    if safe.is_absolute() or ".." in safe.parts or len(safe.parts) != 1 or not name.strip():
        raise ValueError("invalid profile name")
    return profiles_root() / name


def config_path(name: str) -> Path:
    d = profile_dir(name)
    for candidate in (d / "config.yaml", d / "config.yml"):
        if candidate.exists():
            return candidate
    return d / "config.yaml"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_yaml_text(text: str) -> tuple[Any | None, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:
        issues.append({"severity": "error", "scope": "yaml", "message": str(exc)})
        data = None
    return data, issues


def load_profile_config(profile: str) -> dict[str, Any]:
    cp = config_path(profile)
    if not cp.exists():
        return {}
    data, _issues = parse_yaml_text(read_text(cp))
    return data if isinstance(data, dict) else {}


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def write_audit(event: str, profile: str, details: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    rec = {"ts": utc(), "event": event, "profile": profile, "details": details}
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def audit_tail(limit: int = 200) -> list[dict[str, Any]]:
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def backup_file(profile: str, path: Path, kind: str = "config") -> Path:
    """Copy any profile-owned file into this manager's backup store."""
    if not path.exists():
        raise FileNotFoundError(f"No {kind} file to back up for {profile}: {path}")
    bdir = BACKUPS / profile
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)
    dest = bdir / f"{stamp}-{safe_name}"
    shutil.copy2(path, dest)
    if path.name == ".env" or path.name == "auth.json":
        os.chmod(dest, 0o600)
    return dest


def backup_config(profile: str) -> Path:
    return backup_file(profile, config_path(profile), "config")


def list_backups(profile: str) -> list[dict[str, Any]]:
    bdir = BACKUPS / profile
    if not bdir.exists():
        return []
    out = []
    for p in sorted(bdir.iterdir(), reverse=True):
        if not p.is_file():
            continue
        kind = "config" if "config" in p.name else "env" if p.name.endswith(".env") or "-.env" in p.name else "auth" if "auth.json" in p.name else "identity" if p.name.endswith(".md") else "other"
        out.append({
            "name": p.name,
            "path": str(p),
            "kind": kind,
            "bytes": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "created": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return out
