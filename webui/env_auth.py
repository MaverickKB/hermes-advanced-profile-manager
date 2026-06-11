"""Masked profile .env editor and auth.json source/policy manager.

Secrets policy: values are never returned unmasked except through the single
explicit reveal endpoint, never written to the audit log, and never copied
into project docs. Writes require confirm=true, take a backup first, and set
0600 on secret files.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any

from hermes_paths import backup_file, hermes_home, profile_dir, read_text, write_audit

ENV_LINE_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
AUTH_STALE_DAYS = 90


# ---------------------------------------------------------------- .env editor

def global_env_path() -> Path:
    return hermes_home() / ".env"


def env_path(profile: str) -> Path:
    return profile_dir(profile) / ".env"


def parse_env(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in text.splitlines():
        m = ENV_LINE_KEY.match(line)
        if not m:
            continue
        value = m.group(2).strip().strip('"').strip("'")
        entries.append({"key": m.group(1), "value": value})
    return entries


def _mask(value: str) -> str:
    return f"•••• ({len(value)} chars)" if value else "(empty)"


def env_status(profile: str) -> dict[str, Any]:
    p = env_path(profile)
    g = global_env_path()
    entries = parse_env(read_text(p)) if p.exists() else []
    scope = "profile-specific" if p.exists() else ("inherited-global-only" if g.exists() else "none")
    warnings = []
    if profile == "default":
        warnings.append(f"'{profile}' is a primary profile; env edits here affect core operation.")
    return {
        "profile": profile,
        "path": str(p),
        "exists": p.exists(),
        "scope": scope,
        "global_path": str(g),
        "global_exists": g.exists(),
        "keys": [{"key": e["key"], "masked": _mask(e["value"]), "length": len(e["value"])} for e in entries],
        "global_keys": [e["key"] for e in parse_env(read_text(g))] if g.exists() else [],
        "warnings": warnings,
    }


def _write_env(path: Path, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{e['key']}={e['value']}\n" for e in entries)
    path.write_text(body, encoding="utf-8")
    os.chmod(path, 0o600)


def env_apply(profile: str, ops: list[dict[str, Any]], confirm: bool) -> dict[str, Any]:
    """ops: [{op: set|remove, key, value?}] — audited by key name only."""
    if not confirm:
        raise ValueError("confirm=true required to edit .env")
    p = env_path(profile)
    entries = parse_env(read_text(p)) if p.exists() else []
    backup = backup_file(profile, p, "env") if p.exists() else None
    index = {e["key"]: e for e in entries}
    audit_ops = []
    for op in ops:
        action = str(op.get("op") or "")
        key = str(op.get("key") or "").strip()
        if not key or not ENV_LINE_KEY.match(f"{key}=x"):
            raise ValueError(f"invalid env key: {key!r}")
        if action == "set":
            value = str(op.get("value") or "")
            if key in index:
                index[key]["value"] = value
            else:
                entry = {"key": key, "value": value}
                entries.append(entry)
                index[key] = entry
            audit_ops.append({"op": "set", "key": key})
        elif action == "remove":
            entries = [e for e in entries if e["key"] != key]
            index.pop(key, None)
            audit_ops.append({"op": "remove", "key": key})
        else:
            raise ValueError(f"unsupported env op: {action!r}")
    _write_env(p, entries)
    write_audit("env_apply", profile, {"path": str(p), "ops": audit_ops, "backup": str(backup) if backup else None})
    return {"ok": True, "backup": str(backup) if backup else None, "status": env_status(profile)}


def env_copy(profile: str, source: str, confirm: bool) -> dict[str, Any]:
    """Copy .env wholesale from 'global' or another profile."""
    if not confirm:
        raise ValueError("confirm=true required to copy .env")
    src = global_env_path() if source == "global" else env_path(source)
    if not src.exists():
        raise FileNotFoundError(f".env not found in source '{source}'")
    p = env_path(profile)
    backup = backup_file(profile, p, "env") if p.exists() else None
    _write_env(p, parse_env(read_text(src)))
    write_audit("env_copy", profile, {"source": source, "backup": str(backup) if backup else None})
    return {"ok": True, "backup": str(backup) if backup else None, "status": env_status(profile)}


def env_reveal(profile: str, key: str) -> dict[str, Any]:
    """Single-value reveal; the reveal itself is audited (key name only)."""
    p = env_path(profile)
    if not p.exists():
        raise FileNotFoundError("profile has no .env")
    for e in parse_env(read_text(p)):
        if e["key"] == key:
            write_audit("env_reveal", profile, {"key": key})
            return {"key": key, "value": e["value"]}
    raise KeyError(f"key not found: {key}")


def required_env_findings(profile: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Check provider/MCP-declared env key names against profile/global env and process env."""
    available: set[str] = set(os.environ.keys())
    for path in (env_path(profile), global_env_path()):
        if path.exists():
            available |= {e["key"] for e in parse_env(read_text(path))}
    findings = []
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    for name, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        key_env = str(cfg.get("key_env") or cfg.get("api_key_env") or "")
        if key_env and key_env not in available:
            findings.append({"severity": "warning", "scope": "env", "message": f"provider '{name}' wants env key {key_env}, not found in profile/global env or process env"})
    mcp = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
    for name, cfg in mcp.items():
        if not isinstance(cfg, dict):
            continue
        env_map = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
        for env_key in env_map:
            if str(env_key) not in available:
                findings.append({"severity": "info", "scope": "env", "message": f"MCP server '{name}' declares env key {env_key} (value sourced at runtime)"})
    return findings


