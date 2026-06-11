"""Identity and instruction file controls.

SOUL.md / HERMES.md / AGENTS.md and the config system prompt are first-class
workflow controls: discover, inspect provenance, edit, and copy between
profiles — never just raw file dumps.
"""
from __future__ import annotations

from typing import Any

from hermes_paths import (
    backup_file,
    config_path,
    dump_yaml,
    hermes_home,
    load_profile_config,
    profile_dir,
    read_text,
    write_audit,
)

IDENTITY_FILES = ("SOUL.md", "HERMES.md", "AGENTS.md")


def _file_entry(profile: str, name: str) -> dict[str, Any]:
    local = profile_dir(profile) / name
    inherited = hermes_home() / name
    if local.exists():
        status = "profile-local"
        active = local
    elif inherited.exists():
        status = "inherited-from-default"
        active = inherited
    else:
        status = "missing"
        active = None
    return {
        "name": name,
        "status": status,
        "profile_path": str(local),
        "profile_exists": local.exists(),
        "inherited_path": str(inherited),
        "inherited_exists": inherited.exists(),
        "active_path": str(active) if active else None,
        "bytes": active.stat().st_size if active else 0,
        "mtime": active.stat().st_mtime if active else None,
        "editable": True,
    }


def identity_status(profile: str) -> dict[str, Any]:
    cfg = load_profile_config(profile)
    agent = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    system_prompt = str(agent.get("system_prompt") or "")
    return {
        "profile": profile,
        "files": [_file_entry(profile, name) for name in IDENTITY_FILES],
        "system_prompt": {
            "present": bool(system_prompt.strip()),
            "source": str(config_path(profile)),
            "config_key": "agent.system_prompt",
            "text": system_prompt,
        },
    }


def read_identity_file(profile: str, name: str) -> dict[str, Any]:
    if name not in IDENTITY_FILES:
        raise ValueError(f"not an identity file: {name}")
    entry = _file_entry(profile, name)
    text = ""
    if entry["active_path"]:
        text = read_text(profile_dir(profile) / name) if entry["profile_exists"] else read_text(hermes_home() / name)
    return {**entry, "text": text}


def write_identity_file(profile: str, name: str, text: str, confirm: bool) -> dict[str, Any]:
    if name not in IDENTITY_FILES:
        raise ValueError(f"not an identity file: {name}")
    if not confirm:
        raise ValueError("confirm=true required to write identity files")
    target = profile_dir(profile) / name
    backup = backup_file(profile, target, "identity") if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    write_audit("write_identity_file", profile, {
        "file": name, "path": str(target), "bytes": len(text.encode("utf-8")),
        "backup": str(backup) if backup else None,
    })
    return {"ok": True, "backup": str(backup) if backup else None, "entry": _file_entry(profile, name)}


def copy_identity_file(profile: str, name: str, source: str, confirm: bool) -> dict[str, Any]:
    """Copy SOUL.md/HERMES.md/AGENTS.md from another profile or 'default' (hermes home)."""
    if name not in IDENTITY_FILES:
        raise ValueError(f"not an identity file: {name}")
    if not confirm:
        raise ValueError("confirm=true required to copy identity files")
    src = (hermes_home() / name) if source == "default" else (profile_dir(source) / name)
    if not src.exists():
        raise FileNotFoundError(f"{name} not found in source '{source}'")
    result = write_identity_file(profile, name, read_text(src), confirm=True)
    write_audit("copy_identity_file", profile, {"file": name, "source": source, "source_path": str(src)})
    return result


def set_system_prompt(profile: str, text: str, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise ValueError("confirm=true required to write the system prompt")
    cp = config_path(profile)
    cfg = load_profile_config(profile)
    agent = cfg.setdefault("agent", {})
    if not isinstance(agent, dict):
        cfg["agent"] = agent = {}
    backup = backup_file(profile, cp, "config") if cp.exists() else None
    agent["system_prompt"] = text
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(dump_yaml(cfg), encoding="utf-8")
    write_audit("set_system_prompt", profile, {
        "config_path": str(cp), "bytes": len(text.encode("utf-8")),
        "backup": str(backup) if backup else None,
    })
    return {"ok": True, "backup": str(backup) if backup else None}
