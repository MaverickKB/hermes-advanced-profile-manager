"""Domains and roles as managed library primitives.

Stored as JSON under .profile-manager/library/ (these are manager concepts,
not Hermes-native config). Built-in entries seed the library; user-created
entries persist and can be created inline mid-workflow. Skill groups are NOT
stored here — they are Hermes-native manifests handled by skill_groups.py
against the canonical HERMES_HOME locations.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import hermes_paths
from hermes_paths import write_audit

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

BUILTIN_DOMAINS = {
    "coding": {"description": "Software building, debugging, repo work."},
    "ui-ux": {"description": "Visual design, layout critique, browser verification."},
    "research": {"description": "Web research, source quality, synthesis."},
    "devops": {"description": "Deployment, services, host operations."},
    "profile-management": {"description": "Hermes profile configuration and orchestration."},
    "memory-continuity": {"description": "Continuity, AetherMind, world state."},
    "writing": {"description": "Drafting, editing, narrative work."},
    "home-automation": {"description": "Home Assistant, kiosk, world control."},
    "review": {"description": "Critique, audit, verification."},
    "rmm-support": {"description": "Remote monitoring/management and MSP support operations."},
}

BUILTIN_ROLES = {
    "operator": {"risk": "local-write", "review": "self-review with diff", "description": "Hands-on primary operator."},
    "orchestrator": {"risk": "coordination", "review": "requires manager/reviewer graph", "description": "Coordinates specialists; does not own domain writes."},
    "reviewer": {"risk": "read-only", "review": "no direct writes by default", "description": "Critique and verification only."},
    "specialist": {"risk": "bounded-write", "review": "domain-scoped writes", "description": "Deep single-domain executor."},
    "worker": {"risk": "bounded-write", "review": "manager-approved writes", "description": "Delegated bounded task executor."},
    "analyst": {"risk": "read-only", "review": "analysis-only, no mutation", "description": "Analysis-only worker; cannot mutate external systems."},
}

def _store_path(kind: str):
    hermes_paths.LIBRARY.mkdir(parents=True, exist_ok=True)
    return hermes_paths.LIBRARY / f"{kind}.json"


def _load(kind: str) -> dict[str, Any]:
    path = _store_path(kind)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(kind: str, data: dict[str, Any]) -> None:
    _store_path(kind).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_name(name: str) -> str:
    name = str(name or "").strip().lower()
    if not NAME_RE.match(name):
        raise ValueError("name must be lowercase alphanumeric with . _ - (max 80 chars)")
    return name


# ------------------------------------------------------------ domains/roles

def list_domains() -> list[dict[str, Any]]:
    custom = _load("domains")
    out = []
    for name, meta in BUILTIN_DOMAINS.items():
        entry = {"name": name, "source": "built-in", **meta}
        if name in custom:
            entry.update(custom[name])
            entry["source"] = "customized"
        out.append(entry)
    for name, meta in custom.items():
        if name not in BUILTIN_DOMAINS:
            out.append({"name": name, "source": "custom", **meta})
    return sorted(out, key=lambda x: x["name"])


def upsert_domain(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = _validate_name(name)
    custom = _load("domains")
    entry = {k: v for k, v in payload.items() if k in {"description", "default_skills", "default_toolsets", "default_mcp", "prompt_sections"}}
    entry["updated_at"] = _ts()
    custom[name] = {**custom.get(name, {}), **entry}
    _save("domains", custom)
    write_audit("upsert_domain", "-", {"domain": name})
    return {"ok": True, "domains": list_domains()}


def delete_domain(name: str) -> dict[str, Any]:
    custom = _load("domains")
    if name not in custom:
        raise KeyError("only custom/customized domains can be deleted")
    del custom[name]
    _save("domains", custom)
    write_audit("delete_domain", "-", {"domain": name})
    return {"ok": True, "domains": list_domains()}


def list_roles() -> list[dict[str, Any]]:
    custom = _load("roles")
    out = []
    for name, meta in BUILTIN_ROLES.items():
        entry = {"name": name, "source": "built-in", **meta}
        if name in custom:
            entry.update(custom[name])
            entry["source"] = "customized"
        out.append(entry)
    for name, meta in custom.items():
        if name not in BUILTIN_ROLES:
            out.append({"name": name, "source": "custom", **meta})
    return sorted(out, key=lambda x: x["name"])


def upsert_role(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = _validate_name(name)
    custom = _load("roles")
    entry = {k: v for k, v in payload.items() if k in {"description", "risk", "review", "forbidden"}}
    entry["updated_at"] = _ts()
    custom[name] = {**custom.get(name, {}), **entry}
    _save("roles", custom)
    write_audit("upsert_role", "-", {"role": name})
    return {"ok": True, "roles": list_roles()}


def delete_role(name: str) -> dict[str, Any]:
    custom = _load("roles")
    if name not in custom:
        raise KeyError("only custom/customized roles can be deleted")
    del custom[name]
    _save("roles", custom)
    write_audit("delete_role", "-", {"role": name})
    return {"ok": True, "roles": list_roles()}