# ------------------------------------------------------------- auth manager

def auth_path(profile: str) -> Path:
    return profile_dir(profile) / "auth.json"


def default_auth_path() -> Path:
    return hermes_home() / "auth.json"


def _redact_auth(data: dict[str, Any]) -> dict[str, Any]:
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    pool = data.get("credential_pool") if isinstance(data.get("credential_pool"), dict) else {}
    return {
        "active_provider": str(data.get("active_provider") or ""),
        "version": data.get("version"),
        "updated_at": str(data.get("updated_at") or ""),
        "providers": sorted(str(k) for k in providers),
        "credential_pool": sorted(str(k) for k in pool),
    }


def auth_status(profile: str) -> dict[str, Any]:
    p = auth_path(profile)
    d = default_auth_path()
    source = "profile-local" if p.exists() else ("inherited-from-default" if d.exists() else "missing")
    active = p if p.exists() else (d if d.exists() else None)
    meta: dict[str, Any] = {}
    stale = False
    parse_error = None
    if active:
        try:
            meta = _redact_auth(json.loads(read_text(active)))
            updated = meta.get("updated_at") or ""
            if updated:
                ts = dt.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                stale = (dt.datetime.now(dt.timezone.utc) - ts).days > AUTH_STALE_DAYS
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    return {
        "profile": profile,
        "source": source,
        "profile_path": str(p),
        "profile_exists": p.exists(),
        "default_path": str(d),
        "default_exists": d.exists(),
        "active_path": str(active) if active else None,
        "metadata": meta,
        "stale": stale,
        "stale_threshold_days": AUTH_STALE_DAYS,
        "parse_error": parse_error,
    }


def auth_copy(profile: str, source: str, confirm: bool) -> dict[str, Any]:
    """Copy auth.json from 'default' (hermes home) or another profile."""
    if not confirm:
        raise ValueError("confirm=true required to copy auth state")
    src = default_auth_path() if source == "default" else auth_path(source)
    if not src.exists():
        raise FileNotFoundError(f"auth.json not found in source '{source}'")
    p = auth_path(profile)
    backup = backup_file(profile, p, "auth") if p.exists() else None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(read_text(src), encoding="utf-8")
    os.chmod(p, 0o600)
    write_audit("auth_copy", profile, {"source": source, "backup": str(backup) if backup else None})
    return {"ok": True, "backup": str(backup) if backup else None, "status": auth_status(profile)}


def auth_use_default(profile: str, confirm: bool) -> dict[str, Any]:
    """Remove profile-local auth.json so the profile inherits default auth."""
    if not confirm:
        raise ValueError("confirm=true required to change auth source")
    p = auth_path(profile)
    if not p.exists():
        return {"ok": True, "backup": None, "status": auth_status(profile)}
    backup = backup_file(profile, p, "auth")
    p.unlink()
    write_audit("auth_use_default", profile, {"removed": str(p), "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "status": auth_status(profile)}


def auth_remove_provider(profile: str, provider: str, confirm: bool) -> dict[str, Any]:
    """Remove a stale provider entry from profile-local auth.json."""
    if not confirm:
        raise ValueError("confirm=true required to remove auth provider entries")
    p = auth_path(profile)
    if not p.exists():
        raise FileNotFoundError("profile has no local auth.json; copy or create one first")
    data = json.loads(read_text(p))
    removed = []
    for section in ("providers", "credential_pool"):
        block = data.get(section)
        if isinstance(block, dict) and provider in block:
            del block[provider]
            removed.append(section)
    if not removed:
        raise KeyError(f"provider '{provider}' not present in profile auth.json")
    if data.get("active_provider") == provider:
        data["active_provider"] = ""
    backup = backup_file(profile, p, "auth")
    data["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(p, 0o600)
    write_audit("auth_remove_provider", profile, {"provider": provider, "sections": removed, "backup": str(backup)})
    return {"ok": True, "backup": str(backup), "status": auth_status(profile)}
